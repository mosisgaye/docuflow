"""Le chiffrement des secrets gardés en base : jetons OAuth des connecteurs et secrets des abonnements.

Réglages (dans .env, jamais affichés) :
- CONNECTEURS_CLE_CHIFFREMENT : la clé Fernet en service, qui chiffre tout ce qui est écrit ;
- CONNECTEURS_CLES_ANCIENNES : facultatif, d'anciennes clés séparées par des virgules, qui servent seulement à relire.

Changer de clé sans rien perdre (par exemple si la clé a fuité) :
1. mettre la nouvelle clé dans CONNECTEURS_CLE_CHIFFREMENT et l'ancienne dans CONNECTEURS_CLES_ANCIENNES,
   puis relancer le moteur : tout reste lisible ;
2. rechiffrer la base avec la nouvelle clé : python -m moteur.chiffrement
   (sur le serveur : docker compose -f compose.prod.yaml exec -T api python -m moteur.chiffrement) ;
3. retirer l'ancienne clé de CONNECTEURS_CLES_ANCIENNES.
"""

from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import select
from sqlalchemy.orm import Session

from moteur import config


def chiffreur() -> MultiFernet | None:
    """La clé en service d'abord (elle chiffre), puis les anciennes (elles ne font que relire). None sans clé."""
    cle = config.lire("CONNECTEURS_CLE_CHIFFREMENT", "").strip()
    if not cle:
        return None
    anciennes = [ancienne.strip() for ancienne in config.lire("CONNECTEURS_CLES_ANCIENNES", "").split(",") if ancienne.strip()]
    return MultiFernet([Fernet(cle.encode()), *(Fernet(ancienne.encode()) for ancienne in anciennes)])


def rechiffrer(session: Session) -> int:
    """Rechiffre avec la clé en service tout ce qui l'a été avec une ancienne clé. Renvoie le nombre de valeurs réécrites."""
    from moteur.base import Abonnement, JetonConnecteur

    outil = chiffreur()
    if outil is None:
        raise RuntimeError("CONNECTEURS_CLE_CHIFFREMENT n'est pas configurée.")
    nombre = 0
    for jeton in session.scalars(select(JetonConnecteur).with_for_update()):
        jeton.acces = outil.rotate(jeton.acces.encode()).decode()
        nombre += 1
        if jeton.renouvellement:
            jeton.renouvellement = outil.rotate(jeton.renouvellement.encode()).decode()
            nombre += 1
    for abonnement in session.scalars(select(Abonnement).with_for_update()):
        abonnement.secret = outil.rotate(abonnement.secret.encode()).decode()
        nombre += 1
    return nombre


if __name__ == "__main__":
    from moteur.base import creer_moteur

    with Session(creer_moteur()) as session:
        total = rechiffrer(session)
        session.commit()
    print(f"{total} valeur(s) rechiffrée(s) avec la clé en service.")
