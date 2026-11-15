"""Clés d'accès à l'API publique de DocuFlow (/v1/…), pour que d'autres logiciels s'y branchent.

Une clé ressemble à : dfk_3f9a2c1b_8kq2…  (« dfk » pour DocuFlow key, puis un préfixe, puis le secret).
- Elle n'est montrée qu'UNE fois, à sa création. DocuFlow ne garde que son empreinte (SHA-256) :
  une fuite de la base ne donne aucune clé utilisable.
- Le préfixe, lui, est gardé en clair : il permet de reconnaître une clé (« dfk_3f9a2c1b… »)
  et de la retrouver sans parcourir toutes les empreintes.
- Chaque clé a des droits précis, et peut être révoquée à tout moment.
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from moteur.base import CleApi

DROITS = {
    "factures:lire": "Lire les factures, leur état et leur journal",
    "factures:deposer": "Déposer une facture (PDF ou photo)",
}


class AccesRefuse(Exception):
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code  # 401 : qui êtes-vous ? 403 : vous n'avez pas ce droit


@dataclass(frozen=True)
class CleCreee:
    cle: CleApi
    secret_complet: str  # à montrer une fois, puis oublié


def _empreinte(cle: str) -> str:
    return hashlib.sha256(cle.encode()).hexdigest()


def creer(session: Session, nom: str, droits: list[str], auteur: str) -> CleCreee:
    inconnus = sorted(set(droits) - set(DROITS))
    if inconnus or not droits:
        raise ValueError(f"Droits inconnus ou absents : {', '.join(inconnus) or 'aucun droit demandé'}.")
    prefixe = secrets.token_hex(4)
    complet = f"dfk_{prefixe}_{secrets.token_urlsafe(32)}"
    cle = CleApi(nom=nom, prefixe=prefixe, empreinte=_empreinte(complet), droits=sorted(set(droits)), creee_par=auteur)
    session.add(cle)
    session.flush()
    return CleCreee(cle, complet)


def verifier(session: Session, entete: str | None, droit: str) -> CleApi:
    """La clé présentée dans « Authorization: Bearer dfk_… », si elle est valable et a ce droit."""
    if not entete or not entete.startswith("Bearer dfk_"):
        raise AccesRefuse("Clé d'API absente : envoyez l'en-tête « Authorization: Bearer dfk_… ».", 401)
    presentee = entete.removeprefix("Bearer ").strip()
    morceaux = presentee.split("_", 2)
    cle = session.scalars(select(CleApi).where(CleApi.prefixe == morceaux[1])).first() if len(morceaux) == 3 else None
    # compare_digest : la comparaison prend le même temps, que la clé soit presque juste ou pas du tout.
    if cle is None or not hmac.compare_digest(cle.empreinte, _empreinte(presentee)):
        raise AccesRefuse("Clé d'API inconnue.", 401)
    if cle.revoquee_le is not None:
        raise AccesRefuse("Cette clé d'API a été révoquée.", 401)
    if droit not in cle.droits:
        raise AccesRefuse(f"Cette clé n'a pas le droit « {droit} ».", 403)
    cle.utilisee_le = datetime.now(UTC)
    return cle


def revoquer(session: Session, cle: CleApi) -> None:
    if cle.revoquee_le is None:
        cle.revoquee_le = datetime.now(UTC)
        session.flush()
