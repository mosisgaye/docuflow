"""La purge des données techniques périmées, lancée par le travailleur quelques fois par jour.

Ce qui sert de preuve n'est JAMAIS purgé : factures, journal (evenements), approbations, mails reçus,
consignes, versions du circuit, comptes. On ne retire que ce qui ne sert plus à rien :
- les tâches de lecture terminées depuis plus de 30 jours (les abandonnées restent : ce sont des incidents) ;
- les liens et codes de connexion expirés depuis plus d'un jour ;
- les connexions OAuth commencées et jamais finies, après un jour ;
- le journal des appels aux connecteurs, après 90 jours ;
- les événements déjà livrés aux abonnés, après 90 jours (les abandonnés restent, pour enquête) ;
- les codes et jetons du connecteur Claude expirés depuis plus d'un jour.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from moteur.base import AppelConnecteur, CodeOAuth, DemandeConnexion, DemandeOAuth, EtatTache, JetonOAuth, Livraison, Tache

TACHES_TERMINEES = timedelta(days=30)
DEMANDES_EXPIREES = timedelta(days=1)
APPELS_CONNECTEURS = timedelta(days=90)
LIVRAISONS_LIVREES = timedelta(days=90)


def purger(session: Session, maintenant: datetime | None = None) -> dict[str, int]:
    """Supprime les lignes périmées et renvoie, par table, le nombre de lignes supprimées."""
    maintenant = maintenant or datetime.now(UTC)
    requetes = {
        "taches": delete(Tache).where(Tache.etat == EtatTache.TERMINEE.value, Tache.modifie_le < maintenant - TACHES_TERMINEES),
        "demandes_connexion": delete(DemandeConnexion).where(DemandeConnexion.expire_le < maintenant - DEMANDES_EXPIREES),
        "demandes_oauth": delete(DemandeOAuth).where(DemandeOAuth.cree_le < maintenant - DEMANDES_EXPIREES),
        "appels_connecteurs": delete(AppelConnecteur).where(AppelConnecteur.cree_le < maintenant - APPELS_CONNECTEURS),
        "livraisons": delete(Livraison).where(Livraison.etat == "livree", Livraison.livree_le < maintenant - LIVRAISONS_LIVREES),
        "oauth_codes": delete(CodeOAuth).where(CodeOAuth.expire_le < maintenant - DEMANDES_EXPIREES),
        "oauth_jetons": delete(JetonOAuth).where(JetonOAuth.expire_le < maintenant - DEMANDES_EXPIREES),
    }
    return {table: session.execute(requete).rowcount for table, requete in requetes.items()}
