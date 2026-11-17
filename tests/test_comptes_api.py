"""Réglages › Équipe avec des comptes : l'administrateur crée, change, désactive et déconnecte les comptes."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from moteur import comptes, notifications
from moteur.api import creer_application


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("VERIFAC_SECRET_SESSION", "s" * 40)


@pytest.fixture
def monde(connexion, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    jetons = {}
    with fabrique() as session:
        for cle, nom, role, niveaux in (("admin", "Moussa Gaye", "administrateur", ["gerant"]), ("claire", "Claire Fabre", "membre", ["comptable"]), ("support", "Support Verifac", "operateur", [])):
            jetons[cle] = comptes.jeton_session(comptes.creer(session, nom, f"{cle}@exemple.fr", role, niveaux, "installation"))
        session.commit()
    application = creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path, odoo=None)

    def client(cle):
        nouveau = TestClient(application)
        nouveau.cookies.set(comptes.COOKIE, jetons[cle])
        return nouveau

    return client, fabrique


def ids(client) -> dict:
    return {c["email"]: c for c in client.get("/comptes").json()["comptes"]}


def test_l_administrateur_cree_un_compte_signe_de_son_nom(monde):
    client, _ = monde
    admin = client("admin")

    cree = admin.post("/comptes", json={"nom": "Paul Mercier", "email": "Paul@Exemple.fr", "role": "approbateur", "niveaux": ["directeur_financier"]})

    assert cree.status_code == 201 and cree.json()["email"] == "paul@exemple.fr"
    assert set(admin.get("/comptes").json()["roles"]) == {"administrateur", "membre", "approbateur", "lecture"}


@pytest.mark.parametrize(
    ("corps", "message"),
    [
        ({"nom": "X", "email": "x@exemple.fr", "role": "operateur"}, "ne se donne pas"),
        ({"nom": "X", "email": "claire@exemple.fr", "role": "membre"}, "déjà un compte"),
        ({"nom": "X", "email": "pas-une-adresse", "role": "membre"}, "n'est pas une adresse"),
    ],
)
def test_un_compte_refuse_dit_pourquoi(monde, corps, message):
    client, _ = monde

    reponse = client("admin").post("/comptes", json=corps)

    assert reponse.status_code == 422 and message in reponse.json()["detail"]


def test_seul_l_administrateur_gere_les_comptes(monde):
    client, _ = monde
    claire = client("claire")
    cible = ids(claire)["admin@exemple.fr"]["id"]

    assert claire.get("/comptes").status_code == 200  # voir l'équipe, oui
    assert claire.post("/comptes", json={"nom": "X", "email": "x@exemple.fr", "role": "membre"}).status_code == 403
    assert claire.put(f"/comptes/{cible}", json={"actif": False}).status_code == 403
    assert claire.post(f"/comptes/{cible}/deconnexion").status_code == 403
    assert client("support").post("/comptes", json={"nom": "X", "email": "x@exemple.fr", "role": "membre"}).status_code == 403


def test_changer_un_role_deconnecte_la_personne(monde):
    client, _ = monde
    admin, claire = client("admin"), client("claire")
    cible = ids(admin)["claire@exemple.fr"]["id"]

    reponse = admin.put(f"/comptes/{cible}", json={"role": "lecture", "niveaux": []})

    assert reponse.status_code == 200 and reponse.json()["role"] == "lecture"
    assert claire.get("/factures").status_code == 401  # elle doit se reconnecter avec son nouveau rôle


def test_le_dernier_administrateur_ne_peut_pas_se_retirer(monde):
    client, _ = monde
    admin = client("admin")
    moi = ids(admin)["admin@exemple.fr"]["id"]

    reponse = admin.put(f"/comptes/{moi}", json={"actif": False})

    assert reponse.status_code == 422 and "au moins un administrateur" in reponse.json()["detail"]


def test_l_operateur_peut_etre_desactive_mais_pas_change(monde):
    client, _ = monde
    admin = client("admin")
    operateur = ids(admin)["support@exemple.fr"]["id"]

    assert admin.put(f"/comptes/{operateur}", json={"role": "administrateur"}).status_code == 422
    assert admin.put(f"/comptes/{operateur}", json={"actif": False}).json()["actif"] is False
    assert client("support").get("/factures").status_code == 401


def test_deconnecter_partout(monde):
    client, _ = monde
    admin, claire = client("admin"), client("claire")

    admin.post(f"/comptes/{ids(admin)['claire@exemple.fr']['id']}/deconnexion")

    assert claire.get("/factures").status_code == 401


def test_les_mails_d_approbation_vont_aux_comptes_du_niveau(monde):
    client, fabrique = monde
    admin = client("admin")
    admin.post("/comptes", json={"nom": "Paul", "email": "paul@exemple.fr", "role": "approbateur", "niveaux": ["comptable"]})
    admin.put(f"/comptes/{ids(admin)['claire@exemple.fr']['id']}", json={"actif": False})

    with fabrique() as session:
        assert notifications.destinataires(session, "comptable") == ["paul@exemple.fr"]  # Claire est désactivée
        assert notifications.destinataires(session, "gerant") == ["admin@exemple.fr"]
