"""Remplit l'Odoo de démonstration : l'entreprise Transports Lemaire SAS et son activité.

    uv run python -m outils.odoo_remplir
    uv run python -m outils.odoo_remplir --nouvelle-cle   # renouveler la clé d'API de Verifac

Ce qu'il crée (relançable, rien n'est créé deux fois) :
- les fournisseurs des factures d'exemple (outils/generer_factures.py), avec SIRET, TVA,
  contact comptable et IBAN ;
- les produits achetés et des bons de commande confirmés : un exact pour la plupart des
  factures, un avec un écart de prix volontaire, et aucun pour un « achat sans commande » ;
- quelques clients et opportunités, côté CRM ;
- l'utilisateur technique « docuflow » et sa clé d'API, rangée dans donnees/odoo-cle-api
  (lisible par l'utilisateur seul, jamais affichée, jamais versionnée).

Les données sont fictives, sauf MD Plomberie (fournisseur réel, avec l'accord de son dirigeant).
"""

import json
import pathlib
import subprocess
import sys

from moteur.controles import cle_de_luhn_valide, siret_correct
from outils.generer_demo import MODELES_DEMO
from outils.generer_factures import CLIENT, IBANS, MODELES, iban_francais

RACINE = pathlib.Path(__file__).resolve().parent.parent
COMPOSE = ["docker", "compose", "-f", str(RACINE / "odoo" / "compose.yaml")]  # Compose charge odoo/.env tout seul
FICHIER_CLE = RACINE / "donnees" / "odoo-cle-api"

# Informations des fournisseurs absentes des factures : contact comptable et banque.
COMPLEMENTS = {
    "81234567600017": {"contact": ("Claire Fabre", "compta@atelier-numerique-midi.fr"), "banque": ("30004", "01234", "00012345678")},
    "40322198900045": {"contact": ("Henri Durand", "factures@papeterie-durand.fr"), "banque": ("10278", "07311", "00020184501")},
    "52987431500029": {"contact": ("Sylvie Bertin", "compta@garage-bertin.fr"), "banque": ("18206", "00400", "65000123987")},
    "73815042400039": {"contact": ("Paul Mercier", "facturation@imprimerie-lumiere.fr"), "banque": ("20041", "01005", "05123456K01")},
    # MD Plomberie : fournisseur réel. Pas de contact ni d'IBAN inventés à son nom.
    "90856344800012": {"note": "Fournisseur réel (spécimen de facture avec l'accord du dirigeant). Franchise en base de TVA, art. 293 B du CGI."},
}

# Bons de commande : ce que Transports Lemaire avait commandé. Une seule différence volontaire.
ECARTS = {"F26-1193": {"Plaquettes de frein avant": "85.00"}}  # devis à 85,00 €, facturé 98,40 €
SANS_COMMANDE = {"FA-2026-0431", "F26-1240"}  # achat sans commande, et la facture frauduleuse (jamais commandée)

# Factures de la démonstration guidée (demo/) : seulement celles d'un fournisseur connu, qui ont un bon de commande.
# Le doublon reprend le numéro de la 01 (sa commande existe déjà) ; le fournisseur inconnu n'est pas dans Odoo, exprès.
MODELES_COMMANDES_DEMO = [m for m in MODELES_DEMO if m["commande"] and m["fournisseur"][2] in COMPLEMENTS]
ECARTS.update({m["numero"]: m["ecart"] for m in MODELES_DEMO if m.get("ecart")})

SERVICES = ("Maintenance", "Hébergement", "Licence", "Main-d", "Formation", "Développement", "Déplacement", "Vidange", "Remplacement")

CLIENTS = [
    {
        "nom": "Vins des Costières SARL", "rue": "Route de Saint-Gilles", "code_postal": "30800", "ville": "Saint-Gilles",
        "contact": "Julie Roux", "fonction": "Responsable logistique", "email": "logistique@vins-costieres.fr",
        "opportunite": {"nom": "Transport des vendanges 2027", "montant": 48000, "probabilite": 60},
    },
    {
        "nom": "Coopérative Fruitière du Gard", "rue": "12 chemin des Vergers", "code_postal": "30230", "ville": "Bouillargues",
        "contact": "Marc Teissier", "fonction": "Directeur des achats", "email": "achats@coop-fruitiere-gard.fr",
        "opportunite": {"nom": "Tournées frigorifiques été 2027", "montant": 72500, "probabilite": 35},
    },
    {
        "nom": "Matériaux Lacroix SAS", "rue": "ZI de Grézan", "code_postal": "30000", "ville": "Nîmes",
        "contact": "Nadia Lacroix", "fonction": "Gérante", "email": "contact@materiaux-lacroix.fr",
        "opportunite": {"nom": "Contrat annuel livraisons chantiers", "montant": 126000, "probabilite": 80},
    },
]


