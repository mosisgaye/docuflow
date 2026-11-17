"""L'éditeur de circuit : le brouillon, qu'on modifie sans rien changer aux factures.

Le circuit en service est la dernière version publiée (moteur/approbation.py). L'éditeur travaille
sur un brouillon unique : on l'enregistre autant de fois qu'on veut, on peut l'annuler, et seule la
publication en fait une nouvelle version. Tant qu'il n'est pas publié, aucune facture
ne le voit.

Le circuit se dessine en graphe, comme dans n8n (moteur/graphe_circuit.py). Sans brouillon, l'éditeur
s'ouvre sur la version en service ; une version d'avant (en règles) y est convertie sans changer de sens.
"""

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from moteur.approbation import (
    LIBELLES,
    NIVEAUX,
    RELANCES_DEFAUT,
    Relance,
    en_lignes,
    niveau_attendu,
    publier,
    verifier_relances,
    version_en_vigueur,
)
from moteur.base import BrouillonCircuit, Etat, Evenement, FactureEnBase, ReglesApprobation
from moteur.catalogue_circuit import ANOMALIES, CHAMPS, COMPARAISONS
from moteur.graphe_circuit import GrapheInvalide, depuis_regles, parcourir, verifier_esquisse
from moteur.graphe_circuit import verifier as verifier_graphe

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


def _graphe_de_regles(regles: list[dict]) -> dict:
    return depuis_regles([{**regle, "si": en_lignes(regle["si"])} for regle in regles])


def _graphe_de_version(version: ReglesApprobation | None) -> dict:
    if version is None:
        return _graphe_de_regles(REGLES_DE_DEPART)
    return version.graphe or _graphe_de_regles(version.regles)


def verifier(graphe: dict, relances: dict | None) -> tuple[dict, dict | None]:
    """Le graphe et les relances vérifiés, ou BrouillonInvalide avec un message clair.

    Le graphe peut être incomplet (une étape pas encore reliée) : le brouillon le garde quand même,
    comme n8n garde un workflow inachevé. Seule la publication exige un circuit complet.
    """
    if not isinstance(graphe, dict):
        raise BrouillonInvalide("Le circuit est un graphe : des étapes et des liens.")
    try:
        esquisse, _ = verifier_esquisse(graphe)
    except GrapheInvalide as erreur:
        raise BrouillonInvalide(str(erreur)) from erreur
    verifie = esquisse.model_dump(mode="json", exclude_none=True)
    for lien in verifie["liens"]:
        lien.setdefault("sortie", None)  # toujours présente : l'écran reconnaît chaque lien par (étape, sortie)
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
    return verifie, relances_verifiees


def en_service(session: Session) -> dict:
    """La version en service, en graphe (les versions d'avant sont converties, sans changer leur sens)."""
    version = version_en_vigueur(session)
    return {"version": version.version if version else None, "graphe": _graphe_de_version(version), "relances": version.relances if version else None}


def lire(session: Session) -> dict:
    """Le brouillon s'il existe, sinon la version en service. « modifie » dit lequel des deux."""
    service = en_service(session)
    brouillon = session.get(BrouillonCircuit, 1)
    if brouillon is None:
        return {**service, "version_en_service": service["version"], "modifie": False, "modifie_par": None, "modifie_le": None, "a_completer": None}
    graphe = brouillon.graphe or _graphe_de_regles(brouillon.regles)
    return {
        "version_en_service": service["version"],
        "graphe": graphe,
        "a_completer": verifier_esquisse(graphe)[1],  # ce qui manque pour publier ; None : complet
        "relances": brouillon.relances,
        "modifie": True,
        "modifie_par": brouillon.modifie_par,
        "modifie_le": brouillon.modifie_le,
    }


def enregistrer(session: Session, graphe: dict, relances: dict | None, auteur: str) -> dict:
    """Vérifie puis enregistre le brouillon (le remplace s'il existe). Ne touche à aucune facture."""
    verifie, relances_verifiees = verifier(graphe, relances)
    brouillon = session.get(BrouillonCircuit, 1)
    if brouillon is None:
        brouillon = BrouillonCircuit(id=1, regles=[], graphe=verifie, relances=relances_verifiees, modifie_par=auteur)
        session.add(brouillon)
    else:
        brouillon.regles, brouillon.graphe, brouillon.relances, brouillon.modifie_par = [], verifie, relances_verifiees, auteur
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


