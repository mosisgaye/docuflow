import json
import pathlib
from datetime import date
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from moteur.api import creer_application
from moteur.base import Etat
from moteur.export import ErreurEnvoi, ErreurExport, ecriture, en_csv, nom_fichier
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture
from moteur.workflow import TransitionInterdite, exporter, rejeter, traiter, valider

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
GARAGE = Facture.model_validate(ATTENDU["facture-F26-1193.pdf"]["facture"])


def recevoir(session, nom: str = "facture-F26-1193.pdf"):
    donnees = Facture.model_validate(ATTENDU[nom]["facture"])
    return traiter(session, (FACTURES / nom).read_bytes(), nom, lambda texte: ResultatExtraction(donnees, 0.1, "test", "faux"), date(2026, 11, 14)).facture


def logiciel(statut: int = 201, recues: list | None = None) -> httpx.Client:
    def repondre(requete: httpx.Request) -> httpx.Response:
        if recues is not None:
            recues.append(requete)
        return httpx.Response(statut)

    return httpx.Client(transport=httpx.MockTransport(repondre))


# ───────── L'écriture comptable ─────────


def test_l_ecriture_d_une_facture_d_achat():
    lignes = ecriture(GARAGE)

    assert [(ligne.compte, ligne.debit, ligne.credit) for ligne in lignes] == [
        ("606000", Decimal("398.40"), Decimal("0.00")),
        ("445660", Decimal("79.68"), Decimal("0.00")),
        ("401000", Decimal("0.00"), Decimal("478.08")),
    ]
    assert lignes[2].compte_auxiliaire == "F529874315"
    assert {ligne.piece for ligne in lignes} == {"F26-1193"}
    assert {ligne.date for ligne in lignes} == {"2026-11-10"}


def test_l_ecriture_est_toujours_equilibree():
    lignes = ecriture(GARAGE)

    assert sum(ligne.debit for ligne in lignes) == sum(ligne.credit for ligne in lignes)


def test_une_facture_dont_les_totaux_ne_tombent_pas_juste_n_est_pas_exportee():
    fausse = GARAGE.model_copy(update={"total_ttc": Decimal("500.00")})

    with pytest.raises(ErreurExport, match="déséquilibrée"):
        ecriture(fausse)


def test_une_information_manquante_empeche_l_ecriture():
    with pytest.raises(ErreurExport, match="date_facture"):
        ecriture(GARAGE.model_copy(update={"date_facture": None}))


def test_le_compte_de_charge_est_reglable(monkeypatch):
    monkeypatch.setenv("EXPORT_COMPTE_CHARGE", "615500")

    assert ecriture(GARAGE)[0].compte == "615500"


def test_le_csv_est_a_la_francaise():
    texte = en_csv(ecriture(GARAGE))

    assert texte.startswith("﻿Journal;Date;Piece;Compte")
    assert "HA;2026-11-10;F26-1193;401000;F529874315;Garage Central Bertin fact. F26-1193;0,00;478,08;2026-12-10" in texte


def test_le_nom_du_fichier_ne_depend_que_de_la_facture():
    assert nom_fichier(GARAGE, "abcdef1234") == "F26-1193_abcdef12.csv"
    assert nom_fichier(GARAGE.model_copy(update={"numero_facture": "A/B 1"}), "abcdef1234") == "A_B_1_abcdef12.csv"


# ───────── Dans le workflow ─────────


def test_exporter_une_facture_validee(session, tmp_path, monkeypatch):
    monkeypatch.delenv("EXPORT_WEBHOOK_URL", raising=False)
    facture = recevoir(session)
    valider(session, facture.id, "Awa")

    exporter(session, facture.id, "Awa", tmp_path)

    assert facture.etat == Etat.EXPORTEE
    evenement = facture.evenements[-1]
    assert (evenement.type, evenement.auteur) == ("EXPORT", "Awa")
    assert evenement.detail["logiciel"] is None
    assert len(evenement.detail["ecriture"]) == 3
    assert (tmp_path / evenement.detail["fichier"]).read_bytes().count(b"\r\n") == 4


