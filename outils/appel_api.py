"""Appelle l'API d'extraction d'Unstract avec un PDF et mesure le temps de réponse.

Usage : python3 outils/appel_api.py factures/ma-facture.pdf [autre.pdf ...]
La configuration (UNSTRACT_API_URL, UNSTRACT_API_KEY) est lue dans le fichier .env.
La clé n'est jamais affichée.
"""

import json
import pathlib
import sys
import time
import urllib.request
import uuid

RACINE = pathlib.Path(__file__).resolve().parent.parent


def charger_env() -> dict[str, str]:
    config = {}
    for ligne in (RACINE / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in ligne and not ligne.lstrip().startswith("#"):
            cle, valeur = ligne.split("=", 1)
            config[cle.strip()] = valeur.strip()
    return config


def appeler(url: str, cle_api: str, pdf: pathlib.Path, delai: int = 250) -> tuple[int, dict, float]:
    frontiere = uuid.uuid4().hex
    corps = b"".join(
        [
            f"--{frontiere}\r\nContent-Disposition: form-data; name=\"timeout\"\r\n\r\n{delai}\r\n".encode(),
            f"--{frontiere}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{pdf.name}\"\r\n"
            "Content-Type: application/pdf\r\n\r\n".encode(),
            pdf.read_bytes(),
            f"\r\n--{frontiere}--\r\n".encode(),
        ]
    )
    requete = urllib.request.Request(
        url,
        data=corps,
        method="POST",
        headers={
            "Authorization": f"Bearer {cle_api}",
            "Content-Type": f"multipart/form-data; boundary={frontiere}",
        },
    )
    debut = time.monotonic()
    try:
        with urllib.request.urlopen(requete, timeout=delai + 30) as reponse:
            statut, texte = reponse.status, reponse.read().decode("utf-8")
    except urllib.error.HTTPError as erreur:
        statut, texte = erreur.code, erreur.read().decode("utf-8", "replace")
    duree = time.monotonic() - debut
    try:
        donnees = json.loads(texte)
    except json.JSONDecodeError:
        donnees = {"texte_brut": texte[:500]}
    return statut, donnees, duree


def main() -> None:
    config = charger_env()
    for chemin in sys.argv[1:]:
        pdf = pathlib.Path(chemin)
        statut, donnees, duree = appeler(config["UNSTRACT_API_URL"], config["UNSTRACT_API_KEY"], pdf)
        print(f"== {pdf.name} | HTTP {statut} | {duree:.1f} s")
        print(json.dumps(donnees, ensure_ascii=False, indent=1)[:2500])


if __name__ == "__main__":
    main()
