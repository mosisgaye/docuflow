"""Événements sortants (webhooks) : prévenir les autres logiciels de ce qui arrive aux factures.

Un abonnement = une adresse web + les événements qui l'intéressent :
    facture.recue, facture.a_valider, facture.en_anomalie, facture.validee,
    facture.rejetee, facture.exportee, facture.echec

Comment c'est fiable :
- la livraison est préparée DANS LA MÊME TRANSACTION que le changement de la facture
  (« boîte d'envoi transactionnelle ») : si le changement est annulé, rien ne part ;
  s'il est enregistré, l'envoi finira par partir, même après une panne ;
- le travailleur envoie les livraisons, et retente en cas d'échec : 30 s, 2 min, 10 min,
  1 h, 6 h, puis abandon (visible dans Verifac) ;
- chaque envoi est signé : HMAC-SHA256 de « horodatage.corps » avec le secret de
  l'abonnement (en-têtes X-Verifac-Horodatage et X-Verifac-Signature). Le destinataire
  vérifie la signature et refuse un envoi trop ancien ;
- l'identifiant de livraison (X-Verifac-Livraison) est le même à chaque nouvel essai :
  le destinataire peut ignorer un doublon.
- pendant la transition, les mêmes en-têtes partent aussi sous l'ancien nom X-DocuFlow-*.
"""

import hashlib
import hmac
import ipaddress
import json
import secrets
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx
from cryptography.fernet import MultiFernet
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moteur import chiffrement, config
from moteur.base import Abonnement, Etat, FactureEnBase, Livraison

EVENEMENTS = {
    "facture.recue": "Une facture est arrivée (dépôt, mail ou API)",
    "facture.a_valider": "Une facture a été lue et contrôlée : elle attend une décision",
    "facture.en_anomalie": "Une facture a été lue, mais un contrôle bloquant a échoué",
    "facture.validee": "Une facture a été validée par tous les niveaux d'approbation",
    "facture.rejetee": "Une facture a été rejetée",
    "facture.exportee": "Une facture a été envoyée au logiciel de comptabilité",
    "facture.echec": "Une facture n'a pas pu être lue",
}
PAR_ETAT = {
    Etat.A_VALIDER: "facture.a_valider",
    Etat.EN_ANOMALIE: "facture.en_anomalie",
    Etat.VALIDEE: "facture.validee",
    Etat.REJETEE: "facture.rejetee",
    Etat.EXPORTEE: "facture.exportee",
    Etat.ECHEC: "facture.echec",
}
PLAN_S = [30, 120, 600, 3600, 6 * 3600]
TENTATIVES_MAX = len(PLAN_S) + 1


class AbonnementRefuse(ValueError):
    pass


def _chiffreur() -> MultiFernet:
    outil = chiffrement.chiffreur()
    if outil is None:
        raise AbonnementRefuse("La clé de chiffrement (CONNECTEURS_CLE_CHIFFREMENT) n'est pas configurée.")
    return outil


def _url_acceptable(url: str) -> None:
    """HTTPS obligatoire, sauf vers cette machine (développement). Jamais vers une adresse privée du réseau."""
    adresse = urlparse(url)
    hote = adresse.hostname or ""
    locale = hote in ("localhost", "127.0.0.1", "::1")
    if adresse.scheme not in ("https", "http") or not hote:
        raise AbonnementRefuse("Adresse invalide.")
    if adresse.scheme == "http" and not locale:
        raise AbonnementRefuse("Seules les adresses en https sont acceptées (http seulement vers cette machine).")
    try:
        ip = ipaddress.ip_address(hote)
    except ValueError:
        return
    if not locale and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
        # Sinon, un abonnement pourrait servir à sonder le réseau interne du serveur.
        raise AbonnementRefuse("Les adresses de réseau privé sont refusées.")


def creer_abonnement(session: Session, url: str, evenements: list[str], auteur: str) -> tuple[Abonnement, str]:
    """Crée l'abonnement et renvoie son secret de signature, montré une seule fois."""
    inconnus = sorted(set(evenements) - set(EVENEMENTS))
    if inconnus or not evenements:
        raise AbonnementRefuse(f"Événements inconnus ou absents : {', '.join(inconnus) or 'aucun'}.")
    _url_acceptable(url)
    secret = f"whsec_{secrets.token_urlsafe(32)}"
    abonnement = Abonnement(url=url, evenements=sorted(set(evenements)), secret=_chiffreur().encrypt(secret.encode()).decode(), cree_par=auteur)
    session.add(abonnement)
    session.flush()
    return abonnement, secret


