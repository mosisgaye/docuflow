"""Réception des factures par mail : signature, analyse du mail brut, idempotence, tri des pièces."""

import pathlib
import threading
import time
from email.message import EmailMessage

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from moteur.api import creer_application
from moteur.base import FactureEnBase, MailRecu, Tache
from moteur.reception_mail import SignatureInvalide, cles_publiques, en_base64, lire_mail_brut, recevoir_mail, signer, verifier_signature

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
JUSTE = "facture-F26-1193.pdf"
AUTRE = "facture-2026-11-087.pdf"
CLE = Ed25519PrivateKey.generate()  # la clé de l'adaptateur
INTRUS = Ed25519PrivateKey.generate()  # une clé que DocuFlow ne connaît pas


def mail(*pieces: tuple[str, bytes, str], message_id: str | None = "<abc@fournisseur.fr>", objet: str = "Facture novembre") -> bytes:
    """Un mail brut, comme Cloudflare le transmet. pieces : (nom, contenu, type MIME)."""
    message = EmailMessage()
    message["From"] = "Service compta <compta@fournisseur.fr>"
    message["To"] = "depot@factures.moussagaye.com"
    message["Subject"] = objet
    if message_id:
        message["Message-ID"] = message_id
    message.set_content("Bonjour, veuillez trouver nos factures en pièce jointe.")
    for nom, contenu, type_mime in pieces:
        principal, secondaire = type_mime.split("/")
        message.add_attachment(contenu, maintype=principal, subtype=secondaire, filename=nom)
    return message.as_bytes()


def pdf(nom: str) -> tuple[str, bytes, str]:
    return (nom, (FACTURES / nom).read_bytes(), "application/pdf")


def envoyer(client: TestClient, brut: bytes, cle: Ed25519PrivateKey = CLE, horodatage: str | None = None):
    horodatage = horodatage or str(int(time.time()))
    entetes = {"X-DocuFlow-Horodatage": horodatage, "X-DocuFlow-Signature": signer(cle, horodatage, brut), "Content-Type": "message/rfc822"}
    return client.post("/reception/mail", content=brut, headers=entetes)


@pytest.fixture
def fabrique(connexion):
    return lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")


@pytest.fixture
def client(fabrique, tmp_path):
    return TestClient(creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path / "recus", cles_mail=[CLE.public_key()]))


def compter(fabrique, modele) -> int:
    with fabrique() as session:
        return session.scalar(select(func.count()).select_from(modele))


# ───────── Analyse du mail brut ─────────


def test_le_mail_brut_est_analyse():
    lu = lire_mail_brut(mail(pdf(JUSTE), objet="Facture décembre"))

    assert lu.message_id == "<abc@fournisseur.fr>"
    assert lu.expediteur == "compta@fournisseur.fr"  # l'adresse seule, sans le nom affiché
    assert lu.objet == "Facture décembre"  # accents décodés
    assert [(piece.nom, piece.type_mime) for piece in lu.pieces] == [(JUSTE, "application/pdf")]
    assert lu.pieces[0].contenu == (FACTURES / JUSTE).read_bytes()  # le PDF arrive intact
    # Le texte du mail n'est pas pris pour une pièce jointe.


def test_un_mail_sans_identifiant_reste_reconnaissable():
    brut = mail(pdf(JUSTE), message_id=None)

    assert lire_mail_brut(brut).message_id == lire_mail_brut(brut).message_id
    assert lire_mail_brut(brut).message_id.startswith("<sans-identifiant-")


def test_un_mail_abime_ne_fait_pas_tomber_l_analyse():
    lu = lire_mail_brut(b"From: \x00\xff pas une adresse\r\n\r\ncorps sans structure")

    assert lu.pieces == []
    assert lu.expediteur


# ───────── Signature ─────────


def test_un_mail_signe_cree_la_facture_et_sa_tache(client, fabrique, tmp_path):
    reponse = envoyer(client, mail(pdf(JUSTE)))

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
    "cle, decalage_s",
    [(INTRUS, 0), (CLE, -3600), (CLE, 3600)],
    ids=["clé inconnue", "envoi rejoué une heure après", "horodatage dans le futur"],
)
def test_un_envoi_mal_signe_est_refuse(client, fabrique, cle, decalage_s):
    reponse = envoyer(client, mail(pdf(JUSTE)), cle=cle, horodatage=str(int(time.time()) + decalage_s))

    assert reponse.status_code == 401
    assert compter(fabrique, MailRecu) == 0
    assert compter(fabrique, FactureEnBase) == 0


