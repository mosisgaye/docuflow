"""Le mode démo : une installation séparée de Verifac, ouverte aux prospects, avec de fausses données.

VERIFAC_MODE_DEMO=1 l'active. Il ne doit JAMAIS l'être en production : sans lui, rien ici ne s'applique
et la route d'entrée en un clic répond 404.

En mode démo :
- « Entrer dans la démo » ouvre une session sur un compte partagé (VERIFAC_DEMO_EMAIL), créé au besoin,
  administrateur, aux trois niveaux d'approbation : le prospect peut tout essayer ;
- ce qui toucherait le monde extérieur ou les accès est refusé : comptes, clés d'API, abonnements
  (messages vers une adresse donnée par le visiteur), connecteurs ;
- l'agent est plafonné par jour (AGENT_PAR_JOUR, 50 par défaut) : chaque réponse coûte un appel à l'IA.
  Les dépôts de factures, eux, sont plafonnés par DEPOTS_PAR_JOUR (moteur/acces.py).

Les mails ne partent pas : l'installation de démo n'a pas de clé Resend ni de secret d'approbation.
La remise à zéro de chaque nuit est faite hors du moteur (deploiement/demo/remise.sh).
"""

import re
import threading
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from moteur import comptes, config

NOM_COMPTE = "Visiteur de la démo"

# Refusé en démo, quel que soit le rôle. (verbe, motif de chemin, ce que la personne lit)
BLOQUEES = [
    (r"POST|PUT|DELETE", r"/comptes(/.*)?", "la gestion des comptes"),
    (r"POST|DELETE", r"/cles-api(/.*)?", "la création de clés d'API"),
    (r"POST|DELETE", r"/abonnements(/.*)?", "l'envoi de messages vers un autre logiciel"),
    (r"POST|PUT|DELETE", r"/connecteurs/.*", "le branchement des connecteurs"),
]


def actif() -> bool:
    return config.lire("VERIFAC_MODE_DEMO", "").strip().lower() in ("1", "oui", "true")


def email() -> str:
    return comptes.normaliser_email(config.lire("VERIFAC_DEMO_EMAIL", "") or "demo@verifac.company")


def refus(methode: str, chemin: str) -> str | None:
    """Le message à montrer si cette action est fermée dans la démo, sinon None."""
    if not actif():
        return None
    for verbes, motif, quoi in BLOQUEES:
        if re.fullmatch(verbes, methode) and re.fullmatch(motif, chemin):
            return f"Dans la démo, {quoi} est désactivé. Tout le reste s'essaie librement."
    return None


def compte(session: Session) -> comptes.Compte:
    """Le compte partagé de la démo, créé s'il n'existe pas encore. Il est remis actif s'il ne l'était plus."""
    adresse = email()
    existant = session.scalar(select(comptes.Compte).where(comptes.Compte.email == adresse))
    if existant is not None:
        existant.actif, existant.role, existant.niveaux = True, "administrateur", list(comptes.NIVEAUX)
        return existant
    return comptes.creer(session, NOM_COMPTE, adresse, "administrateur", list(comptes.NIVEAUX), "demo")


def agent_par_jour() -> int:
    try:
        return max(0, int(config.lire("AGENT_PAR_JOUR", "50") or 0))
    except ValueError:
        return 50


class CompteurJour:
    """Compte les usages du jour, en mémoire (un seul processus API). Repart de zéro chaque jour."""

    def __init__(self) -> None:
        self._jour, self._nombre, self._verrou = date.today(), 0, threading.Lock()

    def prendre(self, limite: int) -> bool:
        """Vrai si l'usage est permis (et compté) ; faux si la limite du jour est atteinte. 0 : sans limite."""
        with self._verrou:
            if date.today() != self._jour:
                self._jour, self._nombre = date.today(), 0
            if limite and self._nombre >= limite:
                return False
            self._nombre += 1
            return True
