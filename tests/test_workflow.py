import io
import time
import json
import pathlib
from datetime import date

import pytest
from pypdf import PdfWriter
from sqlalchemy import func, select

from moteur.base import Etat, FactureEnBase
from moteur.extraction_llm import ErreurExtraction, ResultatExtraction
from moteur.modeles import Facture
from moteur.workflow import FactureIntrouvable, TransitionInterdite, rejeter, traiter, valider

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
AUJOURD_HUI = date(2026, 11, 14)


def pdf(nom: str) -> bytes:
    return (FACTURES / nom).read_bytes()


class FauxExtracteur:
    """Remplace le LLM : renvoie la facture prévue et compte ses appels."""

    def __init__(self, nom_fichier: str, erreur: Exception | None = None):
        self.facture = Facture.model_validate(ATTENDU[nom_fichier]["facture"])
        self.erreur = erreur
        self.appels = 0

    def __call__(self, texte: str) -> ResultatExtraction:
        self.appels += 1
        if self.erreur:
            raise self.erreur
        return ResultatExtraction(facture=self.facture, duree_s=0.1, fournisseur="test", modele="faux")


def recevoir(session, nom: str, extracteur: FauxExtracteur | None = None):
    return traiter(session, pdf(nom), nom, extracteur or FauxExtracteur(nom), AUJOURD_HUI)


def types_evenements(facture: FactureEnBase) -> list[str]:
    return [evenement.type for evenement in facture.evenements]


def test_une_facture_juste_arrive_a_valider(session):
    resultat = recevoir(session, "facture-F26-1193.pdf")

    facture = resultat.facture
    assert not resultat.deja_vue
    assert facture.etat == Etat.A_VALIDER
    assert facture.anomalies == []
    assert facture.numero_facture == "F26-1193"
    assert facture.donnees["total_ttc"] == "478.08"
    assert types_evenements(facture) == ["RECEPTION", "EXTRACTION", "CONTROLE"]


def test_le_journal_garde_l_etat_et_l_auteur_de_chaque_etape(session):
    facture = recevoir(session, "facture-F26-1193.pdf").facture

    assert [(e.rang, e.etat, e.auteur) for e in facture.evenements] == [
        (1, "recue", "moteur"),
        (2, "extraite", "moteur"),
        (3, "a_valider", "moteur"),
    ]
    assert facture.evenements[1].detail == {"source": "ia", "fournisseur_llm": "test", "modele": "faux", "duree_s": 0.1}


def test_une_facture_au_total_faux_part_en_anomalie(session):
    facture = recevoir(session, "facture-erreur-total.pdf").facture

    assert facture.etat == Etat.EN_ANOMALIE
    assert [anomalie["code"] for anomalie in facture.anomalies] == ["TOTAL_TTC_INCOHERENT"]
    assert facture.anomalies[0]["gravite"] == "bloquante"


def test_le_meme_fichier_envoye_deux_fois_ne_cree_qu_une_facture(session):
    extracteur = FauxExtracteur("facture-F26-1193.pdf")
    premiere = recevoir(session, "facture-F26-1193.pdf", extracteur)

    seconde = recevoir(session, "facture-F26-1193.pdf", extracteur)

    assert seconde.deja_vue
    assert seconde.facture.id == premiere.facture.id
    assert extracteur.appels == 1
    assert session.scalar(select(func.count()).select_from(FactureEnBase)) == 1
    assert types_evenements(seconde.facture)[-1] == "DOUBLON_FICHIER"


def test_la_meme_facture_dans_un_autre_fichier_est_un_doublon(session):
    recevoir(session, "facture-F26-1193.pdf")

    # Un fichier différent, mais le LLM y lit le même fournisseur et le même numéro.
    copie = traiter(session, pdf("facture-2026-11-087.pdf"), "copie.pdf", FauxExtracteur("facture-F26-1193.pdf"), AUJOURD_HUI).facture

    assert copie.etat == Etat.EN_ANOMALIE
    assert [anomalie["code"] for anomalie in copie.anomalies] == ["DOUBLON_FACTURE"]
    assert "facture-F26-1193.pdf" in copie.anomalies[0]["message"]


def test_une_facture_rejetee_ne_compte_plus_comme_doublon(session):
    premiere = recevoir(session, "facture-F26-1193.pdf").facture
    rejeter(session, premiere.id, "Awa", "Envoyée par erreur")

    copie = traiter(session, pdf("facture-2026-11-087.pdf"), "copie.pdf", FauxExtracteur("facture-F26-1193.pdf"), AUJOURD_HUI).facture

    assert copie.etat == Etat.A_VALIDER


