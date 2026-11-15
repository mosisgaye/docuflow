"""Fabrique des versions « scannées » des factures d'exemple, pour mesurer la lecture sur image.

    uv run python -m outils.generer_scans

Chaque facture de factures/ est rendue en image puis abîmée comme par un scanner de bureau
moyen : niveaux de gris, page penchée de 1,5°, grain, léger flou, compression JPEG. Le PDF
obtenu ne contient AUCUN texte : DocuFlow doit le lire sur l'image.
Les réponses attendues sont celles de factures/attendu.json (mêmes noms de fichiers).
"""

import io
import json
import pathlib

import pypdfium2
from PIL import Image, ImageFilter

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
SCANS = FACTURES / "scans"


def scanner(contenu: bytes) -> bytes:
    document = pypdfium2.PdfDocument(contenu)
    try:
        pages = []
        for page in document:
            image = page.render(scale=150 / 72).to_pil().convert("L")
            image = image.rotate(1.5, resample=Image.BICUBIC, expand=True, fillcolor=255)  # posée de travers
            grain = Image.effect_noise(image.size, 28).convert("L")  # poussière et grain du capteur
            image = Image.blend(image, grain, 0.12).filter(ImageFilter.GaussianBlur(0.6))
            tampon = io.BytesIO()
            image.save(tampon, "JPEG", quality=60)  # compression d'un scanner bas de gamme
            pages.append(Image.open(io.BytesIO(tampon.getvalue())))
    finally:
        document.close()
    sortie = io.BytesIO()
    pages[0].save(sortie, "PDF", resolution=150, save_all=True, append_images=pages[1:])
    return sortie.getvalue()


def main() -> None:
    SCANS.mkdir(exist_ok=True)
    for nom in json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8")):
        scan = scanner((FACTURES / nom).read_bytes())
        (SCANS / nom).write_bytes(scan)
        print(f"{nom:36} {len(scan) // 1024:4d} Ko")


if __name__ == "__main__":
    main()
