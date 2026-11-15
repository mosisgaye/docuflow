"""Mails d'approbation : envoyés après l'enregistrement, liens signés sans effet à l'ouverture."""

import json
import pathlib
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from moteur import notifications
from moteur.api import creer_application
from moteur.approbation import REGLES_DEMO, publier
from moteur.base import FactureEnBase
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
MOYENNE = "facture-FA-2026-0412.pdf"  # 3 166,20 € : comptable puis directeur financier


@pytest.fixture(autouse=True)
def reglages(monkeypatch):
    monkeypatch.setenv("APPROBATION_SECRET", "secret-de-test")
    monkeypatch.setenv("APPROBATION_DESTINATAIRE_COMPTABLE", "claire@exemple.fr")
    monkeypatch.setenv("APPROBATION_DESTINATAIRE_DIRECTEUR_FINANCIER", "paul@exemple.fr")
    monkeypatch.setenv("APPROBATION_ADRESSE", "http://localhost:5180/api")


class Boite:
    """Remplace Resend : garde les mails au lieu de les envoyer."""

    def __init__(self):
        self.mails: list[notifications.Message] = []
        self.panne = False

    def __call__(self, message):
        if self.panne:
            raise RuntimeError("Resend indisponible")
        self.mails.append(message)
        return {"id": f"mail-{len(self.mails)}"}

    def jeton(self, rang: int = -1) -> str:
        return self.mails[rang].texte.split("/approbation/")[1].split()[0]


@pytest.fixture
def boite():
    return Boite()


@pytest.fixture
def client(connexion, boite, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    with fabrique() as session:
        publier(session, REGLES_DEMO, "Moussa")
        session.commit()
    donnees = Facture.model_validate(ATTENDU[MOYENNE]["facture"])
    return TestClient(
        creer_application(
            fabrique_session=fabrique, extracteur=lambda texte: ResultatExtraction(donnees, 0.1, "test", "faux"),
            dossier_fichiers=tmp_path, traiter_tout_de_suite=True, odoo=None, envoyeur_mail=boite,
        )
    )


def deposer(client) -> dict:
    return client.post("/factures", files={"fichier": (MOYENNE, (FACTURES / MOYENNE).read_bytes(), "application/pdf")}).json()


# ───────── Les mails ─────────


def test_le_premier_niveau_est_prevenu_a_la_fin_des_controles(client, boite):
    facture = deposer(client)

    assert [m.destinataire for m in boite.mails] == ["claire@exemple.fr"]
    mail = boite.mails[0]
    assert mail.sujet == "Approbation demandée : facture FA-2026-0412 de Atelier Numérique du Midi SARL (3 166,20 €)"
    assert "en tant que comptable" in mail.texte
    assert "http://localhost:5180/api/approbation/" in mail.html
    assert client.get(f"/factures/{facture['id']}").json()["evenements"][-1]["type"] == "NOTIFICATION"


def test_apres_une_approbation_le_niveau_suivant_est_prevenu(client, boite):
    deposer(client)

    client.post(f"/approbation/{boite.jeton()}", data={"decision": "approuver"})

    assert [m.destinataire for m in boite.mails] == ["claire@exemple.fr", "paul@exemple.fr"]
    assert "Plus de 1 000 € TTC" in boite.mails[1].texte


def test_un_mail_rate_ne_casse_rien_et_est_note(client, boite):
    boite.panne = True

    facture = deposer(client)

    assert facture["etat"] == "a_valider"
    assert client.get(f"/factures/{facture['id']}").json()["evenements"][-1]["type"] == "NOTIFICATION_ECHOUEE"


def test_sans_reglages_aucun_mail_n_est_prepare(client, boite, monkeypatch):
    monkeypatch.delenv("APPROBATION_SECRET")

    deposer(client)

    assert boite.mails == []


# ───────── Les liens ─────────


def test_ouvrir_le_lien_n_approuve_rien(client, boite):
    facture = deposer(client)

    page = client.get(f"/approbation/{boite.jeton()}")

    assert page.status_code == 200
    assert "Approuver la facture" in page.text and "claire@exemple.fr" in page.text
    assert client.get(f"/factures/{facture['id']}").json()["etat"] == "a_valider"  # toujours rien de fait


def test_le_bouton_approuve_au_nom_du_destinataire(client, boite):
    facture = deposer(client)

    reponse = client.post(f"/approbation/{boite.jeton()}", data={"decision": "approuver"})

    assert "approuvé" in reponse.text
    detail = client.get(f"/factures/{facture['id']}").json()
    assert detail["etat"] == "en_approbation"
    assert [(a["niveau"], a["personne"]) for a in detail["approbations"]] == [("comptable", "claire@exemple.fr")]


def test_un_lien_ne_sert_qu_une_fois(client, boite):
    deposer(client)
    jeton = boite.jeton()
    client.post(f"/approbation/{jeton}", data={"decision": "approuver"})

    deuxieme = client.post(f"/approbation/{jeton}", data={"decision": "approuver"})

    assert deuxieme.status_code == 409
    assert "a servi" in deuxieme.text


def test_le_circuit_complet_par_les_mails(client, boite):
    facture = deposer(client)
    client.post(f"/approbation/{boite.jeton(0)}", data={"decision": "approuver"})

    fin = client.post(f"/approbation/{boite.jeton(1)}", data={"decision": "approuver"})

    assert "tous les niveaux ont approuvé" in fin.text
    assert client.get(f"/factures/{facture['id']}").json()["etat"] == "validee"


def test_rejeter_demande_un_motif(client, boite):
    facture = deposer(client)

    sans = client.post(f"/approbation/{boite.jeton()}", data={"decision": "rejeter", "motif": "  "})
    avec = client.post(f"/approbation/{boite.jeton()}", data={"decision": "rejeter", "motif": "Pas commandé"})

    assert sans.status_code == 409
    assert "rejetée" in avec.text
    assert client.get(f"/factures/{facture['id']}").json()["etat"] == "rejetee"


def test_un_lien_falsifie_est_refuse(client, boite):
    deposer(client)
    corps, signature = boite.jeton().split(".")

    assert client.get(f"/approbation/{corps}.{signature[:-2]}AA").status_code == 410
    assert client.get("/approbation/nimporte-quoi").status_code == 410


def test_un_lien_expire_est_refuse(client, boite, monkeypatch):
    deposer(client)
    jeton = boite.jeton()
    monkeypatch.setattr(time, "time", lambda: 10**12)

    reponse = client.get(f"/approbation/{jeton}")

    assert reponse.status_code == 410
    assert "expiré" in reponse.text


def test_si_la_facture_change_le_lien_ne_vaut_plus(client, boite, connexion):
    facture = deposer(client)
    with Session(bind=connexion, join_transaction_mode="create_savepoint") as session:
        enregistree = session.get(FactureEnBase, facture["id"])
        enregistree.donnees = {**enregistree.donnees, "total_ttc": "9999.00"}
        session.commit()

    reponse = client.get(f"/approbation/{boite.jeton()}")

    assert reponse.status_code == 410
    assert "a changé" in reponse.text


def test_le_message_d_erreur_n_injecte_pas_de_html(client, boite):
    assert "<script>" not in client.get("/approbation/<script>alert(1)</script>.x").text