def test_une_panne_du_llm_met_la_facture_en_echec(session):
    extracteur = FauxExtracteur("facture-F26-1193.pdf", erreur=ErreurExtraction("Le LLM a répondu 503"))

    facture = recevoir(session, "facture-F26-1193.pdf", extracteur).facture

    assert facture.etat == Etat.ECHEC
    assert facture.donnees is None
    assert facture.evenements[-1].detail == {"raison": "Le LLM a répondu 503"}


def test_une_facture_en_echec_est_retentee_au_renvoi_du_fichier(session):
    en_panne = FauxExtracteur("facture-F26-1193.pdf", erreur=ErreurExtraction("Le LLM a répondu 503"))
    premiere = recevoir(session, "facture-F26-1193.pdf", en_panne).facture

    seconde = recevoir(session, "facture-F26-1193.pdf")

    assert seconde.facture.id == premiere.id
    assert not seconde.deja_vue
    assert seconde.facture.etat == Etat.A_VALIDER
    assert types_evenements(seconde.facture) == ["RECEPTION", "EXTRACTION_ECHOUEE", "NOUVEL_ESSAI", "EXTRACTION", "CONTROLE"]


def test_un_scan_sans_texte_est_lu_sur_image_et_pas_sur_texte(session):
    ecrivain = PdfWriter()
    ecrivain.add_blank_page(width=595, height=842)
    tampon = io.BytesIO()
    ecrivain.write(tampon)
    extracteur = FauxExtracteur("facture-F26-1193.pdf")
    images_recues = []

    def extracteur_images(images):
        images_recues.append(images)
        return FauxExtracteur("facture-F26-1193.pdf")("")

    facture = traiter(session, tampon.getvalue(), "scan.pdf", extracteur, AUJOURD_HUI, extracteur_images=extracteur_images).facture

    assert extracteur.appels == 0  # pas de texte : la lecture du texte n'est pas appelée
    assert len(images_recues) == 1 and images_recues[0][0].startswith(b"\x89PNG")  # une page, en image
    assert next(e for e in facture.evenements if e.type == "EXTRACTION").detail["source"] == "ia-image"


def test_une_personne_valide_une_facture_a_valider(session):
    facture = recevoir(session, "facture-F26-1193.pdf").facture

    valider(session, facture.id, "Awa")

    assert facture.etat == Etat.VALIDEE
    assert (facture.evenements[-1].type, facture.evenements[-1].auteur) == ("VALIDATION", "Awa")


def test_une_facture_en_anomalie_ne_peut_pas_etre_validee(session):
    facture = recevoir(session, "facture-erreur-total.pdf").facture

    with pytest.raises(TransitionInterdite, match="en_anomalie"):
        valider(session, facture.id, "Awa")

    assert facture.etat == Etat.EN_ANOMALIE


def test_une_facture_validee_ne_peut_pas_etre_validee_deux_fois(session):
    facture = recevoir(session, "facture-F26-1193.pdf").facture
    valider(session, facture.id, "Awa")

    with pytest.raises(TransitionInterdite):
        valider(session, facture.id, "Awa")


def test_le_rejet_garde_le_motif(session):
    facture = recevoir(session, "facture-erreur-total.pdf").facture

    rejeter(session, facture.id, "Awa", "Total faux, à redemander au fournisseur")

    assert facture.etat == Etat.REJETEE
    assert facture.evenements[-1].detail == {"motif": "Total faux, à redemander au fournisseur"}


def test_une_facture_inconnue_est_signalee(session):
    import uuid

    with pytest.raises(FactureIntrouvable):
        valider(session, uuid.uuid4(), "Awa")


def test_chaque_evenement_porte_son_heure_reelle(session):
    """Une lecture lente doit se voir au journal : l'extraction est datée après la réception."""
    lent = FauxExtracteur("facture-F26-1193.pdf")
    original = lent.__call__

    def lire_lentement(texte):
        time.sleep(0.3)
        return original(texte)

    facture = traiter(session, pdf("facture-F26-1193.pdf"), "f.pdf", lire_lentement, AUJOURD_HUI).facture

    reception, extraction = facture.evenements[0], facture.evenements[1]
    session.refresh(reception)
    session.refresh(extraction)
    assert (extraction.cree_le - reception.cree_le).total_seconds() >= 0.3
