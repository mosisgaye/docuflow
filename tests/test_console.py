"""La Console de l'opérateur : des faits mesurés, réservés à l'opérateur ; le premier administrateur seulement s'il n'y en a plus."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from moteur import comptes, console
from moteur.api import creer_application
from moteur.base import Evenement, FactureEnBase


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("VERIFAC_SECRET_SESSION", "s" * 40)
    monkeypatch.delenv("VERIFAC_PRIX_ENTREE", raising=False)
    monkeypatch.delenv("VERIFAC_PRIX_SORTIE", raising=False)


def lecture(session, entree: int, sortie: int, modele: str = "gpt-test") -> None:
    facture = FactureEnBase(nom_fichier="f.pdf", empreinte=f"e{entree}-{sortie}", etat="a_valider", donnees={}, anomalies=[])
    session.add(facture)
    session.flush()
    session.add(Evenement(facture_id=facture.id, rang=1, type="EXTRACTION", etat="extraite", auteur="moteur", detail={"source": "ia", "modele": modele, "jetons": {"entree": entree, "sortie": sortie}}))
    session.flush()


def test_les_jetons_sont_comptes_sans_inventer_de_prix(session):
    lecture(session, 1_000_000, 200_000)
    lecture(session, 500_000, 100_000)

    ia = console.etat(session)["ia"]

    assert ia["lectures_30_jours"] == 2 and ia["jetons_entree"] == 1_500_000 and ia["jetons_sortie"] == 300_000
    assert ia["cout_30_jours_eur"] is None and ia["prix_renseigne"] is False
    assert ia["modeles"] == {"gpt-test": 2}


def test_le_cout_vient_du_prix_renseigne(session, monkeypatch):
    lecture(session, 1_000_000, 200_000)
    monkeypatch.setenv("VERIFAC_PRIX_ENTREE", "0,40")
    monkeypatch.setenv("VERIFAC_PRIX_SORTIE", "1.60")

    assert console.etat(session)["ia"]["cout_30_jours_eur"] == 0.72  # 1 × 0,40 + 0,2 × 1,60


def test_l_usage_et_la_version(session, monkeypatch):
    monkeypatch.setenv("VERIFAC_VERSION", "abc1234")
    lecture(session, 10, 10)

    vue = console.etat(session, datetime.now(UTC))

    assert vue["version"]["code"] == "abc1234" and vue["version"]["migration"]
    assert len(vue["usage"]["jours"]) == 30 and vue["usage"]["jours"][-1]["factures"] >= 1
    assert vue["sante"]["base"] == "ok"


@pytest.fixture
def monde(connexion, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    jetons = {}
    with fabrique() as session:
        for cle, role in (("support", "operateur"), ("admin", "administrateur")):
            jetons[cle] = comptes.jeton_session(comptes.creer(session, cle.title(), f"{cle}@exemple.fr", role, [], "installation"))
        session.commit()
    application = creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path, odoo=None)

    def client(cle):
        nouveau = TestClient(application)
        nouveau.cookies.set(comptes.COOKIE, jetons[cle])
        return nouveau

    return client, fabrique


def test_seul_l_operateur_ouvre_la_console(monde):
    client, _ = monde

    assert client("support").get("/console").status_code == 200
    assert client("admin").get("/console").status_code == 403


def test_premier_administrateur_seulement_s_il_n_y_en_a_plus(monde):
    client, fabrique = monde
    support = client("support")

    refus = support.post("/console/premier-administrateur", json={"nom": "Claire", "email": "claire@exemple.fr"})
    assert refus.status_code == 409 and "déjà un administrateur" in refus.json()["detail"]

    with fabrique() as session:
        admin = session.scalar(comptes.select(comptes.Compte).where(comptes.Compte.email == "admin@exemple.fr"))
        admin.actif = False  # l'installation a perdu son administrateur
        session.commit()

    cree = support.post("/console/premier-administrateur", json={"nom": "Claire", "email": "claire@exemple.fr"})
    assert cree.status_code == 201 and cree.json()["role"] == "administrateur"
    assert client("admin").post("/console/premier-administrateur", json={"nom": "X", "email": "x@exemple.fr"}).status_code == 401  # désactivé
