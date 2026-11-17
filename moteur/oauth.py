"""Connexion d'un connecteur par compte (OAuth 2.1 avec PKCE), comme le demande le protocole MCP.

Le parcours :
1. commencer() : Verifac fabrique un « state » et un secret PKCE, puis envoie le navigateur
   chez l'éditeur (HubSpot…), où la personne se connecte et autorise Verifac ;
2. l'éditeur renvoie le navigateur sur /oauth/retour avec un code ;
3. terminer() : Verifac échange ce code contre des jetons, qu'il range CHIFFRÉS en base ;
4. jeton() : donne un jeton d'accès valide, en le renouvelant tout seul quand il expire.

Les adresses OAuth ne sont pas écrites en dur : elles sont lues dans les métadonnées que le
serveur MCP publie lui-même (/.well-known/oauth-authorization-server).

Réglages (dans .env, jamais affichés) :
- CONNECTEURS_CLE_CHIFFREMENT : clé Fernet qui chiffre les jetons (et CONNECTEURS_CLES_ANCIENNES pour en changer, voir moteur/chiffrement.py) ;
- <CONNECTEUR>_CLIENT_ID et <CONNECTEUR>_CLIENT_SECRET : fournis par l'éditeur (HUBSPOT_CLIENT_ID…) ;
- OAUTH_RETOUR : adresse de retour déclarée chez l'éditeur (par défaut http://localhost:5180/api/oauth/retour).
"""

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from cryptography.fernet import InvalidToken, MultiFernet
from sqlalchemy import delete
from sqlalchemy.orm import Session

from moteur import chiffrement, config
from moteur.base import DemandeOAuth, JetonConnecteur

DUREE_DEMANDE = timedelta(minutes=10)
MARGE_EXPIRATION = timedelta(seconds=60)  # on renouvelle un peu avant l'expiration, jamais après


class ErreurOAuth(Exception):
    pass


def _reglage(nom: str) -> str:
    return config.lire(nom, "")


def adresse_retour() -> str:
    return _reglage("OAUTH_RETOUR") or "http://localhost:5180/api/oauth/retour"


def identifiants(connecteur: str) -> tuple[str, str] | None:
    """(client_id, client_secret) fournis par l'éditeur, ou None s'ils ne sont pas configurés."""
    prefixe = connecteur.upper()
    client_id, secret = _reglage(f"{prefixe}_CLIENT_ID"), _reglage(f"{prefixe}_CLIENT_SECRET")
    return (client_id, secret) if client_id and secret else None


def _chiffreur() -> MultiFernet:
    outil = chiffrement.chiffreur()
    if outil is None:
        raise ErreurOAuth("La clé de chiffrement des jetons (CONNECTEURS_CLE_CHIFFREMENT) n'est pas configurée.")
    return outil


def pret(connecteur: str) -> bool:
    """Tout est configuré pour connecter ce compte : identifiants de l'éditeur et clé de chiffrement."""
    return identifiants(connecteur) is not None and bool(_reglage("CONNECTEURS_CLE_CHIFFREMENT"))


def _chiffrer(texte: str) -> str:
    return _chiffreur().encrypt(texte.encode()).decode()


def _dechiffrer(texte: str) -> str:
    try:
        return _chiffreur().decrypt(texte.encode()).decode()
    except InvalidToken as erreur:
        raise ErreurOAuth("Jeton illisible : la clé de chiffrement a changé. Reconnectez le compte.") from erreur


def metadonnees(adresse_serveur: str, client: httpx.Client) -> dict:
    """Les adresses OAuth publiées par le serveur MCP lui-même."""
    try:
        reponse = client.get(adresse_serveur.rstrip("/") + "/.well-known/oauth-authorization-server")
        reponse.raise_for_status()
        return reponse.json()
    except (httpx.HTTPError, ValueError) as erreur:
        raise ErreurOAuth(f"Le serveur {adresse_serveur} ne publie pas ses adresses OAuth : {erreur}") from erreur


# ───────── Connexion ─────────


def commencer(session: Session, connecteur: str, adresse_serveur: str, auteur: str, client: httpx.Client | None = None) -> str:
    """Prépare la connexion et renvoie l'adresse où envoyer le navigateur."""
    ids = identifiants(connecteur)
    if ids is None:
        raise ErreurOAuth(f"Identifiants OAuth absents : ajoutez {connecteur.upper()}_CLIENT_ID et {connecteur.upper()}_CLIENT_SECRET dans .env.")
    meta = metadonnees(adresse_serveur, client or httpx.Client(timeout=15))
    if "S256" not in meta.get("code_challenge_methods_supported", ["S256"]):
        raise ErreurOAuth("Ce serveur ne propose pas PKCE en S256 : connexion refusée par sécurité.")
    verificateur = secrets.token_urlsafe(64)
    defi = base64.urlsafe_b64encode(hashlib.sha256(verificateur.encode()).digest()).rstrip(b"=").decode()
    etat = secrets.token_urlsafe(32)
    # Les demandes abandonnées depuis plus de 10 minutes ne servent plus à rien.
    session.execute(delete(DemandeOAuth).where(DemandeOAuth.cree_le < datetime.now(UTC) - DUREE_DEMANDE))
    session.add(DemandeOAuth(etat=etat, connecteur=connecteur, verificateur=_chiffrer(verificateur), auteur=auteur))
    session.flush()
    parametres = {
        "response_type": "code",
        "client_id": ids[0],
        "redirect_uri": adresse_retour(),
        "state": etat,
        "code_challenge": defi,
        "code_challenge_method": "S256",
        "resource": adresse_serveur,  # le serveur MCP auquel le jeton est destiné (RFC 8707)
    }
    return f"{meta['authorization_endpoint']}?{urlencode(parametres)}"


