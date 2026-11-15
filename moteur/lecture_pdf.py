"""Lecture du texte d'un PDF, sur place, sans service distant.

Un PDF produit par un logiciel contient du vrai texte : on le lit directement.
Un scan ou une photo n'en contient pas : on transforme alors ses pages en images, que l'IA lit.
Une photo (JPEG, PNG, WebP) est d'abord mise dans un PDF : tout le reste du circuit est le même.
"""

import hashlib
import io
from dataclasses import dataclass

import pypdfium2
from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfReader

# En dessous de ce nombre de caractères par page, on considère que le PDF
# est une image (scan) et qu'il n'y a pas de texte exploitable.
SEUIL_CARACTERES_PAR_PAGE = 40


@dataclass(frozen=True)
class TexteLu:
    texte: str
    nb_pages: int
    empreinte: str  # SHA-256 du fichier : sert à reconnaître un document déjà traité

    @property
    def a_du_texte(self) -> bool:
        utiles = sum(1 for c in self.texte if not c.isspace())
        return utiles >= SEUIL_CARACTERES_PAR_PAGE * max(self.nb_pages, 1)


def lire_pdf(contenu: bytes) -> TexteLu:
    """Renvoie le texte d'un PDF en gardant la disposition des colonnes."""
    lecteur = PdfReader(io.BytesIO(contenu))
    pages = [page.extract_text(extraction_mode="layout") or "" for page in lecteur.pages]
    return TexteLu(
        texte="\n\n".join(pages).strip(),
        nb_pages=len(pages),
        empreinte=hashlib.sha256(contenu).hexdigest(),
    )


PAGES_IMAGES_MAX = 3  # au-delà, une facture scannée n'est lue que sur ses 3 premières pages
# 200 dpi : à 150, l'IA sautait parfois un « 0 » dans les longues suites de chiffres d'un IBAN scanné.
RESOLUTION_DPI = 200


def pages_en_images(contenu: bytes, pages_max: int = PAGES_IMAGES_MAX) -> list[bytes]:
    """Les premières pages du PDF, en images PNG en niveaux de gris, pour une lecture par l'IA."""
    document = pypdfium2.PdfDocument(contenu)
    try:
        images = []
        for rang in range(min(len(document), pages_max)):
            tampon = io.BytesIO()
            document[rang].render(scale=RESOLUTION_DPI / 72).to_pil().convert("L").save(tampon, "PNG", optimize=True)
            images.append(tampon.getvalue())
        return images
    finally:
        document.close()


def image_en_pdf(contenu: bytes) -> bytes | None:
    """Met une photo (JPEG, PNG, WebP…) dans un PDF d'une page. None si ce n'est pas une image.

    L'orientation enregistrée par le téléphone est appliquée : une photo prise en portrait
    ne se retrouve pas couchée.
    """
    try:
        image = Image.open(io.BytesIO(contenu))
        image.load()
    except (UnidentifiedImageError, OSError):
        return None
    image = ImageOps.exif_transpose(image).convert("RGB")
    tampon = io.BytesIO()
    image.save(tampon, "PDF", resolution=RESOLUTION_DPI)
    return tampon.getvalue()
