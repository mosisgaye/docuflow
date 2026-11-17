"""Le workflow d'approbation : qui doit approuver une facture, dans quel ordre, et pourquoi.

Les règles sont écrites dans un petit langage contrôlé (jamais du code libre), et publiées par
versions : une version publiée ne change plus ; modifier les règles publie la version suivante.
Une facture garde la version avec laquelle son circuit a été calculé.

Une règle :
    {"nom": "...", "si": <condition>, "exige": ["directeur_financier"]}     ajoute des niveaux
    {"nom": "...", "si": <condition>, "bloque": "message"}                   empêche toute approbation
Une condition :
    {"toujours": true}
    {"champ": "total_ttc", "superieur_a": "1000"}      champs : total_ttc, total_ht
    {"anomalie": ["ECART_COMMANDE", "SANS_COMMANDE"]}  au moins une de ces anomalies
    {"lignes": [<ligne>, ...], "combinaison": "une" | "toutes"}   la forme de l'éditeur
Une ligne : {"champ": ..., "comparaison": ..., "valeur": ...}
    montants (total_ttc, total_ht) : superieur_a, superieur_ou_egal_a, inferieur_a, inferieur_ou_egal_a, egal_a
    textes (fournisseur_nom, fournisseur_siret) : egal_a, different_de, contient
    anomalie (valeur = liste de codes) : une_de, aucune_de
    Une information absente de la facture ne remplit jamais une ligne.

Les garanties :
- les niveaux s'approuvent dans l'ordre (comptable, puis directeur financier, puis gérant) ;
- une même personne n'approuve jamais deux niveaux de la même facture (séparation des tâches) ;
- chaque approbation garde l'empreinte des données approuvées : si elles changent ensuite,
  l'approbation ne vaut plus et il faut approuver de nouveau.

Sans règles publiées, le circuit n'a qu'un niveau, le comptable : une seule validation suffit.
"""

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moteur.base import Approbation, FactureEnBase, ReglesApprobation

NIVEAUX = ["comptable", "directeur_financier", "gerant"]
LIBELLES = {"comptable": "Comptable", "directeur_financier": "Directeur financier", "gerant": "Gérant"}


class ApprobationRefusee(Exception):
    """L'approbation demandée n'est pas permise (mauvais ordre, même personne, facture bloquée…)."""


# ───────── Le langage des règles ─────────


CHAMPS_MONTANT = ("total_ttc", "total_ht")
CHAMPS_TEXTE = ("fournisseur_nom", "fournisseur_siret")
COMPARAISONS_MONTANT = ("superieur_a", "superieur_ou_egal_a", "inferieur_a", "inferieur_ou_egal_a", "egal_a")
COMPARAISONS_TEXTE = ("egal_a", "different_de", "contient")
COMPARAISONS_ANOMALIE = ("une_de", "aucune_de")
CODE_ANOMALIE = re.compile(r"^[A-Z][A-Z_]{2,39}$")


def _texte(valeur) -> str:
    """Un texte comparable : sans espaces superflus ni différence de casse (« 552 100 554 » = « 552100554 » pour un SIRET)."""
    return " ".join(str(valeur).split()).casefold()


