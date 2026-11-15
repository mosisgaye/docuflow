"""Réglages : l'équipe qui approuve reçoit les mails, et les mails sans facture restent lisibles."""

import json
import pathlib
import time
from email.message import EmailMessage

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from moteur.api import creer_application
from moteur.approbation import REGLES_DEMO, publier
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture
from moteur.reception_mail import signer

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
MOYENNE = "facture-FA-2026-0412.pdf"  # comptable puis directeur financier
CLE = Ed25519PrivateKey.generate()


@pytest.fixture(autouse=True)
def reglages(monkeypatch):
    monkeypatch.setenv("APPROBATION_SECRET", "secret-de-test")
    monkeypatch.setenv("APPROBATION_DESTINATAIRE_COMPTABLE", "fichier@exemple.fr")  # le secours, si l'équipe est vide


@pytest.fixture
def boite():
    mails = []

    def envoyer(message):
        mails.append(message)
        return {"id": f"mail-{len(mails)}"}

    envoyer.mails = mails
    return envoyer


@pytest.fixture
def client(connexion, tmp_path, boite):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    with fabrique() as session:
        publier(session, REGLES_DEMO, "Moussa")
        session.commit()
    donnees = Facture.model_validate(ATTENDU[MOYENNE]["facture"])
    return TestClient(
        creer_application(
            fabrique_session=fabrique, extracteur=lambda texte: ResultatExtraction(donnees, 0.1, "test", "faux"),
            dossier_fichiers=tmp_path, traiter_tout_de_suite=True, odoo=None, envoyeur_mail=boite, cles_mail=[CLE.public_key()],
        )
    )


def ajouter(client, nom, email, niveau):
    return client.post("/reglages/equipe", json={"nom": nom, "email": email, "niveau": niveau, "auteur": "Moussa"})


def deposer(client):
    return client.post("/factures", files={"fichier": (MOYENNE, (FACTURES / MOYENNE).read_bytes(), "application/pdf")})


def test_l_equipe_saisie_recoit_les_demandes(client, boite):
    assert ajouter(client, "Claire Fabre", "Claire@Exemple.fr", "comptable").status_code == 201
    assert ajouter(client, "Julien Roux", "julien@exemple.fr", "comptable").status_code == 201

    deposer(client)

    assert sorted(m.destinataire for m in boite.mails) == ["claire@exemple.fr", "julien@exemple.fr"]  # chacun son lien
    assert "fichier@exemple.fr" not in [m.destinataire for m in boite.mails]


def test_sans_equipe_le_fichier_de_reglages_sert_de_secours(client, boite):
    deposer(client)

    assert [m.destinataire for m in boite.mails] == ["fichier@exemple.fr"]


def test_doublon_role_inconnu_adresse_fausse_et_retrait(client):
    assert ajouter(client, "Claire", "claire@exemple.fr", "comptable").status_code == 201
    assert ajouter(client, "Claire", "claire@exemple.fr", "comptable").status_code == 409
    assert ajouter(client, "Claire", "claire@exemple.fr", "stagiaire").status_code == 422
    assert ajouter(client, "Claire", "pas-une-adresse", "comptable").status_code == 422
    # La même personne peut avoir deux rôles ; elle ne pourra pas pour autant approuver deux niveaux d'une facture.
    assert ajouter(client, "Claire", "claire@exemple.fr", "gerant").status_code == 201

    equipe = client.get("/reglages/equipe").json()
    client.delete(f"/reglages/equipe/{equipe['membres'][0]['id']}")

    assert [m["niveau"] for m in client.get("/reglages/equipe").json()["membres"]] == ["gerant"]
    assert equipe["niveaux"]["directeur_financier"] == "Directeur financier"


def test_le_code_de_confirmation_de_gmail_reste_lisible(client):
    message = EmailMessage()
    message["From"], message["Subject"], message["Message-ID"] = "forwarding-noreply@google.com", "(#481516) Confirmation de transfert", "<gmail@google>"
    message.set_content("Code de confirmation : 481516\nhttps://mail.google.com/confirmer")
    brut = message.as_bytes()
    horodatage = str(int(time.time()))
    client.post("/reception/mail", content=brut, headers={"X-DocuFlow-Horodatage": horodatage, "X-DocuFlow-Signature": signer(CLE, horodatage, brut)})

    reception = client.get("/reglages/reception").json()

    assert reception["active"] is True
    mail = reception["mails"][0]
    assert (mail["statut"], mail["factures"]) == ("sans_facture", 0)
    assert "481516" in mail["texte"]
