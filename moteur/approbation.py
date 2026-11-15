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

Les garanties :
- les niveaux s'approuvent dans l'ordre (comptable, puis directeur financier, puis gérant) ;
- une même personne n'approuve jamais deux niveaux de la même facture (séparation des tâches) ;
- chaque approbation garde l'empreinte des données approuvées : si elles changent ensuite,
  l'approbation ne vaut plus et il faut approuver de nouveau.

Sans règles publiées, le circuit n'a qu'un niveau, le comptable : une seule validation suffit.
"""

import hashlib
import json
from decimal import Decimal
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


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    toujours: bool | None = None
    champ: Literal["total_ttc", "total_ht"] | None = None
    superieur_a: Decimal | None = None
    anomalie: list[str] | None = None

    @model_validator(mode="after")
    def une_seule_forme(self):
        formes = [self.toujours is True, self.champ is not None, self.anomalie is not None]
        if sum(formes) != 1:
            raise ValueError("Une condition est « toujours », un champ comparé à un seuil, ou une liste d'anomalies.")
        if (self.champ is None) != (self.superieur_a is None):
            raise ValueError("Un champ se compare toujours à un seuil (superieur_a).")
        return self

    def vraie(self, donnees: dict, anomalies: list[dict]) -> bool:
        if self.toujours:
            return True
        if self.champ is not None:
            valeur = donnees.get(self.champ)
            return valeur is not None and Decimal(str(valeur)) > self.superieur_a
        codes = {anomalie["code"] for anomalie in anomalies}
        return bool(codes & set(self.anomalie or []))


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


REGLES_DEMO = [
    {"nom": "Toute facture est approuvée par le comptable", "si": {"toujours": True}, "exige": ["comptable"]},
    {"nom": "Plus de 1 000 € TTC", "si": {"champ": "total_ttc", "superieur_a": "1000"}, "exige": ["directeur_financier"]},
    {"nom": "Plus de 5 000 € TTC", "si": {"champ": "total_ttc", "superieur_a": "5000"}, "exige": ["gerant"]},
    {"nom": "Écart avec le bon de commande, ou achat sans commande", "si": {"anomalie": ["ECART_COMMANDE", "SANS_COMMANDE"]}, "exige": ["directeur_financier"]},
    {"nom": "IBAN différent de celui connu, ou jamais vu", "si": {"anomalie": ["IBAN_DIFFERENT", "IBAN_NOUVEAU"]}, "exige": ["directeur_financier"]},
    {"nom": "Fournisseur inconnu dans Odoo", "si": {"anomalie": ["FOURNISSEUR_INCONNU"]}, "bloque": "Créez d'abord le fournisseur dans Odoo."},
]


def publier(session: Session, regles: list[dict], auteur: str) -> ReglesApprobation:
    """Publie une nouvelle version des règles, après les avoir vérifiées. Les anciennes restent."""
    verifiees = [Regle.model_validate(regle).model_dump(mode="json", exclude_none=True) for regle in regles]
    suivante = (session.scalar(select(func.max(ReglesApprobation.version))) or 0) + 1
    version = ReglesApprobation(version=suivante, regles=verifiees, publie_par=auteur)
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
    return {"version": version.version, "niveaux": niveaux or [{"niveau": "comptable", "raisons": ["Aucune règle ne s'applique"]}], "bloque": bloque}


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