def test_un_envoi_sans_signature_est_refuse(client):
    assert client.post("/reception/mail", content=mail(pdf(JUSTE))).status_code == 401


def test_un_mail_modifie_apres_signature_est_refuse(client):
    brut = mail(pdf(JUSTE))
    horodatage = str(int(time.time()))
    entetes = {"X-DocuFlow-Horodatage": horodatage, "X-DocuFlow-Signature": signer(CLE, horodatage, brut)}

    reponse = client.post("/reception/mail", content=brut.replace(b"Facture novembre", b"Facture piegee!!"), headers=entetes)

    assert reponse.status_code == 401


def test_sans_cle_configuree_la_reception_est_fermee(fabrique, tmp_path):
    client = TestClient(creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path, cles_mail=[]))

    assert envoyer(client, mail(pdf(JUSTE))).status_code == 503


def test_verifier_signature_accepte_la_bonne_et_refuse_le_reste():
    corps = b"un mail"
    cles = [INTRUS.public_key(), CLE.public_key()]  # plusieurs clés acceptées : n'importe laquelle suffit
    verifier_signature(cles, "1000", signer(CLE, "1000", corps), corps, maintenant=1000)
    for horodatage, signature, maintenant in [("abc", "x", 1000), ("1000", "pas du base64 !", 1000), ("1000", signer(CLE, "1000", corps), 1301)]:
        with pytest.raises(SignatureInvalide):
            verifier_signature(cles, horodatage, signature, corps, maintenant=maintenant)


def test_les_cles_publiques_se_lisent_depuis_la_configuration():
    texte = f"{en_base64(CLE.public_key())}, {en_base64(INTRUS.public_key())}"

    assert [en_base64(cle) for cle in cles_publiques(texte)] == [en_base64(CLE.public_key()), en_base64(INTRUS.public_key())]
    assert cles_publiques("") == []


# ───────── Idempotence ─────────


def test_le_meme_mail_recu_deux_fois_n_est_traite_qu_une_fois(client, fabrique):
    premier = envoyer(client, mail(pdf(JUSTE)))

    second = envoyer(client, mail(pdf(JUSTE)))

    assert second.status_code == 200
    assert second.json()["deja_vu"] is True
    assert second.json()["id"] == premier.json()["id"]
    assert compter(fabrique, MailRecu) == 1
    assert compter(fabrique, FactureEnBase) == 1
    assert compter(fabrique, Tache) == 1


def test_une_facture_deja_deposee_a_l_ecran_est_reconnue(client, fabrique):
    client.post("/factures", files={"fichier": (JUSTE, (FACTURES / JUSTE).read_bytes(), "application/pdf")})

    reponse = envoyer(client, mail(pdf(JUSTE)))

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
            pdf(JUSTE),
            pdf(AUTRE),
            ("logo.png", b"\x89PNG\r\n\x1a\n...", "image/png"),
            ("faux.pdf", b"ceci n'est pas un pdf", "application/pdf"),
            ("casse.pdf", b"%PDF-1.7\nn'importe quoi", "application/pdf"),
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
    assert reponse.json()["pieces"] == []  # le texte du mail n'est pas une pièce jointe
    assert compter(fabrique, MailRecu) == 1
    assert compter(fabrique, FactureEnBase) == 0


def test_un_nom_de_piece_ne_peut_pas_sortir_du_dossier(client):
    reponse = envoyer(client, mail(("../../etc/facture.pdf", (FACTURES / JUSTE).read_bytes(), "application/pdf")))

    facture = client.get(f"/factures/{reponse.json()['pieces'][0]['facture_id']}").json()
    assert facture["nom_fichier"] == "facture.pdf"


def test_un_corps_vide_est_refuse(client):
    assert envoyer(client, b"").status_code == 422


# ───────── Concurrence (vraies transactions) ─────────


def test_le_meme_mail_recu_deux_fois_en_meme_temps(moteur_base, tmp_path):
    entrant = lire_mail_brut(mail(pdf(JUSTE), message_id="<simultane@fournisseur.fr>"))
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