class Ligne(BaseModel):
    """Une ligne de condition : un champ de la facture, une comparaison, une valeur."""

    model_config = ConfigDict(extra="forbid")

    champ: Literal["total_ttc", "total_ht", "fournisseur_nom", "fournisseur_siret", "anomalie"]
    comparaison: Literal["superieur_a", "superieur_ou_egal_a", "inferieur_a", "inferieur_ou_egal_a", "egal_a", "different_de", "contient", "une_de", "aucune_de"]
    valeur: str | list[str]

    @model_validator(mode="after")
    def coherente(self):
        if self.champ in CHAMPS_MONTANT:
            if self.comparaison not in COMPARAISONS_MONTANT:
                raise ValueError(f"Un montant se compare avec : {', '.join(COMPARAISONS_MONTANT)}.")
            if not isinstance(self.valeur, str):
                raise ValueError("Un montant se compare à un seul nombre.")
            try:
                montant = Decimal(self.valeur.replace(" ", "").replace(",", "."))
            except InvalidOperation:
                raise ValueError(f"« {self.valeur} » n'est pas un montant.") from None
            if not montant.is_finite() or montant < 0:
                raise ValueError(f"« {self.valeur} » n'est pas un montant.")
            self.valeur = str(montant)
        elif self.champ in CHAMPS_TEXTE:
            if self.comparaison not in COMPARAISONS_TEXTE:
                raise ValueError(f"Un texte se compare avec : {', '.join(COMPARAISONS_TEXTE)}.")
            if not isinstance(self.valeur, str) or not self.valeur.strip() or len(self.valeur) > 200:
                raise ValueError("Un texte se compare à une valeur non vide (200 caractères au plus).")
        else:
            if self.comparaison not in COMPARAISONS_ANOMALIE:
                raise ValueError(f"Les anomalies se comparent avec : {', '.join(COMPARAISONS_ANOMALIE)}.")
            if not isinstance(self.valeur, list) or not 1 <= len(self.valeur) <= 30 or not all(CODE_ANOMALIE.match(code) for code in self.valeur):
                raise ValueError("Les anomalies se donnent en liste de codes, par exemple [\"IBAN_DIFFERENT\"].")
        return self

    def vraie(self, donnees: dict, codes: set[str]) -> bool:
        if self.champ == "anomalie":
            presente = bool(codes & set(self.valeur))
            return presente if self.comparaison == "une_de" else not presente
        brute = donnees.get(self.champ)
        if brute is None or brute == "":
            return False  # une information absente ne remplit jamais une condition
        if self.champ in CHAMPS_MONTANT:
            try:
                valeur, seuil = Decimal(str(brute)), Decimal(self.valeur)
            except InvalidOperation:
                return False
            return {
                "superieur_a": valeur > seuil,
                "superieur_ou_egal_a": valeur >= seuil,
                "inferieur_a": valeur < seuil,
                "inferieur_ou_egal_a": valeur <= seuil,
                "egal_a": valeur == seuil,
            }[self.comparaison]
        valeur, attendu = _texte(brute), _texte(self.valeur)
        if self.champ == "fournisseur_siret":
            valeur, attendu = valeur.replace(" ", ""), attendu.replace(" ", "")
        return {"egal_a": valeur == attendu, "different_de": valeur != attendu, "contient": attendu in valeur}[self.comparaison]


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    toujours: bool | None = None
    champ: Literal["total_ttc", "total_ht"] | None = None
    superieur_a: Decimal | None = None
    anomalie: list[str] | None = None
    lignes: list[Ligne] | None = Field(default=None, min_length=1, max_length=20)
    combinaison: Literal["une", "toutes"] | None = None

    @model_validator(mode="after")
    def une_seule_forme(self):
        formes = [self.toujours is True, self.champ is not None, self.anomalie is not None, self.lignes is not None]
        if sum(formes) != 1:
            raise ValueError("Une condition est « toujours », un champ comparé à un seuil, une liste d'anomalies, ou des lignes.")
        if (self.champ is None) != (self.superieur_a is None):
            raise ValueError("Un champ se compare toujours à un seuil (superieur_a).")
        if self.combinaison is not None and self.lignes is None:
            raise ValueError("La combinaison (une ou toutes) ne s'emploie qu'avec des lignes.")
        return self

    def vraie(self, donnees: dict, anomalies: list[dict]) -> bool:
        if self.toujours:
            return True
        if self.champ is not None:
            valeur = donnees.get(self.champ)
            return valeur is not None and Decimal(str(valeur)) > self.superieur_a
        codes = {anomalie["code"] for anomalie in anomalies}
        if self.lignes is not None:
            resultats = (ligne.vraie(donnees, codes) for ligne in self.lignes)
            return all(resultats) if self.combinaison == "toutes" else any(resultats)
        return bool(codes & set(self.anomalie or []))


