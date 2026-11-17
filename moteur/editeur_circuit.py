"""L'éditeur de circuit : le brouillon, qu'on modifie sans rien changer aux factures.

Le circuit en service est la dernière version publiée (moteur/approbation.py). L'éditeur travaille
sur un brouillon unique : on l'enregistre autant de fois qu'on veut, on peut l'annuler, et seule la
publication en fait une nouvelle version. Tant qu'il n'est pas publié, aucune facture
ne le voit.

Sans brouillon, l'éditeur s'ouvre sur la version en service, réécrite en lignes (la forme de l'éditeur).
"""

from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy.orm import Session

from moteur.approbation import (
    LIBELLES,
    NIVEAUX,
    RELANCES_DEFAUT,
    Regle,
    Relance,
    en_lignes,
    publier,
    verifier_relances,
    version_en_vigueur,
)
from moteur.base import BrouillonCircuit, ReglesApprobation
from moteur.catalogue_circuit import ANOMALIES, CHAMPS, COMPARAISONS

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


# ───────── En phrases : ce que dit une règle, et ce qui a changé ─────────


def _montant(valeur: str) -> str:
    """« 2500.50 » → « 2 500,50 € » ; « 1000 » → « 1 000 € »."""
    nombre = Decimal(valeur)
    texte = f"{nombre:,.2f}".replace(",", " ").replace(".", ",").removesuffix(",00")
    return f"{texte} €"


def _ligne(ligne: dict) -> str:
    champ = next(c for c in CHAMPS if c["champ"] == ligne["champ"])
    comparaison = COMPARAISONS[ligne["comparaison"]]
    if champ["genre"] == "montant":
        return f"{champ['libelle']} {comparaison} {_montant(ligne['valeur'])}"
    if champ["genre"] == "anomalies":
        libelles = {a["code"]: a["libelle"] for a in ANOMALIES}
        noms = " ou ".join(libelles.get(code, code) for code in ligne["valeur"])
        return f"{'Anomalie' if ligne['comparaison'] == 'une_de' else 'Aucune anomalie'} : {noms}"
    return f"{champ['libelle']} {comparaison} « {ligne['valeur']} »"


def resume_condition(condition: dict) -> str:
    """Une condition en français : « Montant TTC supérieur à 1 000 € ou Anomalie : IBAN différent… »."""
    condition = en_lignes(condition)
    if condition.get("toujours"):
        return "Toujours"
    lien = " et " if condition.get("combinaison") == "toutes" else " ou "
    return lien.join(_ligne(ligne) for ligne in condition["lignes"])


def resume_regle(regle: dict) -> str:
    effet = (
        f"bloque : {regle['bloque']}" if regle.get("bloque") else "exige " + ", ".join(LIBELLES[n].lower() for n in regle["exige"])
    )
    return f"{resume_condition(regle['si'])}, {effet}"


def _resume_relance(reglage: dict) -> str:
    return f"relance après {reglage['delai_h']} h ({reglage['delai_urgent_h']} h si l'échéance approche), {reglage['maximum']} au plus"


def _comparable(regle: dict) -> dict:
    """Une règle sous une forme où deux écritures du même sens sont égales (ancienne forme ou lignes)."""
    si = en_lignes(regle["si"])
    if "lignes" in si:
        lignes = []
        for ligne in si["lignes"]:
            valeur = ligne["valeur"]
            if ligne["champ"] in ("total_ttc", "total_ht"):
                valeur = format(Decimal(valeur).normalize(), "f")  # « 1000.00 » et « 1000 » sont le même seuil
            elif isinstance(valeur, list):
                valeur = sorted(valeur)  # l'ordre des anomalies ne change rien
            lignes.append({**ligne, "valeur": valeur})
        si = {**si, "lignes": lignes, "combinaison": si.get("combinaison") or "une"}
    return {**regle, "si": si}


def comparer(avant: dict, apres: dict) -> list[dict]:
    """Ce qui change d'un circuit (règles, relances) à l'autre, règle par règle (retrouvée par son nom)."""
    changements = []
    anciennes = {r["nom"]: _comparable(r) for r in avant["regles"]}
    nouvelles = {r["nom"]: _comparable(r) for r in apres["regles"]}
    for nom, regle in anciennes.items():
        if nom not in nouvelles:
            changements.append({"genre": "retrait", "regle": nom, "avant": resume_regle(regle), "apres": None, "texte": f"Règle retirée : {nom}."})
    for nom, regle in nouvelles.items():
        if nom not in anciennes:
            changements.append({"genre": "ajout", "regle": nom, "avant": None, "apres": resume_regle(regle), "texte": f"Règle ajoutée : {nom} ({resume_regle(regle)})."})
        elif regle != anciennes[nom]:
            ancien, nouveau = resume_regle(anciennes[nom]), resume_regle(regle)
            changements.append({"genre": "modification", "regle": nom, "avant": ancien, "apres": nouveau, "texte": f"{nom} : {ancien} → {nouveau}."})
    for niveau in NIVEAUX:
        ancien = (avant.get("relances") or {}).get(niveau) or RELANCES_DEFAUT
        nouveau = (apres.get("relances") or {}).get(niveau) or RELANCES_DEFAUT
        if ancien != nouveau:
            texte = f"Relances du {LIBELLES[niveau].lower()} : {_resume_relance(ancien)} → {_resume_relance(nouveau)}."
            changements.append({"genre": "relances", "regle": None, "niveau": niveau, "avant": _resume_relance(ancien), "apres": _resume_relance(nouveau), "texte": texte})
    return changements


def differences(session: Session) -> dict:
    """Ce que le brouillon change par rapport à la version en service."""
    service, brouillon = en_service(session), lire(session)
    return {"version_en_service": service["version"], "modifie": brouillon["modifie"], "changements": comparer(service, brouillon) if brouillon["modifie"] else []}


class PublicationImpossible(ValueError):
    """Rien à publier : pas de brouillon, ou un brouillon identique à la version en service."""


def publier_brouillon(session: Session, auteur: str) -> ReglesApprobation:
    """Fait du brouillon la version suivante, avec la liste de ce qu'elle change, puis le jette.

    Les factures déjà en cours gardent leur version ; seules les suivantes prennent la nouvelle.
    """
    brouillon = session.get(BrouillonCircuit, 1, with_for_update=True)  # deux publications à la fois : l'une attend l'autre
    if brouillon is None:
        raise PublicationImpossible("Aucune modification à publier.")
    changements = comparer(en_service(session), {"regles": brouillon.regles, "relances": brouillon.relances})
    if not changements:
        raise PublicationImpossible("Le brouillon est identique à la version en service : rien à publier.")
    version = publier(session, brouillon.regles, auteur, brouillon.relances, [c["texte"] for c in changements])
    session.delete(brouillon)
    session.flush()
    return version
