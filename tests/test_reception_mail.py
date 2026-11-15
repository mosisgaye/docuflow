"""Réception des factures par mail : signature, idempotence, tri des pièces jointes."""

import base64
import json
import pathlib
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from moteur.api import creer_application
from moteur.base import FactureEnBase, MailRecu, Tache
from moteur.reception_mail import MailEntrant, PieceJointe, SignatureInvalide, recevoir_mail, signer, verifier_signature

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
JUSTE = "facture-F26-1193.pdf"
AUTRE = "facture-2026-11-087.pdf"
SECRET = "secret-de-test"


def piece(nom: str, contenu: bytes | None = None, type_mime: str = "application/pdf") -> dict:
    contenu = contenu if contenu is not None else (FACTURES / nom).read_bytes()
    return {"nom": nom, "type": type_mime, "contenu_base64": base64.b64encode(contenu).decode()}


def mail(*pieces: dict, message_id: str = "<abc@fournisseur.fr>") -> dict:
    return {"message_id": message_id, "expediteur": "compta@fournisseur.fr", "objet": "Facture novembre", "pieces": list(pieces)}


def envoyer(client: TestClient, donnees: dict, secret: str = SECRET, horodatage: str | None = None, corps: bytes | None = None):
    corps = corps if corps is not None else json.dumps(donnees).encode()
    horodatage = horodatage or str(int(time.time()))
    entetes = {"X-DocuFlow-Horodatage": horodatage, "X-DocuFlow-Signature": signer(secret, horodatage, corps), "Content-Type": "application/json"}
    return client.post("/reception/mail", content=corps, headers=entetes)


@pytest.fixture
def fabrique(connexion):
    return lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")


@pytest.fixture
def client(fabrique, tmp_path):
    return TestClient(creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path / "recus", secret_mail=SECRET))


def compter(fabrique, modele) -> int:
    with fabrique() as session:
        return session.scalar(select(func.count()).select_from(modele))


# ───────── Signature ─────────


def test_un_mail_signe_cree_la_facture_et_sa_tache(client, fabrique, tmp_path):
    reponse = envoyer(client, mail(piece(JUSTE)))

    assert reponse.status_code == 202
    corps = reponse.json()
    assert corps["deja_vu"] is False
    assert corps["statut"] == "traite"
    assert [p["resultat"] for p in corps["pieces"]] == ["facture"]
    facture = client.get(f"/factures/{corps['pieces'][0]['facture_id']}").json()
    assert facture["etat"] == "recue"
    reception = facture["evenements"][0]
    assert reception["type"] == "RECEPTION"
    assert reception["detail"]["source"] == "mail"
    assert reception["detail"]["expediteur"] == "compta@fournisseur.fr"
    assert reception["detail"]["objet"] == "Facture novembre"
    assert reception["detail"]["mail_id"] == corps["id"]
    assert compter(fabrique, Tache) == 1
    assert len(list((tmp_path / "recus").glob("*.pdf"))) == 1  # le fichier est là avant que le travailleur le cherche


@pytest.mark.parametrize(
    "secret, decalage_s",
    [("mauvais-secret", 0), (SECRET, -3600), (SECRET, 3600)],
    ids=["secret faux", "envoi rejoué une heure après", "horodatage dans le futur"],
)
def test_un_envoi_mal_signe_est_refuse(client, fabrique, secret, decalage_s):
    reponse = envoyer(client, mail(piece(JUSTE)), secret=secret, horodatage=str(int(time.time()) + decalage_s))

    assert reponse.status_code == 401
    assert compter(fabrique, MailRecu) == 0
    assert compter(fabrique, FactureEnBase) == 0


def test_un_envoi_sans_signature_est_refuse(client):
    reponse = client.post("/reception/mail", json=mail(piece(JUSTE)))

    assert reponse.status_code == 401


def test_un_corps_modifie_apres_signature_est_refuse(client):
    corps = json.dumps(mail(piece(JUSTE))).encode()
    horodatage = str(int(time.time()))
    entetes = {"X-DocuFlow-Horodatage": horodatage, "X-DocuFlow-Signature": signer(SECRET, horodatage, corps)}

    reponse = client.post("/reception/mail", content=corps.replace(b"Facture novembre", b"Facture piegee"), headers=entetes)

    assert reponse.status_code == 401


def test_sans_secret_configure_la_reception_est_fermee(fabrique, tmp_path):
    client = TestClient(creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path, secret_mail=""))

    assert envoyer(client, mail(piece(JUSTE))).status_code == 503


def test_verifier_signature_accepte_la_bonne_et_refuse_le_reste():
    corps = b'{"a": 1}'
    verifier_signature(SECRET, "1000", signer(SECRET, "1000", corps), corps, maintenant=1000)
    with pytest.raises(SignatureInvalide):
        verifier_signature(SECRET, "abc", "x", corps, maintenant=1000)
    with pytest.raises(SignatureInvalide):
        verifier_signature(SECRET, "1000", signer(SECRET, "1000", corps), corps, maintenant=1301)