def nom_etape(noeud: dict) -> str:
    return (noeud.get("nom") or "").strip() or {"debut": "Début", "fin": "Enregistrer dans Odoo", "condition": "Condition", "blocage": "Blocage"}.get(
        noeud["type"], LIBELLES.get(noeud.get("niveau") or "", "Approbation")
    )


def resume_etape(noeud: dict) -> str:
    """Ce que fait une étape, en une phrase."""
    if noeud["type"] == "condition":
        return f"si {resume_condition(noeud['si'])}"
    if noeud["type"] == "approbation":
        return f"approbation du {LIBELLES[noeud['niveau']].lower()}"
    if noeud["type"] == "blocage":
        return f"bloque : {noeud['message']}"
    return nom_etape(noeud)


def _resume_relance(reglage: dict) -> str:
    return f"relance après {reglage['delai_h']} h ({reglage['delai_urgent_h']} h si l'échéance approche), {reglage['maximum']} au plus"


def _comparable_condition(condition: dict) -> dict:
    """Une condition sous une forme où deux écritures du même sens sont égales."""
    si = en_lignes(condition)
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
    return si


def _sens(noeud: dict) -> dict:
    """Ce qui compte dans une étape : son type et ses réglages, pas sa position à l'écran."""
    sens = {cle: noeud.get(cle) for cle in ("type", "nom", "niveau", "message")}
    if noeud.get("si") is not None:
        sens["si"] = _comparable_condition(noeud["si"])
    return sens