def _completer_luhn(chiffres: str) -> str:
    """Ajoute le chiffre qui rend la clé de Luhn juste."""
    for dernier in "0123456789":
        if cle_de_luhn_valide(chiffres + dernier):
            return chiffres + dernier
    raise ValueError(chiffres)


def siret_fictif(rang: int) -> str:
    """Un SIRET fictif mais valide : clé du SIREN ET clé du SIRET justes (Odoo vérifie les deux)."""
    siren = _completer_luhn(f"8{rang:02d}44172")
    return _completer_luhn(siren + "0001")


def adresse(texte: str) -> tuple[str, str, str]:
    rue, _, reste = texte.rpartition(", ")
    code_postal, _, ville = reste.partition(" ")
    return rue, code_postal, ville


def donnees(nouvelle_cle: bool) -> dict:
    fournisseurs, produits, bons = {}, {}, []
    for modele in [*MODELES, *MODELES_COMMANDES_DEMO]:
        nom, adresse_texte, siret, tva = modele["fournisseur"]
        if modele["anomalies"] == ["SIRET_INVALIDE"]:
            siret = next(m["fournisseur"][2] for m in MODELES if m["fournisseur"][0] == nom and not m["anomalies"])  # le vrai SIRET
        complement = COMPLEMENTS[siret]
        rue, code_postal, ville = adresse(adresse_texte)
        fournisseurs[siret] = {
            "nom": nom, "rue": rue, "code_postal": code_postal, "ville": ville, "siret": siret, "tva": tva,
            "contact": {"nom": complement["contact"][0], "email": complement["contact"][1]} if "contact" in complement else None,
            "iban": IBANS.get(nom),  # le même que celui imprimé sur ses factures
            "note": complement.get("note"),
        }
        lignes = []
        for designation, quantite, prix in modele["lignes"]:
            code = f"DEMO-{siret[:9]}-{designation[:24]}"
            type_produit = "service" if designation.startswith(SERVICES) else "consu"
            # Fournisseur en franchise de TVA (art. 293 B) : ni ses produits ni ses commandes ne portent de TVA.
            sans_tva = bool(modele.get("franchise_tva"))
            produits[code] = {"code": code, "nom": designation, "type": type_produit, "prix": float(prix), "sans_tva": sans_tva}
            prix_commande = ECARTS.get(modele["numero"], {}).get(designation, prix)
            lignes.append({"code": code, "designation": designation, "quantite": quantite, "prix": prix_commande, "type": type_produit, "sans_tva": sans_tva})
        if modele["numero"] not in SANS_COMMANDE:
            note = "(écart de prix volontaire)" if modele["numero"] in ECARTS else ""
            bons.append({"facture": modele["numero"], "siret": siret, "date": modele["date"][:8] + "01", "lignes": lignes, "note": note})
    clients = [{**client, "siret": siret_fictif(rang)} for rang, client in enumerate(CLIENTS, 1)]
    return {
        "societe": CLIENT[0], "fournisseurs": list(fournisseurs.values()), "produits": list(produits.values()),
        "bons_de_commande": bons, "clients": clients, "nouvelle_cle": nouvelle_cle,
    }


def main() -> None:
    # --nouvelle-cle : révoque la clé de docuflow dans Odoo et en crée une autre (fichier réécrit).
    nouvelle_cle = not FICHIER_CLE.exists() or "--nouvelle-cle" in sys.argv[1:]
    script = f"DONNEES = {json.dumps(donnees(nouvelle_cle), ensure_ascii=False)!r}\nimport json\nDONNEES = json.loads(DONNEES)\n"
    script += (RACINE / "odoo" / "remplissage.py").read_text(encoding="utf-8")
    resultat = subprocess.run(
        [*COMPOSE, "exec", "-T", "odoo", "sh", "-c", 'odoo shell --db_host "$HOST" --db_user "$USER" --db_password "$PASSWORD" -d demo --no-http'],
        input=script, capture_output=True, text=True,
    )
    lignes = resultat.stdout.splitlines()
    for ligne in lignes:
        if ligne.startswith(">>"):
            print(ligne[3:])
    cle = next((ligne.removeprefix("CLE_API:") for ligne in lignes if ligne.startswith("CLE_API:")), None)
    if cle:
        FICHIER_CLE.parent.mkdir(parents=True, exist_ok=True)
        FICHIER_CLE.touch(mode=0o600)
        FICHIER_CLE.write_text(cle, encoding="utf-8")
        print(f"Clé d'API rangée dans {FICHIER_CLE.relative_to(RACINE)} (non affichée).")
    if resultat.returncode != 0 or not any(ligne == ">> terminé" for ligne in lignes):
        sys.exit("Le remplissage a échoué :\n" + "\n".join(l for l in resultat.stderr.splitlines()[-25:] if "CLE_API" not in l))


if __name__ == "__main__":
    main()