def publier(session: Session, facture: FactureEnBase, evenement: str) -> int:
    """Prépare la livraison de l'événement à chaque abonnement concerné. Dans la transaction en cours."""
    abonnes = [
        abonnement for abonnement in session.scalars(select(Abonnement).where(Abonnement.actif))
        if evenement in abonnement.evenements
    ]
    if not abonnes:
        return 0
    donnees = facture.donnees or {}
    charge = {
        "evenement": evenement,
        "facture": {
            "id": str(facture.id),
            "numero": facture.numero_facture,
            "fournisseur": donnees.get("fournisseur_nom"),
            "siret": facture.fournisseur_siret,
            "total_ttc": donnees.get("total_ttc"),
            "date_echeance": donnees.get("date_echeance"),
            "etat": facture.etat,
            "anomalies": [anomalie["code"] for anomalie in facture.anomalies],
        },
    }
    for abonnement in abonnes:
        session.add(Livraison(abonnement_id=abonnement.id, evenement=evenement, charge=charge))
    session.flush()
    return len(abonnes)


def signer(secret: str, horodatage: str, corps: bytes) -> str:
    return hmac.new(secret.encode(), horodatage.encode() + b"." + corps, hashlib.sha256).hexdigest()


def entetes_signes(evenement: str, livraison: str, horodatage: str, signature: str) -> dict[str, str]:
    """Les en-têtes X-Verifac-*. Les mêmes valeurs partent aussi en X-DocuFlow-* (l'ancien nom du produit),
    le temps que les abonnés existants passent au nouveau nom : à retirer ensuite."""
    valeurs = {"Evenement": evenement, "Livraison": livraison, "Horodatage": horodatage, "Signature": signature}
    return {f"X-{marque}-{nom}": valeur for marque in ("Verifac", "DocuFlow") for nom, valeur in valeurs.items()}


def livrer_une(session: Session, client: httpx.Client | None = None) -> Livraison | None:
    """Envoie la plus ancienne livraison due. Ne valide pas la transaction : c'est à l'appelant."""
    livraison = session.scalars(
        select(Livraison)
        .where(Livraison.etat == "en_attente", Livraison.prochain_essai_le <= func.now())
        .order_by(Livraison.prochain_essai_le)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if livraison is None:
        return None
    abonnement = session.get(Abonnement, livraison.abonnement_id)
    livraison.tentatives += 1
    if abonnement is None or not abonnement.actif:
        livraison.etat, livraison.derniere_reponse = "abandonnee", "Abonnement supprimé ou désactivé."
        return livraison
    corps = json.dumps({**livraison.charge, "livraison": str(livraison.id), "date": livraison.cree_le.isoformat()}, ensure_ascii=False).encode()
    horodatage = str(int(time.time()))
    try:
        secret = _chiffreur().decrypt(abonnement.secret.encode()).decode()
        reponse = (client or httpx.Client(timeout=10, follow_redirects=False)).post(
            abonnement.url,
            content=corps,
            headers={"Content-Type": "application/json", **entetes_signes(livraison.evenement, str(livraison.id), horodatage, signer(secret, horodatage, corps))},
        )
        resultat = f"HTTP {reponse.status_code}"
        reussi = 200 <= reponse.status_code < 300
    except Exception as erreur:  # noqa: BLE001 - réseau, délai, clé de chiffrement changée…
        resultat, reussi = f"{type(erreur).__name__}", False
    livraison.derniere_reponse = resultat
    if reussi:
        livraison.etat, livraison.livree_le = "livree", datetime.now(UTC)
    elif livraison.tentatives >= TENTATIVES_MAX:
        livraison.etat = "abandonnee"
    else:
        livraison.prochain_essai_le = datetime.now(UTC) + timedelta(seconds=PLAN_S[livraison.tentatives - 1])
    session.flush()
    return livraison