def comparer(avant: dict, apres: dict) -> list[dict]:
    """Ce qui change d'un circuit à l'autre : étapes ajoutées, retirées, modifiées, liens, relances.

    Les étapes se retrouvent par leur identifiant ; déplacer une étape à l'écran n'est pas un changement.
    """
    changements: list[dict] = []
    anciennes = {n["id"]: n for n in avant["graphe"]["noeuds"]}
    nouvelles = {n["id"]: n for n in apres["graphe"]["noeuds"]}
    for identifiant, noeud in anciennes.items():
        if identifiant not in nouvelles:
            changements.append({"genre": "retrait", "etape": identifiant, "avant": resume_etape(noeud), "apres": None, "texte": f"Étape retirée : {nom_etape(noeud)}."})
    for identifiant, noeud in nouvelles.items():
        if identifiant not in anciennes:
            changements.append({"genre": "ajout", "etape": identifiant, "avant": None, "apres": resume_etape(noeud), "texte": f"Étape ajoutée : {nom_etape(noeud)} ({resume_etape(noeud)})."})
        elif _sens(noeud) != _sens(anciennes[identifiant]):
            ancien, nouveau = resume_etape(anciennes[identifiant]), resume_etape(noeud)
            texte = f"{nom_etape(noeud)} : {ancien} → {nouveau}." if ancien != nouveau else f"{nom_etape(anciennes[identifiant])} s'appelle maintenant « {nom_etape(noeud)} »."
            changements.append({"genre": "modification", "etape": identifiant, "avant": ancien, "apres": nouveau, "texte": texte})

    def suites(graphe: dict) -> dict:
        return {(lien["de"], lien.get("sortie")): lien["vers"] for lien in graphe["liens"]}

    noms = {**{i: nom_etape(n) for i, n in anciennes.items()}, **{i: nom_etape(n) for i, n in nouvelles.items()}}
    avant_liens, apres_liens = suites(avant["graphe"]), suites(apres["graphe"])
    for (de, sortie), vers in apres_liens.items():
        if de in anciennes and avant_liens.get((de, sortie)) not in (None, vers):
            branche = f" (sortie {sortie.capitalize()})" if sortie else ""
            texte = f"Après « {noms[de]} »{branche}, la facture va maintenant vers « {noms[vers]} » au lieu de « {noms[avant_liens[(de, sortie)]]} »."
            changements.append({"genre": "lien", "etape": de, "avant": noms[avant_liens[(de, sortie)]], "apres": noms[vers], "texte": texte})

    for niveau in NIVEAUX:
        ancien = (avant.get("relances") or {}).get(niveau) or RELANCES_DEFAUT
        nouveau = (apres.get("relances") or {}).get(niveau) or RELANCES_DEFAUT
        if ancien != nouveau:
            texte = f"Relances du {LIBELLES[niveau].lower()} : {_resume_relance(ancien)} → {_resume_relance(nouveau)}."
            changements.append({"genre": "relances", "etape": None, "niveau": niveau, "avant": _resume_relance(ancien), "apres": _resume_relance(nouveau), "texte": texte})
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
    graphe = brouillon.graphe or _graphe_de_regles(brouillon.regles)
    manque = verifier_esquisse(graphe)[1]
    if manque:
        raise PublicationImpossible(f"Le circuit est incomplet : {manque}")
    changements = comparer(en_service(session), {"graphe": graphe, "relances": brouillon.relances})
    if not changements:
        raise PublicationImpossible("Le brouillon est identique à la version en service : rien à publier.")
    version = publier(session, [], auteur, brouillon.relances, [c["texte"] for c in changements], graphe=graphe)
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

    Lecture seule : rien n'est écrit, ni sur la facture, ni dans le journal. Le parcours est celui du
    moteur (graphe_circuit.parcourir), sur les données et les anomalies que la facture a déjà.
    """
    if facture.donnees is None:
        raise TestImpossible("Cette facture n'est pas encore lue : elle ne peut pas servir de test.")
    brouillon = lire(session)
    donnees, anomalies = facture.donnees, facture.anomalies or []
    codes = {a["code"] for a in anomalies}
    libelles = {a["code"]: a["libelle"] for a in ANOMALIES}
    arretee = any(a.get("gravite") == "bloquante" for a in anomalies)

    if brouillon.get("a_completer"):
        raise TestImpossible(f"Le circuit est incomplet : {brouillon['a_completer']}")
    graphe = verifier_graphe(brouillon["graphe"])
    parcours = parcourir(graphe, donnees, anomalies)
    service_version = version_en_vigueur(session)
    service = parcourir(verifier_graphe(_graphe_de_version(service_version)), donnees, anomalies)

    conditions = []
    for etape in parcours["chemin"]:
        noeud = graphe.noeud(etape["id"])
        if noeud.type == "condition":
            lignes = [{"texte": _ligne(l.model_dump(mode="json")), "vraie": l.vraie(donnees, codes)} for l in noeud.si.lignes or []]
            conditions.append({"id": noeud.id, "nom": nom_etape(noeud.model_dump()), "vraie": etape["sortie"] == "oui", "lignes": lignes})

    chemin, bloque, niveaux = parcours["chemin"], parcours["bloque"], parcours["niveaux"]
    if arretee:  # une anomalie bloquante arrête la facture avant le circuit
        bloquantes = ", ".join(libelles.get(a["code"], a["code"]).lower() for a in anomalies if a.get("gravite") == "bloquante")
        bloque, niveaux, chemin, conditions = f"Arrêtée aux contrôles ({bloquantes}) : à corriger ou rejeter.", [], [], []

    relances = {n["niveau"]: (brouillon["relances"] or {}).get(n["niveau"]) or RELANCES_DEFAUT for n in niveaux}
    a_niveaux = lambda r: [n["niveau"] for n in r["niveaux"]]  # noqa: E731
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
        "chemin": chemin,
        "conditions": conditions,
        "niveaux": niveaux,
        "bloque": bloque,
        "relances": relances,
        "en_service": {"version": service_version.version if service_version else None, "niveaux": [] if arretee else a_niveaux(service), "bloque": bloque if arretee else service["bloque"]},
        "change": not arretee and (a_niveaux(parcours), parcours["bloque"]) != (a_niveaux(service), service["bloque"]),
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
            "nombre_etapes": len(v.graphe["noeuds"]) if v.graphe else None,
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
