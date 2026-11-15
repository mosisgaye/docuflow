"""Fabrique le dossier de démonstration guidée : une facture par fonctionnalité.

    uv run python -m outils.generer_demo

Écrit dans demo/ des factures NEUVES (numéros jamais reçus), pour que chacune soit vraiment
lue et contrôlée pendant la démonstration. Leurs bons de commande sont ajoutés à l'Odoo de
démonstration par outils/odoo_remplir.py (relançable).

Toutes les sociétés sont fictives, sauf l'entreprise cliente (fictive aussi) : Transports Lemaire SAS.
Nécessite Google Chrome (impression en PDF sans interface).
"""

import io
import pathlib
import subprocess
import tempfile

import pypdfium2

from outils.generer_factures import CLIENT, IBAN_FRAUDE, calculer, html, joindre_facturx, cii_xml
from outils.generer_scans import scanner

DEMO = pathlib.Path(__file__).resolve().parent.parent / "demo"

ATELIER = ("Atelier Numérique du Midi SARL", "14 rue des Tanneurs, 34000 Montpellier", "81234567600017", "FR19812345676")
PAPETERIE = ("Papeterie Durand & Fils", "8 avenue de la Gare, 69003 Lyon", "40322198900045", "FR28403221989")
GARAGE = ("Garage Central Bertin", "52 route de Paris, 45000 Orléans", "52987431500029", "FR52529874315")
IMPRIMERIE = ("Imprimerie Lumière SAS", "6 rue des Arts, 31000 Toulouse", "73815042400039", "FR66738150424")
# Un fournisseur qui n'existe pas dans Odoo. SIRET fictif mais valide (clés du SIREN et du SIRET justes).
INCONNU = ("Nettoyage Pro Services SARL", "3 impasse des Lilas, 30000 Nîmes", "88214567500014", "FR05882145675")

