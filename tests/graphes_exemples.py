"""Des circuits en graphe pour les tests de l'éditeur (pas un fichier de tests : rien n'y est collecté)."""

DEBUT = {"id": "debut", "type": "debut", "x": 0, "y": 0, "nom": "Début"}
FIN = {"id": "fin", "type": "fin", "x": 1000, "y": 0, "nom": "Enregistrer dans Odoo"}
IBAN = {"lignes": [{"champ": "anomalie", "comparaison": "une_de", "valeur": ["IBAN_DIFFERENT", "IBAN_NOUVEAU"]}], "combinaison": "une"}


def seuil(valeur: str) -> dict:
    return {"lignes": [{"champ": "total_ttc", "comparaison": "superieur_a", "valeur": valeur}], "combinaison": "une"}


def circuit_simple(montant: str = "1000", nom_seuil: str = "Plus de 1 000 €") -> dict:
    """Début → Comptable → Montant > seuil ? oui → Directeur financier → Odoo ; non → Odoo."""
    return {
        "noeuds": [
            DEBUT,
            {"id": "compta", "type": "approbation", "x": 250, "y": 0, "nom": "Comptable", "niveau": "comptable"},
            {"id": "seuil", "type": "condition", "x": 500, "y": 0, "nom": nom_seuil, "si": seuil(montant)},
            {"id": "dfi", "type": "approbation", "x": 750, "y": 150, "nom": "Directeur financier", "niveau": "directeur_financier"},
            FIN,
        ],
        "liens": [
            {"de": "debut", "vers": "compta", "sortie": None},
            {"de": "compta", "vers": "seuil", "sortie": None},
            {"de": "seuil", "vers": "dfi", "sortie": "oui"},
            {"de": "seuil", "vers": "fin", "sortie": "non"},
            {"de": "dfi", "vers": "fin", "sortie": None},
        ],
    }


def tout_au_gerant() -> dict:
    """Début → Comptable → Gérant → Odoo, pour toutes les factures."""
    return {
        "noeuds": [
            DEBUT,
            {"id": "compta", "type": "approbation", "x": 250, "y": 0, "nom": "Comptable", "niveau": "comptable"},
            {"id": "gerant", "type": "approbation", "x": 500, "y": 0, "nom": "Gérant", "niveau": "gerant"},
            FIN,
        ],
        "liens": [
            {"de": "debut", "vers": "compta", "sortie": None},
            {"de": "compta", "vers": "gerant", "sortie": None},
            {"de": "gerant", "vers": "fin", "sortie": None},
        ],
    }


def avec_blocage_iban(base: dict) -> dict:
    """Le même circuit, avec un blocage si l'IBAN a changé, juste après le Début."""
    premier = next(lien["vers"] for lien in base["liens"] if lien["de"] == "debut")
    return {
        "noeuds": [
            *base["noeuds"],
            {"id": "iban", "type": "condition", "x": 120, "y": -150, "nom": "IBAN changé", "si": IBAN},
            {"id": "stop", "type": "blocage", "x": 250, "y": -300, "nom": "IBAN à vérifier", "message": "Appelez le fournisseur."},
        ],
        "liens": [
            *[lien for lien in base["liens"] if lien["de"] != "debut"],
            {"de": "debut", "vers": "iban", "sortie": None},
            {"de": "iban", "vers": "stop", "sortie": "oui"},
            {"de": "iban", "vers": premier, "sortie": "non"},
        ],
    }
