"""Passe tous les PDF d'un dossier dans le workflow complet, avec le vrai LLM et la vraie base.

Usage : uv run python -m outils.traiter_dossier [dossier]   (par défaut : factures/)
Relancer la commande ne retraite rien : les fichiers déjà vus sont reconnus.
"""

import pathlib
import sys
import time

from sqlalchemy.orm import Session

from moteur.base import creer_moteur, creer_tables
from moteur.workflow import traiter

RACINE = pathlib.Path(__file__).resolve().parent.parent


def main() -> None:
    dossier = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else RACINE / "factures"
    moteur = creer_moteur()
    creer_tables(moteur)
    for chemin in sorted(dossier.glob("*.pdf")):
        with Session(moteur) as session:
            debut = time.monotonic()
            resultat = traiter(session, chemin.read_bytes(), chemin.name)
            session.commit()
            duree = time.monotonic() - debut
            facture = resultat.facture
            mention = "déjà vue, rien refait" if resultat.deja_vue else "traitée"
            print(f"{chemin.name:26} {duree:5.2f} s | {facture.etat:11} | {mention}")
            for anomalie in facture.anomalies:
                print(f"    {anomalie['gravite']} : {anomalie['message']}")
            if not resultat.deja_vue:
                journal = " > ".join(f"{evenement.type}" for evenement in facture.evenements)
                print(f"    journal : {journal}")


if __name__ == "__main__":
    main()