def test_exporter_deux_fois_ne_fait_rien_la_seconde_fois(session, tmp_path, monkeypatch):
    recues = []
    monkeypatch.setenv("EXPORT_WEBHOOK_URL", "https://compta.exemple/ecritures")
    facture = recevoir(session)
    valider(session, facture.id, "Awa")

    exporter(session, facture.id, "Awa", tmp_path, logiciel(201, recues))
    exporter(session, facture.id, "Awa", tmp_path, logiciel(201, recues))

    assert len(recues) == 1
    assert [evenement.type for evenement in facture.evenements].count("EXPORT") == 1
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("etat", ["a_valider", "en_anomalie", "rejetee"])
def test_seule_une_facture_validee_peut_etre_exportee(session, tmp_path, etat):
    facture = recevoir(session, "facture-erreur-total.pdf" if etat != "a_valider" else "facture-F26-1193.pdf")
    if etat == "rejetee":
        rejeter(session, facture.id, "Awa", "Total faux")

    with pytest.raises(TransitionInterdite, match="validée"):
        exporter(session, facture.id, "Awa", tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_l_envoi_au_logiciel_porte_une_cle_d_idempotence(session, tmp_path, monkeypatch):
    recues = []
    monkeypatch.setenv("EXPORT_WEBHOOK_URL", "https://compta.exemple/ecritures")
    facture = recevoir(session)
    valider(session, facture.id, "Awa")

    exporter(session, facture.id, "Awa", tmp_path, logiciel(201, recues))

    corps = json.loads(recues[0].content)
    assert recues[0].headers["idempotency-key"] == str(facture.id)
    assert corps["ecriture"][2] == {**corps["ecriture"][2], "compte": "401000", "credit": "478.08"}
    assert facture.evenements[-1].detail["logiciel"] == {"adresse": "https://compta.exemple/ecritures", "statut": 201}


@pytest.mark.parametrize("statut", [400, 500, 503])
def test_un_refus_du_logiciel_laisse_la_facture_validee(session, tmp_path, monkeypatch, statut):
    monkeypatch.setenv("EXPORT_WEBHOOK_URL", "https://compta.exemple/ecritures")
    facture = recevoir(session)
    valider(session, facture.id, "Awa")

    with pytest.raises(ErreurEnvoi, match=str(statut)):
        exporter(session, facture.id, "Awa", tmp_path, logiciel(statut))

    assert facture.etat == Etat.VALIDEE
    assert facture.evenements[-1].type == "EXPORT_ECHOUE"


def test_apres_un_refus_un_nouvel_essai_reussit(session, tmp_path, monkeypatch):
    monkeypatch.setenv("EXPORT_WEBHOOK_URL", "https://compta.exemple/ecritures")
    facture = recevoir(session)
    valider(session, facture.id, "Awa")
    with pytest.raises(ErreurEnvoi):
        exporter(session, facture.id, "Awa", tmp_path, logiciel(503))

    exporter(session, facture.id, "Awa", tmp_path, logiciel(201))

    assert facture.etat == Etat.EXPORTEE
    assert len(list(tmp_path.iterdir())) == 1


# ───────── Par l'API ─────────


@pytest.fixture
def api(connexion, tmp_path, monkeypatch):
    monkeypatch.setenv("EXPORT_WEBHOOK_URL", "https://compta.exemple/ecritures")
    etat = {"statut": 201}
    application = creer_application(
        fabrique_session=lambda: Session(bind=connexion, join_transaction_mode="create_savepoint"),
        extracteur=lambda texte: ResultatExtraction(GARAGE, 0.1, "test", "faux"),
        dossier_fichiers=tmp_path / "fichiers",
        dossier_exports=tmp_path / "exports",
        client_export=httpx.Client(transport=httpx.MockTransport(lambda requete: httpx.Response(etat["statut"]))),
    )
    client = TestClient(application)
    client.etat_logiciel = etat
    return client


def facture_validee(api) -> str:
    identifiant = api.post("/factures", files={"fichier": ("f.pdf", (FACTURES / "facture-F26-1193.pdf").read_bytes(), "application/pdf")}).json()["id"]
    api.post(f"/factures/{identifiant}/validation", json={"auteur": "Awa"})
    return identifiant


def test_exporter_par_l_api_puis_telecharger_le_fichier(api):
    identifiant = facture_validee(api)

    reponse = api.post(f"/factures/{identifiant}/export", json={"auteur": "Awa"})
    fichier = api.get(f"/factures/{identifiant}/export")

    assert reponse.status_code == 200
    assert reponse.json()["etat"] == "exportee"
    assert fichier.status_code == 200
    assert fichier.headers["content-type"].startswith("text/csv")
    assert "401000;F529874315" in fichier.content.decode("utf-8-sig")


def test_un_refus_du_logiciel_donne_502_et_reste_au_journal(api):
    identifiant = facture_validee(api)
    api.etat_logiciel["statut"] = 503

    reponse = api.post(f"/factures/{identifiant}/export", json={"auteur": "Awa"})
    facture = api.get(f"/factures/{identifiant}").json()

    assert reponse.status_code == 502
    assert facture["etat"] == "validee"
    assert facture["evenements"][-1]["type"] == "EXPORT_ECHOUE"


def test_exporter_une_facture_non_validee_donne_409(api):
    identifiant = api.post("/factures", files={"fichier": ("f.pdf", (FACTURES / "facture-F26-1193.pdf").read_bytes(), "application/pdf")}).json()["id"]

    assert api.post(f"/factures/{identifiant}/export", json={"auteur": "Awa"}).status_code == 409
    assert api.get(f"/factures/{identifiant}/export").status_code == 404
