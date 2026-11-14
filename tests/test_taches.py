"""La file de tâches et le travailleur : dépôt immédiat, lecture à part, reprise après plantage."""

import json
import pathlib
import threading
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from moteur.api import creer_application
from moteur.base import Etat, EtatTache, FactureEnBase, Tache
from moteur.extraction_llm import ErreurExtraction, ResultatExtraction
from moteur.modeles import Facture
from moteur.travailleur import PLAN_DE_REPRISE_S, TENTATIVES_MAX, prendre_une_tache, traiter_une_tache
from moteur.workflow import recevoir

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
JUSTE = "facture-F26-1193.pdf"
AUJOURD_HUI = date(2026, 11, 14)


class FauxLLM:
    """Reconnaît la facture à son numéro. Peut échouer un certain nombre de fois avant de réussir."""

    def __init__(self, pannes: list[ErreurExtraction] | None = None, lenteur_s: float = 0.0):
        self.pannes = list(pannes or [])
        self.lenteur_s = lenteur_s
        self.appels = 0
        self.verrou = threading.Lock()

    def __call__(self, texte: str) -> ResultatExtraction:
        with self.verrou:
            self.appels += 1
            panne = self.pannes.pop(0) if self.pannes else None
        time.sleep(self.lenteur_s)
        if panne:
            raise panne
        for attendu in ATTENDU.values():
            if attendu["facture"]["numero_facture"] in texte:
                return ResultatExtraction(Facture.model_validate(attendu["facture"]), 0.1, "test", "faux")
        raise ErreurExtraction("Facture inconnue du faux LLM")


def panne_passagere(attendre_avant: float | None = None) -> ErreurExtraction:
    return ErreurExtraction("Le LLM a répondu 503 (après 3 appels)", passagere=True, attendre_avant=attendre_avant)


@pytest.fixture
def dossier(tmp_path):
    """Le dossier des PDF reçus, comme celui où l'API les écrit."""
    for nom in ATTENDU:
        contenu = (FACTURES / nom).read_bytes()
        (tmp_path / f"{__import__('hashlib').sha256(contenu).hexdigest()}.pdf").write_bytes(contenu)
    return tmp_path


def deposer(session, nom: str = JUSTE):
    return recevoir(session, (FACTURES / nom).read_bytes(), nom)


def taches_de(session, facture) -> list[Tache]:
    return list(session.scalars(select(Tache).where(Tache.facture_id == facture.id).order_by(Tache.cree_le)))


# ───────── Dépôt ─────────


def test_le_depot_cree_la_facture_et_sa_tache_ensemble(session):
    resultat = deposer(session)

    assert resultat.facture.etat == Etat.RECUE
    assert [(tache.etat, tache.tentatives) for tache in taches_de(session, resultat.facture)] == [("en_attente", 0)]
    assert [evenement.type for evenement in resultat.facture.evenements] == ["RECEPTION"]


def test_redeposer_un_fichier_en_attente_ne_cree_pas_de_seconde_tache(session):
    premier = deposer(session)

    second = deposer(session)

    assert second.deja_vue
    assert len(taches_de(session, premier.facture)) == 1


def test_redeposer_une_facture_en_echec_la_remet_en_file(session, dossier):
    facture = deposer(session).facture
    traiter_une_tache(session, dossier, FauxLLM([ErreurExtraction("Le LLM a répondu 401")]), AUJOURD_HUI)
    assert facture.etat == Etat.ECHEC

    resultat = deposer(session)

    assert not resultat.deja_vue
    assert [tache.etat for tache in taches_de(session, facture)] == ["abandonnee", "en_attente"]


# ───────── Travailleur ─────────


def test_le_travailleur_lit_et_controle_la_facture(session, dossier):
    facture = deposer(session).facture

    compte_rendu = traiter_une_tache(session, dossier, FauxLLM(), AUJOURD_HUI)

    assert compte_rendu.resultat == "lue"
    assert facture.etat == Etat.A_VALIDER
    assert [(tache.etat, tache.tentatives) for tache in taches_de(session, facture)] == [("terminee", 1)]
    assert [evenement.type for evenement in facture.evenements] == ["RECEPTION", "EXTRACTION", "CONTROLE"]


def test_file_vide(session, dossier):
    assert traiter_une_tache(session, dossier, FauxLLM(), AUJOURD_HUI) is None


def test_une_panne_passagere_reprogramme_la_tache(session, dossier):
    facture = deposer(session).facture

    compte_rendu = traiter_une_tache(session, dossier, FauxLLM([panne_passagere()]), AUJOURD_HUI)

    tache = taches_de(session, facture)[0]
    assert compte_rendu.resultat == "reprogrammee"
    assert facture.etat == Etat.RECUE
    assert (tache.etat, tache.tentatives) == ("en_attente", 1)
    assert session.scalar(select(func.extract("epoch", Tache.prochain_essai_le - func.now())).where(Tache.id == tache.id)) == PLAN_DE_REPRISE_S[0]
    assert facture.evenements[-1].type == "NOUVEL_ESSAI_PROGRAMME"
    assert facture.evenements[-1].detail["dans_s"] == PLAN_DE_REPRISE_S[0]
    # Pas encore l'heure : la tâche n'est pas reprise tout de suite.
    assert traiter_une_tache(session, dossier, FauxLLM(), AUJOURD_HUI) is None


def test_le_delai_demande_par_le_service_l_emporte_s_il_est_plus_long(session, dossier):
    facture = deposer(session).facture

    traiter_une_tache(session, dossier, FauxLLM([panne_passagere(attendre_avant=3600)]), AUJOURD_HUI)

    assert facture.evenements[-1].detail["dans_s"] == 3600