# ───────── Idempotence ─────────


def test_le_meme_mail_recu_deux_fois_n_est_traite_qu_une_fois(client, fabrique):
    premier = envoyer(client, mail(piece(JUSTE)))

    second = envoyer(client, mail(piece(JUSTE)))

    assert second.status_code == 200
    assert second.json()["deja_vu"] is True
    assert second.json()["id"] == premier.json()["id"]
    assert compter(fabrique, MailRecu) == 1
    assert compter(fabrique, FactureEnBase) == 1
    assert compter(fabrique, Tache) == 1


def test_une_facture_deja_deposee_a_l_ecran_est_reconnue(client, fabrique):
    client.post("/factures", files={"fichier": (JUSTE, (FACTURES / JUSTE).read_bytes(), "application/pdf")})

    reponse = envoyer(client, mail(piece(JUSTE)))

    assert reponse.json()["pieces"][0]["resultat"] == "deja_recue"
    assert compter(fabrique, FactureEnBase) == 1
    facture = client.get(f"/factures/{reponse.json()['pieces'][0]['facture_id']}").json()
    assert facture["evenements"][-1]["type"] == "DOUBLON_FICHIER"
    assert facture["evenements"][-1]["detail"]["source"] == "mail"


# ───────── Tri des pièces jointes ─────────


def test_chaque_pdf_devient_une_facture_et_le_reste_est_ignore(client, fabrique):
    reponse = envoyer(
        client,
        mail(
            piece(JUSTE),
            piece(AUTRE),
            piece("logo.png", b"\x89PNG\r\n\x1a\n...", "image/png"),
            piece("faux.pdf", b"ceci n'est pas un pdf"),
            piece("casse.pdf", b"%PDF-1.7\nn'importe quoi"),
        ),
    )

    pieces = {p["nom"]: p for p in reponse.json()["pieces"]}
    assert pieces[JUSTE]["resultat"] == "facture"
    assert pieces[AUTRE]["resultat"] == "facture"
    assert pieces["logo.png"] == {"nom": "logo.png", "resultat": "ignoree", "raison": "Ce n'est pas un PDF."}
    assert pieces["faux.pdf"]["raison"] == "Ce n'est pas un PDF."  # le nom ne suffit pas, on regarde le contenu
    assert pieces["casse.pdf"]["raison"] == "PDF illisible."
    assert compter(fabrique, FactureEnBase) == 2
    assert compter(fabrique, Tache) == 2


def test_un_mail_sans_pdf_est_note_sans_facture(client, fabrique):
    reponse = envoyer(client, mail())

    assert reponse.status_code == 202
    assert reponse.json()["statut"] == "sans_facture"
    assert compter(fabrique, MailRecu) == 1
    assert compter(fabrique, FactureEnBase) == 0


def test_un_nom_de_piece_ne_peut_pas_sortir_du_dossier(client):
    reponse = envoyer(client, mail(piece(JUSTE) | {"nom": "../../etc/facture.pdf"}))

    facture = client.get(f"/factures/{reponse.json()['pieces'][0]['facture_id']}").json()
    assert facture["nom_fichier"] == "facture.pdf"


def test_une_piece_mal_encodee_est_refusee(client, fabrique):
    reponse = envoyer(client, mail({"nom": "x.pdf", "type": "application/pdf", "contenu_base64": "@@pas du base64@@"}))

    assert reponse.status_code == 422
    assert compter(fabrique, MailRecu) == 0


def test_un_mail_mal_forme_est_refuse(client):
    assert envoyer(client, {}, corps=b'{"objet": "sans identifiant"}').status_code == 422


# ───────── Concurrence (vraies transactions) ─────────


def test_le_meme_mail_recu_deux_fois_en_meme_temps(moteur_base, tmp_path):
    contenu = (FACTURES / JUSTE).read_bytes()
    entrant = MailEntrant("<simultane@fournisseur.fr>", "compta@fournisseur.fr", "Facture", [PieceJointe(JUSTE, "application/pdf", contenu)])
    comptes_rendus, depart = [], threading.Barrier(2)

    def recevoir():
        with Session(moteur_base) as session:
            depart.wait()
            comptes_rendus.append(recevoir_mail(session, entrant, tmp_path))
            session.commit()

    try:
        fils = [threading.Thread(target=recevoir) for _ in range(2)]
        for fil in fils:
            fil.start()
        for fil in fils:
            fil.join(timeout=30)

        assert sorted(compte_rendu.deja_vu for compte_rendu in comptes_rendus) == [False, True]
        with Session(moteur_base) as session:
            assert session.scalar(select(func.count()).select_from(MailRecu)) == 1
            assert session.scalar(select(func.count()).select_from(FactureEnBase)) == 1
    finally:
        with moteur_base.begin() as connexion:
            connexion.execute(text("truncate mails_recus, taches, evenements, factures"))
