"""Remplit une installation de démo en déposant des factures par son API, comme le ferait un visiteur.

    uv run python -m outils.remplir_demo https://demo.verifac.company demo factures
    uv run python -m outils.remplir_demo http://localhost:5180 demo        # en local

Entre par « Entrer dans la démo » (le moteur doit être en mode démo), puis dépose chaque PDF et chaque
photo des dossiers donnés. La lecture se fait ensuite par le travailleur de la démo, avec le vrai LLM
(quelques centimes par facture) et compte dans DEPOTS_PAR_JOUR.

Une fois la démo dans l'état voulu (circuit publié dans l'écran Workflow), prendre la photo de référence :
    docker compose -f compose.demo.yaml exec remise /scripts/photographier.sh
"""

import mimetypes
import pathlib
import sys

import httpx

EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    adresse, dossiers = sys.argv[1].rstrip("/"), [pathlib.Path(d) for d in sys.argv[2:]]
    with httpx.Client(base_url=f"{adresse}/api", timeout=60) as client:
        entree = client.post("/connexion/demo")
        if entree.status_code != 200:
            sys.exit(f"Entrée refusée ({entree.status_code}) : ce moteur n'est pas en mode démo ?")
        for dossier in dossiers:
            for chemin in sorted(p for p in dossier.iterdir() if p.suffix.lower() in EXTENSIONS):
                type_mime = mimetypes.guess_type(chemin.name)[0] or "application/octet-stream"
                reponse = client.post("/factures", files={"fichier": (chemin.name, chemin.read_bytes(), type_mime)})
                if reponse.status_code >= 300:
                    print(f"{chemin.name} : refusé ({reponse.status_code}) {reponse.json().get('detail', '')}")
                    if reponse.status_code == 429:
                        sys.exit("Limite de dépôts du jour atteinte (DEPOTS_PAR_JOUR).")
                    continue
                print(f"{chemin.name} : {'déjà reçue' if reponse.json().get('deja_vue') else 'déposée'}")


if __name__ == "__main__":
    main()
