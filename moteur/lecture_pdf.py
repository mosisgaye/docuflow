"""Lecture du texte d'un PDF, sur place, sans service distant.

Un PDF produit par un logiciel contient du vrai texte : on le lit directement.
Un scan ou une photo n'en contient pas : il faudra un lecteur d'images (OCR).
"""

import hashlib
import io
from dataclasses import dataclass

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
