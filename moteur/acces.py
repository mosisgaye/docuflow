"""Code d'accès de la démonstration en ligne, et limite de dépôts.

DOCUFLOW_CODE_ACCES : si ce réglage est vide (développement, tests), tout est ouvert.
Sinon, l'écran et l'API interne demandent le code une fois ; le navigateur garde ensuite
un cookie de 30 jours. Le cookie vaut HMAC(code) : changer le code déconnecte tout le monde.

Restent ouverts sans code, parce qu'ils ont leur propre protection :
- /reception/mail (signature Ed25519 du Worker de messagerie) ;
- /approbation/… (lien signé envoyé par mail) ;
- /oauth/retour (état OAuth à usage unique) ;
- /v1/… (clé d'API) ;
- /sante (ne dit rien de sensible).

Contre l'essai de codes au hasard : 8 essais faux au plus par adresse IP, et 40 en tout, par quart d'heure.

DEPOTS_PAR_JOUR : nombre de nouvelles factures acceptées par jour (0 ou vide : sans limite).
Chaque lecture coûte un appel à l'IA : la démonstration ne doit pas pouvoir vider le crédit.
"""

import hashlib
import hmac
import time
from collections import defaultdict, deque

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moteur import config
from moteur.base import FactureEnBase

COOKIE = "docuflow_acces"
DUREE_COOKIE_S = 30 * 24 * 3600
ESSAIS_MAX = 8
ESSAIS_MAX_TOTAL = 40  # toutes adresses confondues, par quart d'heure
FENETRE_ESSAIS_S = 15 * 60
# La connexion par compte a ses propres protections (lien et code à usage unique, essais limités).
CHEMINS_LIBRES = {"/acces", "/sante", "/reception/mail", "/oauth/retour", "/moi", "/connexion/demande", "/connexion/lien", "/connexion/code", "/deconnexion"}
# Le connecteur Claude (moteur/mcp_verifac.py) a sa propre protection : jeton OAuth sur /mcp, compte connecté
# sur la page d'accord. Ces adresses ne doivent donc ni exiger le code d'accès ni la session de l'interface.
CHEMINS_LIBRES |= {"/mcp", "/authorize", "/token", "/register", "/revoke", "/oauth/consentement"}
PREFIXES_LIBRES = ("/approbation/", "/v1/", "/.well-known/")


def code() -> str:
    return config.lire("DOCUFLOW_CODE_ACCES", "")


def jeton(code_acces: str) -> str:
    return hmac.new(code_acces.encode(), b"docuflow-acces-1", hashlib.sha256).hexdigest()


def chemin_libre(chemin: str) -> bool:
    return chemin in CHEMINS_LIBRES or chemin.startswith(PREFIXES_LIBRES)


def autorise(chemin: str, cookie: str | None) -> bool:
    attendu = code()
    if not attendu or chemin_libre(chemin):
        return True
    return cookie is not None and hmac.compare_digest(cookie, jeton(attendu))


def code_correct(propose: str) -> bool:
    attendu = code()
    return bool(attendu) and hmac.compare_digest(propose.strip().encode(), attendu.encode())


class Tentatives:
    """Compte les essais faux par adresse, sur une fenêtre glissante. En mémoire : un seul processus API."""

    def __init__(self, maximum: int = ESSAIS_MAX, fenetre_s: float = FENETRE_ESSAIS_S):
        self.maximum, self.fenetre_s = maximum, fenetre_s
        self._essais: dict[str, deque[float]] = defaultdict(deque)

    def _purger(self, adresse: str, maintenant: float) -> deque[float]:
        essais = self._essais[adresse]
        while essais and essais[0] < maintenant - self.fenetre_s:
            essais.popleft()
        return essais

    def bloquee(self, adresse: str) -> bool:
        return len(self._purger(adresse, time.monotonic())) >= self.maximum

    def noter_echec(self, adresse: str) -> None:
        self._purger(adresse, time.monotonic()).append(time.monotonic())


def depots_par_jour() -> int:
    try:
        return max(0, int(config.lire("DEPOTS_PAR_JOUR", "0") or 0))
    except ValueError:
        return 0


def quota_atteint(session: Session) -> bool:
    """Vrai si la limite du jour est atteinte. Compte les factures créées depuis minuit (heure du serveur)."""
    limite = depots_par_jour()
    if not limite:
        return False
    du_jour = session.scalar(select(func.count()).select_from(FactureEnBase).where(FactureEnBase.cree_le >= func.date_trunc("day", func.now())))
    return du_jour >= limite
