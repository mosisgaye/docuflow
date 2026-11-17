"""L'éditeur de circuit : le brouillon, qu'on modifie sans rien changer aux factures.

Le circuit en service est la dernière version publiée (moteur/approbation.py). L'éditeur travaille
sur un brouillon unique : on l'enregistre autant de fois qu'on veut, on peut l'annuler, et seule la
publication en fait une nouvelle version. Tant qu'il n'est pas publié, aucune facture
ne le voit.

Sans brouillon, l'éditeur s'ouvre sur la version en service, réécrite en lignes (la forme de l'éditeur).
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from moteur.approbation import (
    LIBELLES,
    NIVEAUX,
    RELANCES_DEFAUT,
    Regle,
    Relance,
    circuit,
    en_lignes,
    niveau_attendu,
    publier,
    verifier_relances,
    version_en_vigueur,
)
from moteur.base import BrouillonCircuit, Etat, Evenement, FactureEnBase, ReglesApprobation
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


# ───────── Tester le brouillon sur une facture déjà reçue (rien n'est écrit) ─────────


class TestImpossible(ValueError):
    """La facture ne peut pas servir de test (pas encore lue)."""


def _niveaux(calcule: dict) -> list[str]:
    return [n["niveau"] for n in calcule["niveaux"]]


def tester(session: Session, facture: FactureEnBase) -> dict:
    """Le chemin que prendrait cette facture avec le brouillon (ou la version en service s'il n'y en a pas).

    Lecture seule : rien n'est écrit, ni sur la facture, ni dans le journal. Le calcul est celui du
    moteur (approbation.circuit), sur les données et les anomalies que la facture a déjà.
    """
    if facture.donnees is None:
        raise TestImpossible("Cette facture n'est pas encore lue : elle ne peut pas servir de test.")
    brouillon = lire(session)
    donnees, anomalies = facture.donnees, facture.anomalies or []
    codes = {a["code"] for a in anomalies}
    libelles = {a["code"]: a["libelle"] for a in ANOMALIES}
    arretee = any(a.get("gravite") == "bloquante" for a in anomalies)

    regles = []
    for brute in brouillon["regles"]:
        regle = Regle.model_validate(brute)
        lignes = [{"texte": _ligne(l.model_dump(mode="json")), "vraie": l.vraie(donnees, codes)} for l in regle.si.lignes or []]
        regles.append({
            "nom": regle.nom,
            "condition": resume_condition(brute["si"]),
            "lignes": lignes,
            "vraie": regle.si.vraie(donnees, anomalies),
            "effet": resume_regle(brute).removeprefix(resume_condition(brute["si"]) + ", "),
        })

    essai = SimpleNamespace(version="brouillon", regles=brouillon["regles"], relances=brouillon["relances"])
    calcule = circuit(donnees, anomalies, essai)
    service = circuit(donnees, anomalies, version_en_vigueur(session))
    if arretee:
        bloquantes = ", ".join(libelles.get(a["code"], a["code"]).lower() for a in anomalies if a.get("gravite") == "bloquante")
        calcule = {**calcule, "niveaux": [], "bloque": f"Arrêtée aux contrôles ({bloquantes}) : à corriger ou rejeter."}
        service = {**service, "niveaux": [], "bloque": calcule["bloque"]}

    relances = {n: (brouillon["relances"] or {}).get(n) or RELANCES_DEFAUT for n in _niveaux(calcule)}
    return {
        "facture": {
            "id": str(facture.id),
            "fournisseur": donnees.get("fournisseur_nom"),
            "numero": donnees.get("numero_facture"),
            "total_ttc": donnees.get("total_ttc"),
        },
        "circuit_teste": "brouillon" if brouillon["modifie"] else "en_service",
        "controles": {
            "arretee": arretee,
            "anomalies": [{"code": a["code"], "libelle": libelles.get(a["code"], a["code"]), "gravite": a.get("gravite")} for a in anomalies],
        },
        "regles": regles,
        "niveaux": calcule["niveaux"],
        "bloque": calcule["bloque"],
        "relances": relances,
        "en_service": {"version": service["version"], "niveaux": _niveaux(service), "bloque": service["bloque"]},
        "change": (_niveaux(calcule), calcule["bloque"]) != (_niveaux(service), service["bloque"]),
    }


# ───────── Les versions publiées, et le chemin suivi par les dernières factures ─────────


def versions(session: Session) -> list[dict]:
    """Toutes les versions publiées, de la plus récente à la plus ancienne. La première est en service."""
    toutes = session.scalars(select(ReglesApprobation).order_by(ReglesApprobation.version.desc())).all()
    return [
        {
            "version": v.version,
            "en_service": rang == 0,
            "publie_par": v.publie_par,
            "publie_le": v.publie_le,
            "nombre_regles": len(v.regles),
            "changements": v.changements,  # None : publiée avant l'éditeur
            "relances_reglees": bool(v.relances),
        }
        for rang, v in enumerate(toutes)
    ]


EXECUTIONS_MAX = 100

RESULTATS = {
    Etat.RECUE.value: "En lecture",
    Etat.EXTRAITE.value: "En contrôle",
    Etat.A_VALIDER.value: "En attente",
    Etat.EN_APPROBATION.value: "En attente",
    Etat.EN_ANOMALIE.value: "Arrêtée aux contrôles",
    Etat.VALIDEE.value: "Validée",
    Etat.REJETEE.value: "Rejetée",
    Etat.EXPORTEE.value: "Envoyée au logiciel",
    Etat.ECHEC.value: "Lecture impossible",
}
TERMINES = {Etat.VALIDEE.value, Etat.REJETEE.value, Etat.EXPORTEE.value, Etat.EN_ANOMALIE.value, Etat.ECHEC.value}


def _etape(evenement: Evenement) -> str | None:
    """Une étape du chemin, en quelques mots, lue dans le journal. None : pas une étape du chemin."""
    detail = evenement.detail or {}
    if evenement.type == "RECEPTION":
        return "Reçue"
    if evenement.type == "EXTRACTION":
        return "Lue"
    if evenement.type in ("EXTRACTION_ECHOUEE", "LECTURE_IMPOSSIBLE"):
        return "Lecture impossible"
    if evenement.type == "CONTROLE":
        return "Contrôles : arrêtée" if evenement.etat == Etat.EN_ANOMALIE.value else "Contrôles"
    if evenement.type in ("APPROBATION", "VALIDATION") and detail.get("libelle"):
        return f"{detail['libelle']} ✓ ({evenement.auteur})"
    if evenement.type == "VALIDATION":
        return f"Validée ({evenement.auteur})"
    if evenement.type == "NOTIFICATION" and detail.get("rappel"):
        return f"Relance : {LIBELLES.get(detail.get('niveau'), detail.get('niveau'))}"
    if evenement.type == "REJET":
        return f"Rejetée ({evenement.auteur})"
    if evenement.type == "EXPORT":
        return "Envoyée au logiciel"
    return None


def executions(session: Session, limite: int = 20, maintenant: datetime | None = None) -> list[dict]:
    """Le chemin réellement suivi par les dernières factures, lu dans le journal (rien n'est calculé de nouveau)."""
    maintenant = maintenant or datetime.now(UTC)
    # À égalité de date de création (même transaction), l'heure exacte du premier événement départage.
    premier = select(func.min(Evenement.cree_le)).where(Evenement.facture_id == FactureEnBase.id).scalar_subquery()
    factures = session.scalars(
        select(FactureEnBase)
        .options(selectinload(FactureEnBase.evenements))
        .order_by(FactureEnBase.cree_le.desc(), premier.desc().nulls_last())
        .limit(min(max(limite, 1), EXECUTIONS_MAX))
    ).all()
    lignes = []
    for facture in factures:
        evenements = list(facture.evenements)
        chemin = [etape for etape in (_etape(e) for e in evenements) if etape]
        en_cours = facture.etat not in TERMINES
        fin = maintenant if en_cours or not evenements else evenements[-1].cree_le
        debut = evenements[0].cree_le if evenements else facture.cree_le
        attendu = niveau_attendu(session, facture) if facture.etat in (Etat.A_VALIDER.value, Etat.EN_APPROBATION.value) else None
        resultat = RESULTATS.get(facture.etat, facture.etat)
        if attendu:
            resultat = f"En attente : {LIBELLES[attendu].lower()}"
        donnees = facture.donnees or {}
        lignes.append({
            "facture_id": str(facture.id),
            "fournisseur": donnees.get("fournisseur_nom"),
            "numero": donnees.get("numero_facture"),
            "total_ttc": donnees.get("total_ttc"),
            "etat": facture.etat,
            "version_circuit": (facture.circuit or {}).get("version"),
            "chemin": chemin,
            "resultat": resultat,
            "en_cours": en_cours,
            "duree_s": max(int((fin - debut).total_seconds()), 0),
            "recue_le": facture.cree_le,
        })
    return lignes
