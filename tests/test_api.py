import json
import pathlib
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from moteur.api import TAILLE_MAX_OCTETS, creer_application
from moteur.extraction_llm import ErreurExtraction, ResultatExtraction
from moteur.modeles import Facture

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
JUSTE = "facture-F26-1193.pdf"
FAUSSE = "facture-erreur-total.pdf"


class FauxLLM:
    """Reconnaît la facture à son numéro dans le texte et renvoie les données prévues."""

    def __init__(self):
        self.appels = 0
        self.en_panne = False

    def __call__(self, texte: str) -> ResultatExtraction:
        self.appels += 1
        if self.en_panne:
            raise ErreurExtraction("Le LLM a répondu 503")
        for attendu in ATTENDU.values():
            if attendu["facture"]["numero_facture"] in texte:
                return ResultatExtraction(Facture.model_validate(attendu["facture"]), 0.1, "test", "faux")
        raise ErreurExtraction("Facture inconnue du faux LLM")


@pytest.fixture
def llm():
    return FauxLLM()


@pytest.fixture
def client(connexion, llm, tmp_path):
    application = creer_application(
        fabrique_session=lambda: Session(bind=connexion, join_transaction_mode="create_savepoint"),
        extracteur=llm,
        dossier_fichiers=tmp_path,
        traiter_tout_de_suite=True,
    )
    return TestClient(application)


def deposer(client: TestClient, nom: str, contenu: bytes | None = None):
    return client.post("/factures", files={"fichier": (nom, contenu or (FACTURES / nom).read_bytes(), "application/pdf")})


def test_la_sante_repond(client):
    assert client.get("/sante").json() == {"etat": "ok", "file": {"en_attente": 0, "abandonnees": 0, "plus_ancienne_attente_s": None}}


def test_deposer_une_facture_juste(client):
    reponse = deposer(client, JUSTE)

    corps = reponse.json()
    assert reponse.status_code == 201
    assert corps["etat"] == "a_valider"
    assert corps["deja_vue"] is False
    assert corps["numero_facture"] == "F26-1193"
    assert corps["fournisseur_nom"] == "Garage Central Bertin"
    assert corps["total_ttc"] == "478.08"
    assert corps["nb_anomalies"] == 0
    assert [evenement["type"] for evenement in corps["evenements"]] == ["RECEPTION", "EXTRACTION", "CONTROLE"]


def test_deposer_une_facture_fausse_renvoie_ses_anomalies(client):
    corps = deposer(client, FAUSSE).json()

    assert corps["etat"] == "en_anomalie"
    assert corps["anomalies"][0]["code"] == "TOTAL_TTC_INCOHERENT"
    assert corps["anomalies"][0]["message"] == "HT + TVA font 1500,00 €, le total TTC indique 1600,00 €."


def test_redeposer_le_meme_fichier_renvoie_200_sans_rappeler_le_llm(client, llm):
    premiere = deposer(client, JUSTE).json()

    seconde = deposer(client, JUSTE)

    assert seconde.status_code == 200
    assert seconde.json()["deja_vue"] is True
    assert seconde.json()["id"] == premiere["id"]
    assert llm.appels == 1
    assert len(client.get("/factures").json()) == 1


def test_un_fichier_qui_n_est_pas_un_pdf_est_refuse(client, llm):
    reponse = deposer(client, "notes.txt", b"Bonjour, ceci est un texte.")

    assert reponse.status_code == 415
    assert reponse.json()["detail"] == "Seuls les fichiers PDF sont acceptés."
    assert llm.appels == 0


def test_un_pdf_corrompu_est_refuse(client, llm):
    reponse = deposer(client, "casse.pdf", b"%PDF-1.7\nceci n'est pas un vrai PDF")

    assert reponse.status_code == 400
    assert llm.appels == 0
    assert client.get("/factures").json() == []


def test_un_fichier_trop_gros_est_refuse(client):
    reponse = deposer(client, "gros.pdf", b"%PDF-" + b"0" * TAILLE_MAX_OCTETS)

    assert reponse.status_code == 413


def test_une_panne_du_llm_donne_une_facture_en_echec(client, llm):
    llm.en_panne = True

    reponse = deposer(client, JUSTE)

    assert reponse.status_code == 201
    assert reponse.json()["etat"] == "echec"
    assert reponse.json()["evenements"][-1]["detail"] == {"raison": "Le LLM a répondu 503"}


def test_lister_et_filtrer_par_etat(client):
    deposer(client, JUSTE)
    deposer(client, FAUSSE)

    toutes = client.get("/factures").json()
    en_anomalie = client.get("/factures", params={"etat": "en_anomalie"}).json()

    assert {facture["nom_fichier"] for facture in toutes} == {JUSTE, FAUSSE}
    assert [facture["nom_fichier"] for facture in en_anomalie] == [FAUSSE]
    assert "donnees" not in toutes[0]


