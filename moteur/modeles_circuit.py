"""Les modèles de circuit : des workflows prêts à l'emploi, que l'agent (ou la palette) pose dans le brouillon.

Un modèle est écrit en règles (lisibles, testées), puis converti en graphe par graphe_circuit.depuis_regles.
Les seuils se règlent à la création. Rien n'est publié : le modèle devient un brouillon, qu'une
personne vérifie et publie dans Workflow.
"""

from decimal import Decimal, InvalidOperation

from moteur.graphe_circuit import depuis_regles

COMPTABLE_TOUJOURS = {"nom": "Comptable", "si": {"toujours": True}, "exige": ["comptable"]}
IBAN = {"nom": "IBAN changé ?", "si": {"lignes": [{"champ": "anomalie", "comparaison": "une_de", "valeur": ["IBAN_DIFFERENT", "IBAN_NOUVEAU"]}], "combinaison": "une"}, "bloque": "IBAN à vérifier : appelez le fournisseur au numéro connu avant de payer."}
INCONNU = {"nom": "Fournisseur inconnu ?", "si": {"lignes": [{"champ": "anomalie", "comparaison": "une_de", "valeur": ["FOURNISSEUR_INCONNU"]}], "combinaison": "une"}, "bloque": "Créez d'abord le fournisseur dans Odoo."}
COMMANDE = {"nom": "Écart avec la commande ?", "si": {"lignes": [{"champ": "anomalie", "comparaison": "une_de", "valeur": ["ECART_COMMANDE", "SANS_COMMANDE"]}], "combinaison": "une"}, "exige": ["directeur_financier"]}


def _seuil(nom: str, montant: Decimal, niveau: str) -> dict:
    return {"nom": nom, "si": {"lignes": [{"champ": "total_ttc", "comparaison": "superieur_a", "valeur": str(montant)}], "combinaison": "une"}, "exige": [niveau]}


def _euros(montant: Decimal) -> str:
    return f"{montant:,.0f} €".replace(",", " ")


MODELES = {
    "classique": {
        "nom": "Classique par montant",
        "description": "Le comptable valide tout ; le directeur financier au-dessus d'un seuil ; le gérant au-dessus d'un second seuil.",
        "parametres": ["seuil_directeur_financier", "seuil_gerant"],
    },
    "anti_fraude": {
        "nom": "Anti-fraude IBAN",
        "description": "Un IBAN changé ou jamais vu bloque la facture tant que le fournisseur n'a pas été appelé ; sinon le comptable valide.",
        "parametres": [],
    },
    "fournisseur_inconnu": {
        "nom": "Fournisseur inconnu dans Odoo",
        "description": "Une facture d'un fournisseur absent d'Odoo est bloquée jusqu'à sa création ; sinon le comptable valide.",
        "parametres": [],
    },
    "commande": {
        "nom": "Rapprochement avec la commande",
        "description": "Le comptable valide tout ; un écart avec le bon de commande, ou un achat sans commande, passe aussi par le directeur financier.",
        "parametres": [],
    },
    "complet": {
        "nom": "Complet pour une PME",
        "description": "Anti-fraude IBAN et fournisseur inconnu d'abord, puis le comptable, le directeur financier (seuil ou écart de commande) et le gérant au-dessus d'un second seuil.",
        "parametres": ["seuil_directeur_financier", "seuil_gerant"],
    },
}

SEUILS_PAR_DEFAUT = {"seuil_directeur_financier": Decimal("1000"), "seuil_gerant": Decimal("5000")}


class ModeleInconnu(ValueError):
    """Le modèle demandé n'existe pas, ou ses seuils n'ont pas de sens."""


def lire_seuil(valeur, defaut: Decimal) -> Decimal:
    if valeur in (None, ""):
        return defaut
    try:
        montant = Decimal(str(valeur).replace(" ", "").replace("€", "").replace(",", "."))
    except InvalidOperation:
        raise ModeleInconnu(f"« {valeur} » n'est pas un montant.") from None
    if not montant.is_finite() or montant <= 0 or montant > 1_000_000_000:
        raise ModeleInconnu(f"« {valeur} » n'est pas un seuil possible.")
    return montant


def regles(code: str, seuil_directeur_financier=None, seuil_gerant=None) -> list[dict]:
    """Les règles du modèle, avec ses seuils."""
    if code not in MODELES:
        raise ModeleInconnu(f"Modèle inconnu : {code}. Modèles : {', '.join(MODELES)}.")
    dfi = lire_seuil(seuil_directeur_financier, SEUILS_PAR_DEFAUT["seuil_directeur_financier"])
    gerant = lire_seuil(seuil_gerant, SEUILS_PAR_DEFAUT["seuil_gerant"])
    if code in ("classique", "complet") and gerant <= dfi:
        raise ModeleInconnu("Le seuil du gérant doit être plus haut que celui du directeur financier.")
    montant_dfi = _seuil(f"Plus de {_euros(dfi)} ?", dfi, "directeur_financier")
    montant_gerant = _seuil(f"Plus de {_euros(gerant)} ?", gerant, "gerant")
    return {
        "classique": [COMPTABLE_TOUJOURS, montant_dfi, montant_gerant],
        "anti_fraude": [IBAN, COMPTABLE_TOUJOURS],
        "fournisseur_inconnu": [INCONNU, COMPTABLE_TOUJOURS],
        "commande": [COMPTABLE_TOUJOURS, COMMANDE],
        "complet": [IBAN, INCONNU, COMPTABLE_TOUJOURS, montant_dfi, COMMANDE, montant_gerant],
    }[code]


def construire(code: str, seuil_directeur_financier=None, seuil_gerant=None) -> dict:
    """Le graphe du modèle, prêt à devenir un brouillon."""
    return depuis_regles(regles(code, seuil_directeur_financier, seuil_gerant))
