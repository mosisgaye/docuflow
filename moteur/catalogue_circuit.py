"""Le catalogue de l'éditeur de circuit : ce qu'on peut régler, décrit en données.

L'écran de réglage se construit à partir de ce catalogue (aucun champ n'y est écrit en dur) :
ajouter un champ ou une comparaison ici, et dans le langage des règles (moteur/approbation.py),
suffit à le rendre réglable. Les tests vérifient que les deux disent la même chose.
"""

from moteur.approbation import LIBELLES, NIVEAUX, RELANCES_DEFAUT, Relance

COMPARAISONS = {
    "superieur_a": "supérieur à",
    "superieur_ou_egal_a": "supérieur ou égal à",
    "inferieur_a": "inférieur à",
    "inferieur_ou_egal_a": "inférieur ou égal à",
    "egal_a": "égal à",
    "different_de": "différent de",
    "contient": "contient",
    "une_de": "une de",
    "aucune_de": "aucune de",
}

CHAMPS = [
    {"champ": "total_ttc", "libelle": "Montant TTC", "genre": "montant", "comparaisons": ["superieur_a", "superieur_ou_egal_a", "inferieur_a", "inferieur_ou_egal_a", "egal_a"]},
    {"champ": "total_ht", "libelle": "Montant HT", "genre": "montant", "comparaisons": ["superieur_a", "superieur_ou_egal_a", "inferieur_a", "inferieur_ou_egal_a", "egal_a"]},
    {"champ": "fournisseur_nom", "libelle": "Nom du fournisseur", "genre": "texte", "comparaisons": ["egal_a", "different_de", "contient"]},
    {"champ": "fournisseur_siret", "libelle": "SIRET du fournisseur", "genre": "texte", "comparaisons": ["egal_a", "different_de"]},
    {"champ": "anomalie", "libelle": "Anomalie", "genre": "anomalies", "comparaisons": ["une_de", "aucune_de"]},
]

# Chaque anomalie que les contrôles savent détecter. Les bloquantes arrêtent la facture avant le
# circuit (elle passe « en anomalie ») : elles ne servent donc à rien dans une condition.
ANOMALIES = [
    {"code": "IBAN_DIFFERENT", "libelle": "IBAN différent de celui connu", "gravite": "avertissement"},
    {"code": "IBAN_NOUVEAU", "libelle": "IBAN jamais vu pour ce fournisseur", "gravite": "avertissement"},
    {"code": "ECART_COMMANDE", "libelle": "Écart avec le bon de commande", "gravite": "avertissement"},
    {"code": "SANS_COMMANDE", "libelle": "Achat sans bon de commande", "gravite": "avertissement"},
    {"code": "FOURNISSEUR_INCONNU", "libelle": "Fournisseur inconnu dans Odoo", "gravite": "avertissement"},
    {"code": "TAUX_TVA_INCONNU", "libelle": "Taux de TVA inhabituel", "gravite": "avertissement"},
    {"code": "DATE_FUTURE", "libelle": "Facture datée dans le futur", "gravite": "avertissement"},
    {"code": "CHAMP_MANQUANT", "libelle": "Information obligatoire absente", "gravite": "bloquante"},
    {"code": "AUCUNE_LIGNE", "libelle": "Aucune ligne de facture", "gravite": "bloquante"},
    {"code": "LIGNE_INCOHERENTE", "libelle": "Ligne mal calculée", "gravite": "bloquante"},
    {"code": "TOTAL_HT_INCOHERENT", "libelle": "Total HT mal calculé", "gravite": "bloquante"},
    {"code": "TOTAL_TTC_INCOHERENT", "libelle": "Total TTC mal calculé", "gravite": "bloquante"},
    {"code": "TVA_INCOHERENTE", "libelle": "TVA mal calculée", "gravite": "bloquante"},
    {"code": "SIRET_INVALIDE", "libelle": "SIRET invalide", "gravite": "bloquante"},
    {"code": "TVA_INTRACOM_INVALIDE", "libelle": "Numéro de TVA invalide", "gravite": "bloquante"},
    {"code": "TVA_SIRET_DIFFERENTS", "libelle": "Numéro de TVA et SIRET qui ne correspondent pas", "gravite": "bloquante"},
    {"code": "IBAN_INVALIDE", "libelle": "IBAN invalide", "gravite": "bloquante"},
    {"code": "ECHEANCE_AVANT_FACTURE", "libelle": "Échéance antérieure à la facture", "gravite": "bloquante"},
    {"code": "DOUBLON_FACTURE", "libelle": "Facture déjà reçue (doublon)", "gravite": "bloquante"},
]

RELANCES = [
    {"nom": "delai_h", "libelle": "Relancer après", "unite": "heures"},
    {"nom": "delai_urgent_h", "libelle": "Si l'échéance approche, relancer après", "unite": "heures"},
    {"nom": "maximum", "libelle": "Relances au plus", "unite": "relances"},
]

# Les types d'étapes du graphe. Début et Odoo sont fixes (un seul de chaque, ni ajout ni retrait) ;
# les autres s'ajoutent depuis la palette. « disponible : False » : annoncés, pas encore exécutés.
ETAPES = [
    {"type": "debut", "libelle": "Début", "description": "Réception, lecture IA et contrôles", "fixe": True},
    {"type": "condition", "libelle": "Condition", "description": "Deux chemins : Oui et Non", "fixe": False, "disponible": True},
    {"type": "approbation", "libelle": "Approbation", "description": "Une personne de l'équipe approuve", "fixe": False, "disponible": True},
    {"type": "blocage", "libelle": "Blocage", "description": "Arrête la facture tant que le problème n'est pas réglé", "fixe": False, "disponible": True},
    {"type": "prevenir", "libelle": "Prévenir par mail", "description": "Informer quelqu'un, sans lui demander d'agir", "fixe": False, "disponible": False},
    {"type": "envoyer", "libelle": "Envoyer à un logiciel", "description": "Événement signé vers votre outil", "fixe": False, "disponible": False},
    {"type": "attendre", "libelle": "Attendre", "description": "Jusqu'à une date, par exemple avant l'échéance", "fixe": False, "disponible": False},
    {"type": "fin", "libelle": "Enregistrer dans Odoo", "description": "Facture fournisseur et PDF", "fixe": True},
]


def _bornes(nom: str) -> dict:
    bornes = {}
    for contrainte in Relance.model_fields[nom].metadata:
        if hasattr(contrainte, "ge"):
            bornes["min"] = contrainte.ge
        if hasattr(contrainte, "le"):
            bornes["max"] = contrainte.le
    return bornes


def catalogue() -> dict:
    """Tout ce que l'éditeur peut proposer, en données (libellés en français)."""
    return {
        "champs": [{**champ, "comparaisons": [{"code": c, "libelle": COMPARAISONS[c]} for c in champ["comparaisons"]]} for champ in CHAMPS],
        "anomalies": [{**anomalie, "utilisable": anomalie["gravite"] == "avertissement"} for anomalie in ANOMALIES],
        "niveaux": [{"code": niveau, "libelle": LIBELLES[niveau]} for niveau in NIVEAUX],
        "relances": [{**reglage, **_bornes(reglage["nom"]), "defaut": RELANCES_DEFAUT[reglage["nom"]]} for reglage in RELANCES],
        "etapes": ETAPES,
    }