def _ranger(session: Session, connecteur: str, reponse: dict) -> None:
    if "access_token" not in reponse:
        raise ErreurOAuth("L'éditeur n'a pas renvoyé de jeton d'accès.")
    jeton = session.get(JetonConnecteur, connecteur) or JetonConnecteur(connecteur=connecteur)
    jeton.acces = _chiffrer(reponse["access_token"])
    if reponse.get("refresh_token"):  # un renouvellement peut ne pas en renvoyer : on garde l'ancien
        jeton.renouvellement = _chiffrer(reponse["refresh_token"])
    duree = reponse.get("expires_in")
    jeton.expire_le = datetime.now(UTC) + timedelta(seconds=int(duree)) if duree else None
    session.add(jeton)
    session.flush()


def _appeler_jetons(adresse_serveur: str, donnees: dict, client: httpx.Client) -> dict:
    meta = metadonnees(adresse_serveur, client)
    try:
        reponse = client.post(meta["token_endpoint"], data=donnees, headers={"Accept": "application/json"})
    except httpx.HTTPError as erreur:
        raise ErreurOAuth(f"L'éditeur est injoignable : {type(erreur).__name__}") from erreur
    if reponse.status_code >= 400:
        # Le corps d'une réponse d'erreur OAuth ne contient pas de secret, mais on n'en garde que le code.
        try:
            code = reponse.json().get("error", "")
        except ValueError:
            code = ""
        raise ErreurOAuth(f"L'éditeur a refusé (code {reponse.status_code} {code}).")
    return reponse.json()


def terminer(session: Session, etat: str, code: str, adresse_de: dict[str, str], client: httpx.Client | None = None) -> DemandeOAuth:
    """Échange le code reçu contre des jetons. adresse_de : adresse du serveur MCP de chaque connecteur."""
    demande = session.get(DemandeOAuth, etat, with_for_update=True)
    if demande is None:
        raise ErreurOAuth("Demande de connexion inconnue ou déjà utilisée : recommencez depuis Verifac.")
    session.delete(demande)  # un « state » ne sert qu'une fois
    session.flush()
    if demande.cree_le < datetime.now(UTC) - DUREE_DEMANDE:
        raise ErreurOAuth("La demande de connexion a expiré : recommencez depuis Verifac.")
    client_id, secret = identifiants(demande.connecteur) or ("", "")
    reponse = _appeler_jetons(
        adresse_de[demande.connecteur],
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": adresse_retour(),
            "client_id": client_id,
            "client_secret": secret,
            "code_verifier": _dechiffrer(demande.verificateur),
        },
        client or httpx.Client(timeout=15),
    )
    _ranger(session, demande.connecteur, reponse)
    return demande


def jeton(session: Session, connecteur: str, adresse_serveur: str, client: httpx.Client | None = None, forcer: bool = False) -> str | None:
    """Un jeton d'accès valide, renouvelé si besoin. None si le compte n'a jamais été connecté."""
    enregistre = session.get(JetonConnecteur, connecteur, with_for_update=True)
    if enregistre is None:
        return None
    perime = enregistre.expire_le is not None and enregistre.expire_le - MARGE_EXPIRATION <= datetime.now(UTC)
    if (perime or forcer) and enregistre.renouvellement:
        client_id, secret = identifiants(connecteur) or ("", "")
        reponse = _appeler_jetons(
            adresse_serveur,
            {"grant_type": "refresh_token", "refresh_token": _dechiffrer(enregistre.renouvellement), "client_id": client_id, "client_secret": secret},
            client or httpx.Client(timeout=15),
        )
        _ranger(session, connecteur, reponse)
    elif perime:
        raise ErreurOAuth("La connexion a expiré et ne peut pas être renouvelée : reconnectez le compte.")
    return _dechiffrer(enregistre.acces)


def oublier(session: Session, connecteur: str) -> None:
    """Efface les jetons du connecteur (débranchement)."""
    session.execute(delete(JetonConnecteur).where(JetonConnecteur.connecteur == connecteur))
    session.flush()
