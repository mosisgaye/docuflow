"""L'éditeur de circuit : le brouillon, qu'on modifie sans rien changer aux factures.

Le circuit en service est la dernière version publiée (moteur/approbation.py). L'éditeur travaille
sur un brouillon unique : on l'enregistre autant de fois qu'on veut, on peut l'annuler, et seule la
publication (plus tard) en fait une nouvelle version. Tant qu'il n'est pas publié, aucune facture
ne le voit.

Sans brouillon, l'éditeur s'ouvre sur la version en service, réécrite en lignes (la forme de l'éditeur).
"""

from pydantic import ValidationError
from sqlalchemy.orm import Session

from moteur.approbation import LIBELLES, Regle, Relance, en_lignes, verifier_relances, version_en_vigueur
from moteur.base import BrouillonCircuit

REGLES_MAX = 50

# Sans aucune version publiée, le moteur demande une seule validation, celle du comptable : l'éditeur part de là.
REGLES_DE_DEPART = [{"nom": "Toute facture est approuvée par le comptable", "si": {"toujours": True}, "exige": ["comptable"]}]

TRADUCTIONS = {
    "missing": "information manquante",
    "extra_forbidden": "information inconnue",
    "literal_error": "valeur non permise",
    "too_short": "trop court ou vide",
    "too_long": "trop long",
    "greater_than_equal": "valeur trop petite",
    "less_than_equal": "valeur trop grande",
    "int_parsing": "un nombre entier est attendu",
    "int_type": "un nombre entier est attendu",
    "dict_type": "une liste de réglages est attendue",
    "string_type": "un texte est attendu",
    "list_type": "une liste est attendue",
    "bool_type": "vrai ou faux est attendu",
}


class BrouillonInvalide(ValueError):
    """Un brouillon refusé : le message dit, en français, ce qui ne va pas et où."""


def _message(erreur: ValidationError | ValueError, ou: str) -> str:
    if not isinstance(erreur, ValidationError):
        return f"{ou} : {erreur}"
    premiere = erreur.errors()[0]
    # Les positions se comptent à partir de 1, comme à l'écran (« lignes › 1 » est la première ligne).
    chemin = " › ".join(str(partie + 1) if isinstance(partie, int) else str(partie) for partie in premiere["loc"] if partie != "function-after")
    texte = premiere["msg"].removeprefix("Value error, ") if premiere["type"] == "value_error" else TRADUCTIONS.get(premiere["type"], premiere["msg"])
    return f"{ou}{f' ({chemin})' if chemin else ''} : {texte}"


def _en_lignes(regles: list[dict]) -> list[dict]:
    return [{**regle, "si": en_lignes(regle["si"])} for regle in regles]


def verifier(regles: list[dict], relances: dict | None) -> tuple[list[dict], dict | None]:
    """Les règles et les relances vérifiées, ou BrouillonInvalide avec un message clair."""
    if not isinstance(regles, list) or not 1 <= len(regles) <= REGLES_MAX:
        raise BrouillonInvalide(f"Le circuit compte de 1 à {REGLES_MAX} règles.")
    verifiees = []
    for numero, regle in enumerate(regles, start=1):
        try:
            verifiees.append(Regle.model_validate(regle).model_dump(mode="json", exclude_none=True))
        except ValidationError as erreur:
            nom = regle.get("nom") if isinstance(regle, dict) else None
            raise BrouillonInvalide(_message(erreur, f"Règle {numero}{f' « {nom} »' if nom else ''}")) from erreur
    if isinstance(relances, dict):
        for niveau, reglage in relances.items():
            if niveau in LIBELLES:
                try:
                    Relance.model_validate(reglage)
                except ValidationError as erreur:
                    raise BrouillonInvalide(_message(erreur, f"Relances du {LIBELLES[niveau].lower()}")) from erreur
    try:
        relances_verifiees = verifier_relances(relances)
    except ValueError as erreur:
        raise BrouillonInvalide(_message(erreur, "Relances")) from erreur
    return verifiees, relances_verifiees


def en_service(session: Session) -> dict:
    """La version en service, telle que l'éditeur l'affiche."""
    version = version_en_vigueur(session)
    if version is None:
        return {"version": None, "regles": _en_lignes(REGLES_DE_DEPART), "relances": None}
    return {"version": version.version, "regles": _en_lignes(version.regles), "relances": version.relances}


def lire(session: Session) -> dict:
    """Le brouillon s'il existe, sinon la version en service. « modifie » dit lequel des deux."""
    service = en_service(session)
    brouillon = session.get(BrouillonCircuit, 1)
    if brouillon is None:
        return {**service, "version_en_service": service["version"], "modifie": False, "modifie_par": None, "modifie_le": None}
    return {
        "version_en_service": service["version"],
        "regles": _en_lignes(brouillon.regles),
        "relances": brouillon.relances,
        "modifie": True,
        "modifie_par": brouillon.modifie_par,
        "modifie_le": brouillon.modifie_le,
    }


def enregistrer(session: Session, regles: list[dict], relances: dict | None, auteur: str) -> dict:
    """Vérifie puis enregistre le brouillon (le remplace s'il existe). Ne touche à aucune facture."""
    verifiees, relances_verifiees = verifier(regles, relances)
    brouillon = session.get(BrouillonCircuit, 1)
    if brouillon is None:
        brouillon = BrouillonCircuit(id=1, regles=verifiees, relances=relances_verifiees, modifie_par=auteur)
        session.add(brouillon)
    else:
        brouillon.regles, brouillon.relances, brouillon.modifie_par = verifiees, relances_verifiees, auteur
    session.flush()
    session.refresh(brouillon)
    return lire(session)


def annuler(session: Session) -> dict:
    """Jette le brouillon : l'éditeur revient à la version en service. Sans brouillon, ne fait rien."""
    brouillon = session.get(BrouillonCircuit, 1)
    if brouillon is not None:
        session.delete(brouillon)
        session.flush()
    return lire(session)