def test_un_etat_inconnu_est_refuse(client):
    assert client.get("/factures", params={"etat": "nimporte"}).status_code == 422


def test_le_detail_contient_les_donnees_et_le_journal(client):
    identifiant = deposer(client, JUSTE).json()["id"]

    corps = client.get(f"/factures/{identifiant}").json()

    assert corps["donnees"]["lignes"][2]["designation"] == "Main-d'œuvre (heures)"
    assert len(corps["evenements"]) == 3


def test_le_fichier_d_origine_est_rendu_tel_quel(client):
    identifiant = deposer(client, JUSTE).json()["id"]

    reponse = client.get(f"/factures/{identifiant}/fichier")

    assert reponse.status_code == 200
    assert reponse.headers["content-type"] == "application/pdf"
    assert reponse.content == (FACTURES / JUSTE).read_bytes()


def test_valider_une_facture(client):
    identifiant = deposer(client, JUSTE).json()["id"]

    reponse = client.post(f"/factures/{identifiant}/validation", json={"auteur": "Awa"})

    dernier = reponse.json()["evenements"][-1]
    assert reponse.status_code == 200
    assert reponse.json()["etat"] == "validee"
    assert (dernier["type"], dernier["auteur"]) == ("VALIDATION", "Awa")


def test_valider_une_facture_en_anomalie_est_refuse(client):
    identifiant = deposer(client, FAUSSE).json()["id"]

    reponse = client.post(f"/factures/{identifiant}/validation", json={"auteur": "Awa"})

    assert reponse.status_code == 409
    assert reponse.json()["detail"] == "Passage interdit de « en_anomalie » à « validee »."
    assert client.get(f"/factures/{identifiant}").json()["etat"] == "en_anomalie"


def test_valider_sans_auteur_est_refuse(client):
    identifiant = deposer(client, JUSTE).json()["id"]

    assert client.post(f"/factures/{identifiant}/validation", json={"auteur": ""}).status_code == 422


def test_rejeter_une_facture_avec_un_motif(client):
    identifiant = deposer(client, FAUSSE).json()["id"]

    reponse = client.post(f"/factures/{identifiant}/rejet", json={"auteur": "Awa", "motif": "Total faux"})

    assert reponse.json()["etat"] == "rejetee"
    assert reponse.json()["evenements"][-1]["detail"] == {"motif": "Total faux"}


def test_rejeter_sans_motif_est_refuse(client):
    identifiant = deposer(client, FAUSSE).json()["id"]

    assert client.post(f"/factures/{identifiant}/rejet", json={"auteur": "Awa"}).status_code == 422


@pytest.mark.parametrize(
    ("methode", "chemin", "corps"),
    [
        ("get", "/factures/{id}", None),
        ("get", "/factures/{id}/fichier", None),
        ("post", "/factures/{id}/validation", {"auteur": "Awa"}),
        ("post", "/factures/{id}/rejet", {"auteur": "Awa", "motif": "x"}),
    ],
)
def test_une_facture_inconnue_donne_404(client, methode, chemin, corps):
    reponse = client.request(methode, chemin.format(id=uuid.uuid4()), json=corps)

    assert reponse.status_code == 404


def test_les_statistiques_d_une_base_vide(client):
    corps = client.get("/statistiques").json()

    assert corps["total"] == 0
    assert corps["duree_moyenne_s"] is None
    assert corps["recentes"] == [] and corps["activite"] == []


def test_les_statistiques_comptent_les_factures_reelles(client):
    deposer(client, JUSTE)
    identifiant = deposer(client, FAUSSE).json()["id"]
    client.post(f"/factures/{identifiant}/rejet", json={"auteur": "Awa", "motif": "Total faux"})

    corps = client.get("/statistiques").json()

    assert corps["total"] == 2
    assert corps["par_etat"]["a_valider"] == 1 and corps["par_etat"]["rejetee"] == 1
    assert corps["conformes"] == 1
    assert corps["anomalies_detectees"] == 1
    assert corps["duree_moyenne_s"] == 0.1
    assert (corps["lues_par_ia"], corps["lues_sans_ia"]) == (2, 0)
    assert corps["durees_recentes_s"] == [0.1, 0.1]
    assert len(corps["recentes"]) == 2
    assert corps["activite"][0]["type"] == "REJET"
    assert corps["activite"][0]["numero_facture"] == "FA-2026-0431"


def test_l_enregistrement_se_fait_avant_l_envoi_de_la_reponse(connexion, llm, tmp_path):
    """Sinon l'interface peut relire l'ancien état juste après une décision."""
    application = creer_application(
        fabrique_session=lambda: Session(bind=connexion, join_transaction_mode="create_savepoint"),
        extracteur=llm,
        dossier_fichiers=tmp_path,
    )
    portees = {
        dependance.scope
        for route in application.routes
        if hasattr(route, "dependant")
        for dependance in route.dependant.dependencies
        if dependance.call.__name__ == "session_de_requete"
    }

    assert portees == {"function"}
