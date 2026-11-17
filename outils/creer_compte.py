"""Crée un compte Verifac depuis le serveur : le premier administrateur à l'installation, ou l'opérateur.

    uv run python -m outils.creer_compte --nom "Claire Fabre" --email claire@exemple.fr --role administrateur --niveau gerant

Ensuite, la personne se connecte avec son adresse : elle reçoit un lien et un code par mail.
Les comptes suivants se créent dans Réglages › Équipe, par un administrateur.
"""

import argparse
import sys

from sqlalchemy.orm import Session

from moteur import comptes
from moteur.base import creer_moteur


def main(arguments: list[str] | None = None) -> int:
    lecteur = argparse.ArgumentParser(description="Crée un compte Verifac.")
    lecteur.add_argument("--nom", required=True)
    lecteur.add_argument("--email", required=True)
    lecteur.add_argument("--role", required=True, choices=comptes.ROLES)
    lecteur.add_argument("--niveau", action="append", default=[], choices=comptes.NIVEAUX, help="niveau d'approbation (répétable)")
    options = lecteur.parse_args(arguments)
    with Session(creer_moteur()) as session:
        try:
            compte = comptes.creer(session, options.nom, options.email, options.role, options.niveau, "installation")
        except comptes.CompteInvalide as erreur:
            print(f"Refusé : {erreur}", file=sys.stderr)
            return 1
        session.commit()
        print(f"Compte créé : {compte.nom} <{compte.email}>, {comptes.LIBELLES_ROLES[compte.role]}.")
        if not comptes.peut(compte, "administrer") and comptes.administrateurs_actifs(session) == 0:
            print("Attention : aucun administrateur. Créez-en un pour gérer l'équipe.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
