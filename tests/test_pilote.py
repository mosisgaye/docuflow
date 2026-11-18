"""Le programme pilote : une demande du site vitrine est gardée, annoncée par mail, et lue par l'administrateur."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moteur import comptes
from moteur.api import creer_application
from moteur.base import DemandePilote

DEMANDE = {
    "nom": "Claire Fabre",
    "entreprise": "Transports Lemaire SAS",
    "email": "Claire@Lemaire.fr",
    "volume": "50 à 200",
    "logiciel": "Odoo",
    "message": "La saisie des factures nous prend une journée par semaine.",
}


@pytest.fixture(autouse=True)
def reglages(monkeypatch):
    monkeypatch.setenv("VERIFAC_SECRET_SESSION", "s" * 40)
    monkeypatch.setenv("PILOTE_DESTINATAIRE", "moussa@exemple.fr")


@pytest.fixture
def monde(connexion, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    with fabrique() as session:
        jetons = {
            "admin": comptes.jeton_session(comptes.creer(session, "Moussa Gaye", "admin@exemple.fr", "administrateur", ["gerant"], "test")),
            "membre": comptes.jeton_session(comptes.creer(session, "Paul Mercier", "paul@exemple.fr", "membre", ["comptable"], "test")),
        }
        session.commit()
    mails = []
    application = creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path, odoo=None, envoyeur_mail=lambda message: mails.append(message) or {"id": "m1"})

    def client(qui=None):
        nouveau = TestClient(application)
        if qui:
            nouveau.cookies.set(comptes.COOKIE, jetons[qui])
        return nouveau

    return client, fabrique, mails


def compter(fabrique) -> int:
    with fabrique() as session:
        return session.scalar(select(func.count()).select_from(DemandePilote))


def test_une_demande_sans_compte_est_gardee_et_annoncee(monde):
    client, fabrique, mails = monde

    reponse = client().post("/pilote", json=DEMANDE)

    assert reponse.status_code == 201 and "Demande envoyée" in reponse.json()["message"]
    assert compter(fabrique) == 1
    assert len(mails) == 1 and mails[0].destinataire == "moussa@exemple.fr"
    assert "Transports Lemaire SAS" in mails[0].sujet and "claire@lemaire.fr" in mails[0].texte
    # Le texte du visiteur est échappé dans le mail HTML.
    piege = client().post("/pilote", json={**DEMANDE, "entreprise": "<script>x</script>"})
    assert piege.status_code == 201 and "<script>" not in mails[1].html


def test_un_robot_recoit_la_meme_reponse_mais_rien_n_est_garde(monde):
    client, fabrique, mails = monde

    reponse = client().post("/pilote", json={**DEMANDE, "site_web": "http://spam.example"})

    assert reponse.status_code == 201 and "Demande envoyée" in reponse.json()["message"]
    assert compter(fabrique) == 0 and mails == []


def test_un_choix_hors_liste_est_refuse(monde):
    client, fabrique, _ = monde
    reponse = client().post("/pilote", json={**DEMANDE, "volume": "un million"})
    assert reponse.status_code == 422 and "nombre de factures" in reponse.json()["detail"]
    assert compter(fabrique) == 0


def test_les_demandes_sont_limitees_par_connexion(monde):
    client, _, _ = monde
    visiteur = client()
    codes = [visiteur.post("/pilote", json=DEMANDE).status_code for _ in range(6)]
    assert codes == [201] * 5 + [429]


def test_sans_destinataire_la_demande_reste_en_base(monde, monkeypatch):
    client, fabrique, mails = monde
    monkeypatch.setenv("PILOTE_DESTINATAIRE", "")
    assert client().post("/pilote", json=DEMANDE).status_code == 201
    assert compter(fabrique) == 1 and mails == []


def test_seul_l_administrateur_lit_les_demandes(monde):
    client, _, _ = monde
    client().post("/pilote", json=DEMANDE)

    assert client().get("/pilote/demandes").status_code == 401
    assert client("membre").get("/pilote/demandes").status_code == 403
    lues = client("admin").get("/pilote/demandes")
    assert lues.status_code == 200
    assert [(d["entreprise"], d["email"]) for d in lues.json()["demandes"]] == [("Transports Lemaire SAS", "claire@lemaire.fr")]