# « commande » : un bon de commande existe dans Odoo pour cette facture ; « ecart » : le prix commandé diffère.
# « rendu » : pdf (texte), facturx (XML joint), scan (image sans texte), photo (JPEG).
MODELES_DEMO = [
    {
        "fichier": "01-facture-simple.pdf", "style": "classique", "numero": "2026-11-140", "date": "2026-11-14", "echeance": "2026-12-14",
        "fournisseur": PAPETERIE, "lignes": [("Ramettes papier A4 80 g", "30", "4.90"), ("Classeurs à levier", "20", "3.20")],
        "commande": True,
    },
    {
        "fichier": "02-deux-niveaux.pdf", "style": "bleu", "numero": "FA-2026-0520", "date": "2026-11-14", "echeance": "2026-12-14",
        "fournisseur": ATELIER, "lignes": [("Maintenance applicative (jours)", "4", "450.00"), ("Hébergement serveur, décembre 2026", "1", "120.00")],
        "commande": True,
    },
    {
        "fichier": "03-trois-niveaux.pdf", "style": "bleu", "numero": "FA-2026-0521", "date": "2026-11-14", "echeance": "2026-12-31",
        "fournisseur": ATELIER, "lignes": [("Développement du module de réservation (jours)", "12", "450.00"), ("Formation des utilisateurs (demi-journée)", "2", "250.00")],
        "commande": True,
    },
    {
        # Fraude au changement d'IBAN, avec une échéance très proche pour presser le paiement.
        "fichier": "04-fraude-iban.pdf", "style": "rouge", "numero": "F26-1302", "date": "2026-11-14", "echeance": "2026-11-17",
        "fournisseur": GARAGE, "lignes": [("Vidange et filtre à huile", "1", "145.00"), ("Main-d'œuvre (heures)", "1.5", "62.00")],
        "commande": True, "iban": IBAN_FRAUDE,
        "mention_paiement": "Important : nous avons changé de banque. Merci de régler cette facture urgente sur nos nouvelles coordonnées.",
    },
    {
        "fichier": "05-ecart-commande.pdf", "style": "rouge", "numero": "F26-1303", "date": "2026-11-14", "echeance": "2026-12-14",
        "fournisseur": GARAGE, "lignes": [("Pneus été 205/55 R16 (lot de 4)", "1", "460.00"), ("Montage et équilibrage", "1", "60.00")],
        "commande": True, "ecart": {"Pneus été 205/55 R16 (lot de 4)": "420.00"},
    },
    {
        # Le total TTC imprimé (391 €) ne correspond pas aux lignes (342 €) : la facture ne peut pas être validée.
        "fichier": "06-erreur-de-calcul.pdf", "style": "classique", "numero": "2026-11-141", "date": "2026-11-14", "echeance": "2026-12-14",
        "fournisseur": PAPETERIE, "lignes": [("Cartouches toner noir", "4", "62.00"), ("Enveloppes C4 (boîte de 250)", "2", "18.50")],
        "commande": True, "ttc_imprime": "391.00",
    },
    {
        # Même numéro que la facture 01, renvoyée sous une autre forme : un doublon à ne pas payer deux fois.
        "fichier": "07-doublon.pdf", "style": "bleu", "numero": "2026-11-140", "date": "2026-11-14", "echeance": "2026-12-14",
        "fournisseur": PAPETERIE, "lignes": [("Ramettes papier A4 80 g", "30", "4.90"), ("Classeurs à levier", "20", "3.20")],
        "commande": False,
    },
    {
        "fichier": "08-facture-electronique-facturx.pdf", "style": "bleu", "numero": "FX-2026-0091", "date": "2026-11-14", "echeance": "2026-12-14",
        "fournisseur": IMPRIMERIE, "lignes": [("Flyers A5 quadri (lot de 1000)", "2", "86.00"), ("Affiches A2 (lot de 50)", "1", "145.00")],
        "commande": True, "rendu": "facturx",
    },
    {
        "fichier": "09-facture-scannee.pdf", "style": "bleu", "numero": "FA-2026-0522", "date": "2026-11-15", "echeance": "2026-12-15",
        "fournisseur": ATELIER, "lignes": [("Licence logiciel de suivi", "4", "89.50"), ("Hébergement serveur, janvier 2027", "1", "120.00")],
        "commande": True, "rendu": "scan",
    },
    {
        "fichier": "10-photo-telephone.jpg", "style": "classique", "numero": "2026-11-142", "date": "2026-11-15", "echeance": "2026-12-15",
        "fournisseur": PAPETERIE, "lignes": [("Stylos bille bleus (lot de 50)", "4", "12.00"), ("Post-it 76 x 76 (lot de 12)", "5", "9.80")],
        "commande": True, "rendu": "photo",
    },
    {
        "fichier": "11-fournisseur-inconnu.pdf", "style": "classique", "numero": "NPS-2026-077", "date": "2026-11-15", "echeance": "2026-12-15",
        "fournisseur": INCONNU, "lignes": [("Nettoyage des locaux, novembre 2026", "1", "680.00"), ("Vitrerie (forfait)", "1", "120.00")],
        "commande": False,
    },
    {
        # À envoyer par MAIL à depot@factures.moussagaye.com, pour montrer la réception automatique.
        "fichier": "12-a-envoyer-par-mail.pdf", "style": "bleu", "numero": "FX-2026-0092", "date": "2026-11-15", "echeance": "2026-12-15",
        "fournisseur": IMPRIMERIE, "lignes": [("Cartes de visite (boîte de 500)", "6", "24.50"), ("Kakémono 85 x 200", "1", "139.00")],
        "commande": True,
    },
]
for _modele in MODELES_DEMO:
    _modele.setdefault("client", CLIENT)
    _modele.setdefault("anomalies", [])


def _imprimer(modele: dict, dossier: pathlib.Path) -> bytes:
    page = dossier / "facture.html"
    page.write_text(html(modele, calculer(modele)), encoding="utf-8")
    sortie = dossier / "facture.pdf"
    subprocess.run(
        ["google-chrome", "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={sortie}", page.as_uri()],
        check=True, capture_output=True,
    )
    return sortie.read_bytes()


def _photo(pdf: bytes) -> bytes:
    """Une « photo » de la page : légèrement de travers, en JPEG, comme prise au téléphone."""
    image = pypdfium2.PdfDocument(pdf)[0].render(scale=170 / 72).to_pil().convert("RGB")
    image = image.rotate(-2.2, expand=True, fillcolor=(236, 233, 226))
    tampon = io.BytesIO()
    image.save(tampon, "JPEG", quality=82)
    return tampon.getvalue()


def main() -> None:
    DEMO.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temporaire:
        dossier = pathlib.Path(temporaire)
        for modele in MODELES_DEMO:
            pdf = _imprimer(modele, dossier)
            rendu = modele.get("rendu", "pdf")
            if rendu == "facturx":
                contenu = joindre_facturx(pdf, cii_xml(modele, calculer(modele)))
            elif rendu == "scan":
                contenu = scanner(pdf)
            elif rendu == "photo":
                contenu = _photo(pdf)
            else:
                contenu = pdf
            (DEMO / modele["fichier"]).write_bytes(contenu)
            print(f"{modele['fichier']:38} {calculer(modele)['total_ttc']:>9} € TTC  ({rendu})")


if __name__ == "__main__":
    main()