def test_apres_trop_de_pannes_la_tache_est_abandonnee(session, dossier):
    facture = deposer(session).facture
    tache = taches_de(session, facture)[0]
    tache.tentatives = TENTATIVES_MAX - 1

    compte_rendu = traiter_une_tache(session, dossier, FauxLLM([panne_passagere()]), AUJOURD_HUI)

    assert compte_rendu.resultat == "abandonnee"
    assert (tache.etat, tache.tentatives) == ("abandonnee", TENTATIVES_MAX)
    assert facture.etat == Etat.ECHEC
    assert f"abandon après {TENTATIVES_MAX} tentatives" in facture.evenements[-1].detail["raison"]


def test_une_erreur_definitive_abandonne_tout_de_suite(session, dossier):
    facture = deposer(session).facture

    compte_rendu = traiter_une_tache(session, dossier, FauxLLM([ErreurExtraction("Le LLM a répondu 401")]), AUJOURD_HUI)

    assert compte_rendu.resultat == "abandonnee"
    assert facture.etat == Etat.ECHEC
    assert taches_de(session, facture)[0].tentatives == 1


def test_un_fichier_introuvable_abandonne_la_tache(session, tmp_path):
    facture = deposer(session).facture

    compte_rendu = traiter_une_tache(session, tmp_path, FauxLLM(), AUJOURD_HUI)

    assert compte_rendu.resultat == "abandonnee"
    assert facture.etat == Etat.ECHEC
    assert "introuvable" in facture.evenements[-1].detail["raison"]


# ───────── Plantage et parallélisme (vraies transactions) ─────────


@pytest.fixture
def base_propre(moteur_base):
    yield moteur_base
    with moteur_base.begin() as connexion:
        connexion.execute(text("truncate taches, evenements, factures"))


def test_un_travailleur_qui_plante_rend_sa_tache_a_un_autre(base_propre, dossier):
    with Session(base_propre) as session:
        deposer(session)
        session.commit()

    # Le travailleur A prend la tâche…
    session_a = Session(base_propre)
    tache_a = prendre_une_tache(session_a)
    assert tache_a is not None
    # … pendant ce temps, B ne la voit pas : elle est tenue.
    with Session(base_propre) as session_b:
        assert prendre_une_tache(session_b) is None
    # A plante : sa connexion se coupe sans rien valider.
    session_a.connection().invalidate()
    session_a.close()

    # B reprend la tâche et la termine.
    llm = FauxLLM()
    with Session(base_propre) as session_b:
        compte_rendu = traiter_une_tache(session_b, dossier, llm, AUJOURD_HUI)
        session_b.commit()

    assert compte_rendu.resultat == "lue"
    assert llm.appels == 1
    with Session(base_propre) as session:
        tache = session.scalars(select(Tache)).one()
        assert (tache.etat, tache.tentatives) == ("terminee", 1)  # la tentative de A n'a pas compté
        assert session.scalars(select(FactureEnBase)).one().etat == Etat.A_VALIDER


def test_deux_travailleurs_ne_prennent_jamais_la_meme_tache(base_propre, dossier):
    with Session(base_propre) as session:
        deposer(session, "facture-F26-1193.pdf")
        deposer(session, "facture-2026-11-087.pdf")
        session.commit()
    llm = FauxLLM(lenteur_s=0.4)
    comptes_rendus, depart = [], threading.Barrier(2)

    def travailler():
        with Session(base_propre) as session:
            depart.wait()
            comptes_rendus.append(traiter_une_tache(session, dossier, llm, AUJOURD_HUI))
            session.commit()

    fils = [threading.Thread(target=travailler) for _ in range(2)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=30)

    assert llm.appels == 2
    assert len({compte_rendu.facture_id for compte_rendu in comptes_rendus}) == 2
    with Session(base_propre) as session:
        assert {tache.etat for tache in session.scalars(select(Tache))} == {EtatTache.TERMINEE.value}


# ───────── Par l'API ─────────


def test_le_depot_par_l_api_repond_tout_de_suite_puis_le_travailleur_lit(connexion, dossier, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    llm = FauxLLM()
    client = TestClient(creer_application(fabrique_session=fabrique, extracteur=llm, dossier_fichiers=tmp_path / "recus"))

    reponse = client.post("/factures", files={"fichier": (JUSTE, (FACTURES / JUSTE).read_bytes(), "application/pdf")})
    sante = client.get("/sante").json()

    assert reponse.status_code == 202
    assert reponse.json()["etat"] == "recue"
    assert llm.appels == 0  # rien n'a été lu pendant la requête
    assert sante["file"]["en_attente"] == 1
    assert (tmp_path / "recus" / f"{__import__('hashlib').sha256((FACTURES / JUSTE).read_bytes()).hexdigest()}.pdf").exists()

    with fabrique() as session:
        traiter_une_tache(session, tmp_path / "recus", llm, AUJOURD_HUI)
        session.commit()

    assert client.get(f"/factures/{reponse.json()['id']}").json()["etat"] == "a_valider"
    assert client.get("/sante").json()["file"]["en_attente"] == 0


def test_de_nombreux_depots_sur_la_meme_connexion(session):
    """Au-delà de quelques exécutions, psycopg prépare la requête côté serveur.

    La condition de l'index partiel doit alors être écrite en toutes lettres dans la requête,
    sinon PostgreSQL ne retrouve plus l'index et le dépôt échoue (erreur vue au 9e dépôt réel).
    """
    original = (FACTURES / JUSTE).read_bytes()
    for numero in range(12):
        copie = original + f"\n% copie {numero}\n".encode()
        resultat = recevoir(session, copie, f"copie-{numero}.pdf")
        assert resultat.tache is not None

    assert session.scalar(select(func.count()).select_from(Tache)) == 12
