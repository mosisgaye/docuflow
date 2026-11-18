"""Le mode démo : entrée en un clic sur un compte partagé, actions risquées fermées, assistant plafonné.

Hors du mode démo (la production), l'entrée en un clic n'existe pas.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moteur import comptes, demo
from moteur.api import creer_application


def faux_llm(messages, outils):
    yield {"texte": "Bonjour."}


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("VERIFAC_SECRET_SESSION", "s" * 40)


@pytest.fixture
def fabrique(connexion):
    return lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")


@pytest.fixture
def client(fabrique, tmp_path):
    # Une vraie installation a déjà son administrateur : la démo ne doit pas dépendre d'une base vide.
    with fabrique() as session:
        comptes.creer(session, "Moussa Gaye", "moussa@exemple.fr", "administrateur", ["gerant"], "installation")
        session.commit()
    application = creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path, odoo=None, llm_agent=faux_llm)
    return TestClient(application)


@pytest.fixture
def en_demo(monkeypatch):
    monkeypatch.setenv("VERIFAC_MODE_DEMO", "1")


def test_hors_demo_l_entree_en_un_clic_n_existe_pas(client):
    assert client.get("/moi").json()["demo"] is False
    reponse = client.post("/connexion/demo")
    assert reponse.status_code == 404
    assert comptes.COOKIE not in reponse.cookies
    # Et la session n'est pas ouverte : l'application reste fermée.
    assert client.get("/factures").status_code == 401


def test_en_demo_un_clic_ouvre_la_session_sur_le_compte_partage(client, fabrique, en_demo):
    assert client.get("/moi").json() == {"compte": None, "comptes": True, "demo": True}

    entree = client.post("/connexion/demo")

    assert entree.status_code == 200
    vu = entree.json()["compte"]
    assert vu["email"] == "demo@verifac.company" and vu["role"] == "administrateur"
    assert client.get("/factures").status_code == 200
    # Un second visiteur arrive sur le même compte : il n'est pas recréé.
    assert TestClient(client.app).post("/connexion/demo").json()["compte"]["id"] == vu["id"]
    with fabrique() as session:
        assert session.scalar(select(func.count()).select_from(comptes.Compte).where(comptes.Compte.email == "demo@verifac.company")) == 1


@pytest.mark.parametrize(
    ("methode", "chemin", "corps"),
    [
        ("POST", "/comptes", {"nom": "Pirate", "email": "pirate@exemple.fr", "role": "administrateur"}),
        ("POST", "/cles-api", {"nom": "x", "portee": "lecture"}),
        ("POST", "/abonnements", {"url": "https://exemple.fr/crochet", "evenements": ["facture.validee"]}),
        ("POST", "/connecteurs/odoo/branchement", {}),
    ],
)
def test_en_demo_les_actions_risquees_sont_fermees(client, en_demo, methode, chemin, corps):
    client.post("/connexion/demo")

    reponse = client.request(methode, chemin, json=corps)

    assert reponse.status_code == 403
    assert "Dans la démo" in reponse.json()["detail"]


def test_en_demo_le_reste_s_essaie(client, en_demo):
    client.post("/connexion/demo")
    # Le cas légitime passe : l'équipe d'approbation se règle, le circuit se lit.
    assert client.post("/reglages/equipe", json={"nom": "Paul Mercier", "email": "paul@exemple.fr", "niveau": "gerant", "auteur": "Visiteur"}).status_code == 201
    assert client.get("/circuit/brouillon").status_code == 200


def test_en_demo_l_assistant_est_plafonne(client, en_demo, monkeypatch):
    monkeypatch.setenv("AGENT_PAR_JOUR", "2")
    client.post("/connexion/demo")
    question = {"messages": [{"role": "user", "content": "Bonjour"}]}

    assert [client.post("/agent", json=question).status_code for _ in range(3)] == [200, 200, 429]


def test_le_compteur_repart_chaque_jour(monkeypatch):
    compteur = demo.CompteurJour()
    assert compteur.prendre(1) and not compteur.prendre(1)
    compteur._jour = compteur._jour.replace(year=2000)
    assert compteur.prendre(1)
    assert all(demo.CompteurJour().prendre(0) for _ in range(5))  # 0 : sans limite


def test_une_demo_neuve_sans_aucun_compte_n_est_pas_ouverte(fabrique, tmp_path, en_demo):
    client = TestClient(creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path, odoo=None, llm_agent=faux_llm))
    # Sans compte, une installation normale est ouverte ; une démo, non : l'écran de connexion s'affiche.
    assert client.get("/moi").json() == {"compte": None, "comptes": True, "demo": True}
    assert client.get("/factures").status_code == 401
    assert client.post("/comptes", json={"nom": "X", "email": "x@exemple.fr", "role": "administrateur"}).status_code == 401
    # Le cas légitime : l'entrée en un clic crée le compte partagé et ouvre la session.
    assert client.post("/connexion/demo").status_code == 200
    assert client.get("/factures").status_code == 200