def en_lignes(condition: dict) -> dict:
    """Réécrit une condition de l'ancienne forme en lignes, sans changer ce qu'elle veut dire.

    Sert à l'éditeur : une version publiée avant les lignes s'ouvre et se modifie comme les autres.
    """
    forme = Condition.model_validate(condition)
    if forme.champ is not None:
        return {"lignes": [{"champ": forme.champ, "comparaison": "superieur_a", "valeur": str(forme.superieur_a)}], "combinaison": "une"}
    if forme.anomalie is not None:
        return {"lignes": [{"champ": "anomalie", "comparaison": "une_de", "valeur": list(forme.anomalie)}], "combinaison": "une"}
    return forme.model_dump(mode="json", exclude_none=True)


class Regle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nom: str = Field(min_length=1, max_length=200)
    si: Condition
    exige: list[Literal["comptable", "directeur_financier", "gerant"]] | None = None
    bloque: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def un_effet(self):
        if (self.exige is None) == (self.bloque is None):
            raise ValueError("Une règle exige des niveaux, ou bloque : l'un des deux, pas les deux.")
        return self


class Relance(BaseModel):
    """Quand relancer un niveau qui n'a pas répondu. Les délais sont en heures."""

    model_config = ConfigDict(extra="forbid")

    delai_h: int = Field(ge=1, le=336)  # sans réponse depuis ce délai : relancer
    delai_urgent_h: int = Field(ge=1, le=336)  # le délai quand l'échéance de paiement approche
    maximum: int = Field(ge=0, le=5)  # relances au plus, par personne (0 : jamais)

    @model_validator(mode="after")
    def urgent_plus_court(self):
        if self.delai_urgent_h > self.delai_h:
            raise ValueError("Le délai quand l'échéance approche ne peut pas dépasser le délai normal.")
        return self


RELANCES_DEFAUT = {"delai_h": 48, "delai_urgent_h": 24, "maximum": 2}


def verifier_relances(relances: dict | None) -> dict | None:
    """Les relances par niveau, vérifiées. Un niveau absent garde les délais par défaut."""
    if relances is None:
        return None
    if not isinstance(relances, dict):
        raise ValueError("Les relances se donnent par niveau : {\"comptable\": {...}}.")
    inconnus = set(relances) - set(NIVEAUX)
    if inconnus:
        raise ValueError(f"Niveau inconnu dans les relances : {', '.join(sorted(inconnus))}.")
    return {niveau: Relance.model_validate(relances[niveau]).model_dump() for niveau in NIVEAUX if niveau in relances}


REGLES_DEMO = [
    {"nom": "Toute facture est approuvée par le comptable", "si": {"toujours": True}, "exige": ["comptable"]},
    {"nom": "Plus de 1 000 € TTC", "si": {"champ": "total_ttc", "superieur_a": "1000"}, "exige": ["directeur_financier"]},
    {"nom": "Plus de 5 000 € TTC", "si": {"champ": "total_ttc", "superieur_a": "5000"}, "exige": ["gerant"]},
    {"nom": "Écart avec le bon de commande, ou achat sans commande", "si": {"anomalie": ["ECART_COMMANDE", "SANS_COMMANDE"]}, "exige": ["directeur_financier"]},
    {"nom": "IBAN différent de celui connu, ou jamais vu", "si": {"anomalie": ["IBAN_DIFFERENT", "IBAN_NOUVEAU"]}, "exige": ["directeur_financier"]},
    {"nom": "Fournisseur inconnu dans Odoo", "si": {"anomalie": ["FOURNISSEUR_INCONNU"]}, "bloque": "Créez d'abord le fournisseur dans Odoo."},
]


def publier(session: Session, regles: list[dict], auteur: str, relances: dict | None = None) -> ReglesApprobation:
    """Publie une nouvelle version des règles (et des relances), après les avoir vérifiées. Les anciennes restent."""
    verifiees = [Regle.model_validate(regle).model_dump(mode="json", exclude_none=True) for regle in regles]
    relances_verifiees = verifier_relances(relances)
    suivante = (session.scalar(select(func.max(ReglesApprobation.version))) or 0) + 1
    version = ReglesApprobation(version=suivante, regles=verifiees, relances=relances_verifiees, publie_par=auteur)
    session.add(version)
    session.flush()
    return version


