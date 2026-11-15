"""Code d'accès de la démonstration en ligne, et limite de dépôts par jour."""

import json
import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from moteur import acces
from moteur.api import creer_application
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
NOMS = list(ATTENDU)[:3]


@pytest.fixture
def client(connexion, tmp_path):
    def extracteur(texte):
        for nom in NOMS:  # la bonne réponse pour chaque fichier, reconnue à son numéro
            if ATTENDU[nom]["facture"]["numero_facture"] in texte:
                return ResultatExtraction(Facture.model_validate(ATTENDU[nom]["facture"]), 0.1, "test", "faux")
        return ResultatExtraction(Facture.model_validate(ATTENDU[NOMS[0]]["facture"]), 0.1, "test", "faux")

    return TestClient(
        creer_application(
            fabrique_session=lambda: Session(bind=connexion, join_transaction_mode="create_savepoint"),
            extracteur=extracteur, dossier_fichiers=tmp_path, traiter_tout_de_suite=True, odoo=None,
        )
    )


def deposer(client, nom):
    return client.post("/factures", files={"fichier": (nom, (FACTURES / nom).read_bytes(), "application/pdf")})


def test_sans_code_configure_tout_est_ouvert(client):
    assert client.get("/factures").status_code == 200
    assert client.get("/acces").json()["requis"] is False


def test_avec_un_code_l_ecran_est_ferme_puis_ouvert_par_le_bon_code(client, monkeypatch):
    monkeypatch.setenv("DOCUFLOW_CODE_ACCES", "graine-de-baobab")

    ferme = client.get("/factures")
    faux = client.post("/acces", json={"code": "pas-le-bon"})
    bon = client.post("/acces", json={"code": "graine-de-baobab"})

    assert ferme.status_code == 401 and ferme.json()["acces"] is True
    assert faux.status_code == 401
    assert bon.status_code == 200
    assert acces.COOKIE in bon.cookies
    assert client.get("/factures").status_code == 200  # le cas légitime passe
    assert client.get("/acces").json() == {"requis": True, "ouvert": True}


def test_changer_le_code_deconnecte(client, monkeypatch):
    monkeypatch.setenv("DOCUFLOW_CODE_ACCES", "premier")
    client.post("/acces", json={"code": "premier"})
    monkeypatch.setenv("DOCUFLOW_CODE_ACCES", "second")

    assert client.get("/factures").status_code == 401


def test_les_chemins_proteges_autrement_ne_demandent_pas_le_code(client, monkeypatch):
    monkeypatch.setenv("DOCUFLOW_CODE_ACCES", "graine-de-baobab")

    assert client.get("/sante").status_code == 200
    v1 = client.get("/v1/factures")
    assert v1.status_code == 401 and "Clé d'API" in v1.json()["detail"]  # c'est la clé qui est demandée, pas le code
    mail = client.post("/reception/mail", content=b"x")
    assert "acces" not in mail.json()  # refus par la réception (pas configurée), pas par le code


def test_trop_d_essais_faux_bloquent_l_adresse(client, monkeypatch):
    monkeypatch.setenv("DOCUFLOW_CODE_ACCES", "graine-de-baobab")
    for _ in range(acces.ESSAIS_MAX):
        assert client.post("/acces", json={"code": "faux"}).status_code == 401

    assert client.post("/acces", json={"code": "graine-de-baobab"}).status_code == 429  # même le bon code attend


def test_la_limite_de_depots_par_jour(client, monkeypatch):
    monkeypatch.setenv("DEPOTS_PAR_JOUR", "2")

    assert deposer(client, NOMS[0]).status_code == 201
    assert deposer(client, NOMS[1]).status_code == 201
    refuse = deposer(client, NOMS[2])

    assert refuse.status_code == 429
    assert "2 factures par jour" in refuse.json()["detail"]


def test_derriere_vercel_l_adresse_du_visiteur_est_comptee_et_la_limite_totale_tient(client, monkeypatch):
    monkeypatch.setenv("DOCUFLOW_CODE_ACCES", "graine-de-baobab")
    for rang in range(acces.ESSAIS_MAX):
        client.post("/acces", json={"code": "faux"}, headers={"X-Forwarded-For": "203.0.113.7, 76.76.21.1"})

    # Un autre visiteur, derrière la même adresse Vercel, n'est pas bloqué par le premier.
    autre = client.post("/acces", json={"code": "graine-de-baobab"}, headers={"X-Forwarded-For": "198.51.100.9, 76.76.21.1"})
    assert autre.status_code == 200
    # Mais changer d'adresse à chaque essai ne permet pas d'essayer sans fin.
    for rang in range(acces.ESSAIS_MAX_TOTAL):
        client.post("/acces", json={"code": "faux"}, headers={"X-Forwarded-For": f"192.0.2.{rang}"})
    assert client.post("/acces", json={"code": "graine-de-baobab"}, headers={"X-Forwarded-For": "198.51.100.10"}).status_code == 429
