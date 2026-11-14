import pathlib

import pytest

from moteur.lecture_pdf import TexteLu, lire_pdf

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"


@pytest.mark.parametrize(
    ("fichier", "attendus"),
    [
        ("facture-FA-2026-0412.pdf", ["FA-2026-0412", "Atelier Numérique du Midi SARL", "3 166,20"]),
        ("facture-2026-11-087.pdf", ["2026-11-087", "Papeterie Durand & Fils", "777,60"]),
        ("facture-F26-1193.pdf", ["F26-1193", "Garage Central Bertin", "478,08"]),
    ],
)
def test_le_texte_des_factures_est_lu(fichier, attendus):
    lu = lire_pdf((FACTURES / fichier).read_bytes())

    assert lu.nb_pages == 1
    assert lu.a_du_texte
    for attendu in attendus:
        assert attendu in lu.texte.replace(" ", " ").replace("\xa0", " ")


def test_la_meme_facture_a_la_meme_empreinte():
    contenu = (FACTURES / "facture-F26-1193.pdf").read_bytes()

    assert lire_pdf(contenu).empreinte == lire_pdf(contenu).empreinte
    assert len(lire_pdf(contenu).empreinte) == 64


def test_deux_factures_ont_des_empreintes_differentes():
    a = lire_pdf((FACTURES / "facture-F26-1193.pdf").read_bytes())
    b = lire_pdf((FACTURES / "facture-2026-11-087.pdf").read_bytes())

    assert a.empreinte != b.empreinte


def test_un_pdf_sans_texte_est_signale():
    scan = TexteLu(texte="  \n ", nb_pages=1, empreinte="x")

    assert not scan.a_du_texte
