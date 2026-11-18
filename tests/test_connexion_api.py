"""La connexion par l'API : demande, mail, lien ou code, session, déconnexion."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from moteur import comptes
from moteur.api import creer_application


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("VERIFAC_SECRET_SESSION", "s" * 40)
    monkeypatch.setenv("VERIFAC_ADRESSE", "https://verifac.exemple")


@pytest.fixture
def mails():
    return []


@pytest.fixture
def client(connexion, tmp_path, mails):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    with fabrique() as session:
        comptes.creer(session, "Claire Fabre", "claire@exemple.fr", "membre", ["comptable"], "installation")
        session.commit()
    return TestClient(creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path, odoo=None, envoyeur_mail=lambda message: mails.append(message) or {"id": "m1"}))


def lien_et_code(message) -> tuple[str, str]:
    jeton = re.search(r"\?connexion=([\w-]+)", message.texte).group(1)
    code = re.search(r"code : (\d{3}) (\d{3})", message.texte)
    return jeton, code.group(1) + code.group(2)


def test_la_demande_envoie_un_lien_et_un_code(client, mails):
    reponse = client.post("/connexion/demande", json={"email": "Claire@exemple.fr"})

    assert reponse.status_code == 200 and len(mails) == 1
    assert mails[0].destinataire == "claire@exemple.fr"
    assert "https://verifac.exemple/?connexion=" in mails[0].texte and "15 minutes" in mails[0].texte


def test_une_adresse_inconnue_recoit_la_meme_reponse_et_aucun_mail(client, mails):
    connue = client.post("/connexion/demande", json={"email": "claire@exemple.fr"}).json()
    inconnue = client.post("/connexion/demande", json={"email": "personne@exemple.fr"}).json()

    assert connue == inconnue and len(mails) == 1


def test_le_lien_connecte_et_pose_la_session(client, mails):
    client.post("/connexion/demande", json={"email": "claire@exemple.fr"})
    jeton, _ = lien_et_code(mails[0])

    assert client.get("/moi").json() == {"compte": None, "comptes": True, "demo": False}
    reponse = client.post("/connexion/lien", json={"jeton": jeton})

    assert reponse.status_code == 200 and comptes.COOKIE in reponse.cookies
    moi = client.get("/moi").json()["compte"]
    assert moi["nom"] == "Claire Fabre" and moi["role"] == "membre" and "traiter" in moi["droits"]
    assert client.post("/connexion/lien", json={"jeton": jeton}).status_code == 401  # déjà utilisé


def test_le_code_connecte(client, mails):
    client.post("/connexion/demande", json={"email": "claire@exemple.fr"})
    _, code = lien_et_code(mails[0])

    assert client.post("/connexion/code", json={"email": "claire@exemple.fr", "code": "999999" if code != "999999" else "111111"}).status_code == 401
    assert client.post("/connexion/code", json={"email": "claire@exemple.fr", "code": code}).status_code == 200
    assert client.get("/moi").json()["compte"]["email"] == "claire@exemple.fr"


def test_un_code_faux_compte_un_essai_meme_refuse(client, mails):
    client.post("/connexion/demande", json={"email": "claire@exemple.fr"})
    _, code = lien_et_code(mails[0])
    faux = "999999" if code != "999999" else "111111"

    for _ in range(comptes.ESSAIS_CODE_MAX):
        client.post("/connexion/code", json={"email": "claire@exemple.fr", "code": faux})

    assert client.post("/connexion/code", json={"email": "claire@exemple.fr", "code": code}).status_code == 401  # bloqué


def test_la_deconnexion_retire_la_session(client, mails):
    client.post("/connexion/demande", json={"email": "claire@exemple.fr"})
    client.post("/connexion/lien", json={"jeton": lien_et_code(mails[0])[0]})

    client.post("/deconnexion")

    assert client.get("/moi").json()["compte"] is None


def test_trop_de_demandes_depuis_une_adresse(client):
    for _ in range(20):
        client.post("/connexion/demande", json={"email": "personne@exemple.fr"})

    assert client.post("/connexion/demande", json={"email": "personne@exemple.fr"}).status_code == 429


def test_le_mail_ne_contient_rien_d_injecte(client, mails, connexion):
    with Session(bind=connexion, join_transaction_mode="create_savepoint") as session:
        comptes.creer(session, "<b>Paul</b>", "paul@exemple.fr", "lecture", [], "installation")
        session.commit()
    client.post("/connexion/demande", json={"email": "paul@exemple.fr"})

    assert "<b>Paul</b>" not in mails[0].html and "&lt;b&gt;Paul&lt;/b&gt;" in mails[0].html