def version_en_vigueur(session: Session) -> ReglesApprobation | None:
    return session.scalars(select(ReglesApprobation).order_by(ReglesApprobation.version.desc()).limit(1)).first()


# ───────── Le circuit d'une facture ─────────


def circuit(donnees: dict, anomalies: list[dict], version: ReglesApprobation | None) -> dict:
    """Les niveaux d'approbation exigés pour cette facture, dans l'ordre, avec la règle qui les impose."""
    if version is None:
        return {"version": None, "niveaux": [{"niveau": "comptable", "raisons": ["Validation simple : aucune règle publiée"]}], "bloque": None}
    raisons: dict[str, list[str]] = {}
    bloque = None
    for regle in (Regle.model_validate(brute) for brute in version.regles):
        if not regle.si.vraie(donnees, anomalies):
            continue
        if regle.bloque:
            bloque = bloque or f"{regle.nom} : {regle.bloque}"
        for niveau in regle.exige or []:
            raisons.setdefault(niveau, []).append(regle.nom)
    niveaux = [{"niveau": niveau, "raisons": raisons[niveau]} for niveau in NIVEAUX if niveau in raisons]
    calcule = {"version": version.version, "niveaux": niveaux or [{"niveau": "comptable", "raisons": ["Aucune règle ne s'applique"]}], "bloque": bloque}
    if version.relances:
        calcule["relances"] = version.relances  # figées avec le circuit, comme les niveaux
    return calcule


def empreinte(donnees: dict | None) -> str:
    """Empreinte stable des données d'une facture : la « photo » de ce qui est approuvé."""
    return hashlib.sha256(json.dumps(donnees or {}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def approbations_valides(session: Session, facture: FactureEnBase) -> list[Approbation]:
    """Les approbations encore valables : celles faites sur les données actuelles de la facture."""
    actuelle = empreinte(facture.donnees)
    return [
        a for a in session.scalars(select(Approbation).where(Approbation.facture_id == facture.id).order_by(Approbation.cree_le))
        if a.empreinte_donnees == actuelle
    ]


def niveau_attendu(session: Session, facture: FactureEnBase) -> str | None:
    """Le prochain niveau qui doit approuver, ou None si tous l'ont fait."""
    faits = {a.niveau for a in approbations_valides(session, facture)}
    return next((n["niveau"] for n in (facture.circuit or circuit({}, [], None))["niveaux"] if n["niveau"] not in faits), None)


def approuver(session: Session, facture: FactureEnBase, personne: str) -> tuple[Approbation, bool]:
    """Enregistre l'approbation du niveau attendu par cette personne. Renvoie (approbation, circuit terminé)."""
    regle_du_circuit = facture.circuit or circuit({}, [], None)
    if regle_du_circuit.get("bloque"):
        raise ApprobationRefusee(f"Approbation impossible. {regle_du_circuit['bloque']}")
    niveau = niveau_attendu(session, facture)
    if niveau is None:
        raise ApprobationRefusee("Tous les niveaux ont déjà approuvé cette facture.")
    valides = approbations_valides(session, facture)
    deja = next((a for a in valides if a.personne.strip().lower() == personne.strip().lower()), None)
    if deja is not None:
        raise ApprobationRefusee(
            f"{personne} a déjà approuvé cette facture en tant que {LIBELLES[deja.niveau].lower()} : "
            f"le niveau {LIBELLES[niveau].lower()} doit être approuvé par une autre personne."
        )
    # Une approbation ancienne, faite sur d'autres données, est remplacée par la nouvelle.
    ancienne = session.scalars(select(Approbation).where(Approbation.facture_id == facture.id, Approbation.niveau == niveau)).first()
    if ancienne is not None:
        session.delete(ancienne)
        session.flush()
    approbation = Approbation(facture_id=facture.id, niveau=niveau, personne=personne, empreinte_donnees=empreinte(facture.donnees))
    session.add(approbation)
    session.flush()
    return approbation, niveau_attendu(session, facture) is None
