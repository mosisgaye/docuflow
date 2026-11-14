"""Règles communes pour retenter un appel à un service extérieur (IA, registres).

On ne retente que ce qui peut réussir en retentant : une panne passagère.
Une clé refusée ou une demande mal formée échouera pareil à chaque fois :
la retenter ne ferait que marteler le service.
"""

import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

# Codes HTTP qui signalent une panne passagère : délai dépassé, conflit, trop de demandes, serveur indisponible.
CODES_PASSAGERS = {408, 409, 425, 429, 500, 502, 503, 504}

# Nombre maximal d'appels dans une même demande (le premier compris).
TENTATIVES = 3

# Au-delà de cette attente, on n'attend pas sur place : on rend la main,
# et la tâche sera reprogrammée plus tard par la file (voir moteur/travailleur.py).
ATTENTE_MAX_SUR_PLACE_S = 20.0


def est_passager(code: int) -> bool:
    return code in CODES_PASSAGERS


def delai_demande(reponse: httpx.Response, maintenant: datetime | None = None) -> float | None:
    """Délai demandé par le service dans l'en-tête Retry-After, en secondes, s'il y en a un."""
    valeur = reponse.headers.get("retry-after")
    if not valeur:
        return None
    try:
        return max(0.0, float(valeur))
    except ValueError:
        pass
    try:
        date = parsedate_to_datetime(valeur)
    except (TypeError, ValueError):
        return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return max(0.0, (date - (maintenant or datetime.now(timezone.utc))).total_seconds())


def delai_avant_essai(numero: int, hasard: random.Random | None = None) -> float:
    """Attente avant l'essai numéro `numero` (2 pour le premier nouvel essai) : 1 s, 2 s, 4 s…

    La part aléatoire (± 20 %) évite que plusieurs travailleurs retentent tous à la même seconde.
    """
    base = min(ATTENTE_MAX_SUR_PLACE_S, 2.0 ** (numero - 2))
    return base * (hasard or random).uniform(0.8, 1.2)
