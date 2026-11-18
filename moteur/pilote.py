"""Le programme pilote : les demandes de place envoyées depuis le site vitrine (verifac.company).

Chaque demande est gardée en base, puis annoncée par mail à PILOTE_DESTINATAIRE (via Resend).
Si le mail ne part pas, la demande reste en base : l'administrateur la voit dans Réglages › Programme pilote.

Contre les robots : un champ piège (« site_web ») invisible pour une personne. S'il est rempli, la demande
est ignorée en silence (la réponse est la même, pour ne pas apprendre au robot qu'il a été repéré).
Le nombre de demandes par adresse IP est limité dans l'API.
"""

import hashlib
from html import escape

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from moteur import config
from moteur.base import DemandePilote
from moteur.notifications import Message

VOLUMES = ("Moins de 50", "50 à 200", "200 à 1 000", "Plus de 1 000")
LOGICIELS = ("Odoo", "Pennylane", "Sage", "Cegid", "Expert-comptable externe", "Autre")


class NouvelleDemande(BaseModel):
    nom: str = Field(min_length=2, max_length=100)
    entreprise: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    volume: str = Field(max_length=40)
    logiciel: str = Field(max_length=60)
    message: str | None = Field(default=None, max_length=3000)
    site_web: str | None = Field(default=None, max_length=300)  # le champ piège


class DemandeRefusee(ValueError):
    """Une valeur hors des choix proposés : le message dit laquelle."""


def est_un_robot(demande: NouvelleDemande) -> bool:
    return bool((demande.site_web or "").strip())


def enregistrer(session: Session, demande: NouvelleDemande) -> DemandePilote:
    if demande.volume not in VOLUMES:
        raise DemandeRefusee("Choisissez un nombre de factures par mois dans la liste.")
    if demande.logiciel not in LOGICIELS:
        raise DemandeRefusee("Choisissez un logiciel comptable dans la liste.")
    ligne = DemandePilote(
        nom=demande.nom.strip(),
        entreprise=demande.entreprise.strip(),
        email=demande.email.strip().lower(),
        volume=demande.volume,
        logiciel=demande.logiciel,
        message=(demande.message or "").strip() or None,
    )
    session.add(ligne)
    session.flush()
    return ligne


def destinataire() -> str:
    return config.lire("PILOTE_DESTINATAIRE", "")


def composer_mail(ligne: DemandePilote, destinataire_mail: str) -> Message:
    champs = [
        ("Nom", ligne.nom),
        ("Entreprise", ligne.entreprise),
        ("Adresse", ligne.email),
        ("Factures par mois", ligne.volume),
        ("Logiciel comptable", ligne.logiciel),
        ("Message", ligne.message or "(aucun)"),
    ]
    lignes_html = "".join(f"<tr><td style='padding:4px 12px 4px 0;color:#5b616e'>{escape(nom)}</td><td style='padding:4px 0'>{escape(valeur)}</td></tr>" for nom, valeur in champs)
    html = (
        "<div style='font-family:system-ui,sans-serif;font-size:15px;color:#1f2328'>"
        f"<p>Nouvelle demande pour le programme pilote de Verifac.</p><table>{lignes_html}</table>"
        f"<p style='color:#5b616e'>Répondre à <a href='mailto:{escape(ligne.email)}'>{escape(ligne.email)}</a>.</p></div>"
    )
    texte = "Nouvelle demande pour le programme pilote de Verifac.\n\n" + "\n".join(f"{nom} : {valeur}" for nom, valeur in champs)
    idempotence = "pilote-" + hashlib.sha256(str(ligne.id).encode()).hexdigest()[:24]
    return Message(destinataire_mail, f"Programme pilote : {ligne.entreprise}", html, texte, idempotence)


def lister(session: Session, limite: int = 200) -> list[dict]:
    demandes = session.scalars(select(DemandePilote).order_by(DemandePilote.cree_le.desc()).limit(limite))
    return [
        {
            "id": str(d.id),
            "nom": d.nom,
            "entreprise": d.entreprise,
            "email": d.email,
            "volume": d.volume,
            "logiciel": d.logiciel,
            "message": d.message,
            "cree_le": d.cree_le.isoformat(),
        }
        for d in demandes
    ]
