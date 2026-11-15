"""Factures scannées et photos : lues sur image par l'IA, logos de mail ignorés, coût compté."""

import base64
import io
import json
import pathlib
import time
from datetime import date
from email.message import EmailMessage

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from moteur.api import creer_application
from moteur.extraction_llm import ResultatExtraction, extraire_images
from moteur.lecture_pdf import PAGES_IMAGES_MAX, image_en_pdf, lire_pdf, pages_en_images
from moteur.modeles import Facture
from moteur.reception_mail import signer

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
GARAGE = "facture-F26-1193.pdf"
AUJOURD_HUI = date(2026, 11, 14)


def photo(largeur: int = 1200, hauteur: int = 1600, format_: str = "JPEG", bruit: bool = True) -> bytes:
    """Une « photo » : assez lourde pour ressembler à une vraie (une image unie se compresse trop bien)."""
    import random

    image = Image.new("RGB", (largeur, hauteur), "white")
    if bruit:
        generateur = random.Random(4)
        pixels = image.load()
        for _ in range(largeur * hauteur // 6):
            pixels[generateur.randrange(largeur), generateur.randrange(hauteur)] = (generateur.randrange(256),) * 3
    tampon = io.BytesIO()
    image.save(tampon, format_)
    return tampon.getvalue()


class FauxLecteurImages:
    def __init__(self):
        self.appels: list[list[bytes]] = []

    def __call__(self, images):
        self.appels.append(images)
        return ResultatExtraction(
            Facture.model_validate(ATTENDU[GARAGE]["facture"]), 2.4, "test", "faux", jetons={"entree": 1500, "sortie": 300}, pages_images=len(images)
        )


# ───────── Images et PDF ─────────


def test_une_photo_devient_un_pdf_sans_texte():
    pdf = image_en_pdf(photo())

    assert pdf.startswith(b"%PDF-")
    assert lire_pdf(pdf).a_du_texte is False  # elle partira donc en lecture d'image


def test_ce_qui_n_est_pas_une_image_n_est_pas_converti():
    assert image_en_pdf(b"Bonjour, ceci est un texte.") is None


def test_l_orientation_du_telephone_est_appliquee():
    image = Image.new("RGB", (400, 200), "white")
    exif = image.getexif()
    exif[0x0112] = 6  # le téléphone dit « tourner de 90° » : la photo est en fait en portrait
    tampon = io.BytesIO()
    image.save(tampon, "JPEG", exif=exif)

    page = Image.open(io.BytesIO(pages_en_images(image_en_pdf(tampon.getvalue()))[0]))

    assert page.height > page.width


def test_seules_les_premieres_pages_sont_lues():
    images = [Image.new("RGB", (300, 400), "white") for _ in range(5)]
    tampon = io.BytesIO()
    images[0].save(tampon, "PDF", save_all=True, append_images=images[1:])

    assert len(pages_en_images(tampon.getvalue())) == PAGES_IMAGES_MAX


# ───────── L'appel à l'IA ─────────


@pytest.mark.parametrize("fournisseur", ["openai", "gemini"])
def test_les_images_partent_dans_la_requete_et_les_jetons_reviennent(monkeypatch, fournisseur):
    monkeypatch.setenv("LLM_FOURNISSEUR", fournisseur)
    monkeypatch.setenv("OPENAI_API_KEY", "cle-test")
    monkeypatch.setenv("GEMINI_API_KEY", "cle-test")
    donnees = json.dumps(ATTENDU[GARAGE]["facture"])
    recues = []

    def serveur(requete):
        corps = json.loads(requete.content)
        recues.append(corps)
        if fournisseur == "openai":
            return httpx.Response(200, json={"choices": [{"message": {"content": donnees}}], "usage": {"prompt_tokens": 1712, "completion_tokens": 288}})
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": donnees}]}}], "usageMetadata": {"promptTokenCount": 1712, "candidatesTokenCount": 288}})

    resultat = extraire_images([b"\x89PNG-page-1", b"\x89PNG-page-2"], httpx.Client(transport=httpx.MockTransport(serveur)))

    assert resultat.facture.numero_facture == "F26-1193"
    assert resultat.jetons == {"entree": 1712, "sortie": 288}
    assert resultat.pages_images == 2
    assert resultat.consigne.usage == "extraction-image"
    envoye = json.dumps(recues[0])
    assert base64.b64encode(b"\x89PNG-page-2").decode() in envoye  # les deux pages sont parties
    assert "images de ses pages" in envoye


# ───────── Dans le circuit ─────────


@pytest.fixture
def fabrique(connexion):
    return lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")


def application(fabrique, tmp_path, lecteur, cles=None):
    return TestClient(
        creer_application(
            fabrique_session=fabrique, extracteur=lambda texte: (_ for _ in ()).throw(AssertionError("pas de texte à lire")),
            extracteur_images=lecteur, dossier_fichiers=tmp_path, traiter_tout_de_suite=True, odoo=None, cles_mail=cles or [],
        )
    )


def test_une_photo_deposee_est_lue_sur_image(fabrique, tmp_path):
    lecteur = FauxLecteurImages()

    reponse = application(fabrique, tmp_path, lecteur).post("/factures", files={"fichier": ("IMG_2041.jpg", photo(), "image/jpeg")})

    facture = reponse.json()
    assert reponse.status_code == 201
    assert facture["nom_fichier"] == "IMG_2041.pdf"
    assert facture["etat"] == "a_valider"
    lecture = next(e for e in facture["evenements"] if e["type"] == "EXTRACTION")["detail"]
    assert (lecture["source"], lecture["pages_lues"], lecture["jetons"]) == ("ia-image", 1, {"entree": 1500, "sortie": 300})
    assert len(lecteur.appels) == 1


def test_par_mail_la_photo_jointe_est_lue_et_le_logo_ignore(fabrique, tmp_path):
    cle = Ed25519PrivateKey.generate()
    client = application(fabrique, tmp_path, FauxLecteurImages(), [cle.public_key()])
    message = EmailMessage()
    message["From"], message["Subject"], message["Message-ID"] = "compta@garage-bertin.fr", "Facture", "<photo@garage>"
    message.set_content("Voici la facture prise en photo.")
    message.add_attachment(photo(), maintype="image", subtype="jpeg", filename="facture.jpg")
    message.add_attachment(photo(120, 40, "PNG", bruit=False), maintype="image", subtype="png", filename="logo.png")
    brut = message.as_bytes()
    horodatage = str(int(time.time()))

    pieces = client.post(
        "/reception/mail", content=brut, headers={"X-DocuFlow-Horodatage": horodatage, "X-DocuFlow-Signature": signer(cle, horodatage, brut)}
    ).json()["pieces"]

    resultats = {p["nom"]: p for p in pieces}
    assert resultats["facture.jpg"]["resultat"] == "facture"
    assert resultats["logo.png"]["resultat"] == "ignoree"
    assert "logo" in resultats["logo.png"]["raison"]


def test_iban_et_tva_sont_ranges_sans_espace():
    """Sur une image, l'IA garde parfois les espaces imprimés : le code les retire toujours."""
    facture = Facture.model_validate(
        {**ATTENDU[GARAGE]["facture"], "fournisseur_tva": "fr52 529874315", "fournisseur_iban": "FR76 1820 6004 0065 0001 2398 765"}
    )

    assert (facture.fournisseur_tva, facture.fournisseur_iban) == ("FR52529874315", "FR7618206004006500012398765")
