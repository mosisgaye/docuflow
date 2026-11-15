"""Simule un mail reçu à l'adresse de dépôt, comme le ferait l'adaptateur Cloudflare.

Sert à essayer la réception par mail sans messagerie : le mail est signé avec
RECEPTION_MAIL_SECRET (lu dans .env) et envoyé à l'API.

    uv run python -m outils.envoyer_mail_test factures/facture-F26-1193.pdf
    uv run python -m outils.envoyer_mail_test a.pdf b.pdf --de compta@fournisseur.fr --objet "Factures novembre"
"""

import argparse
import base64
import json
import pathlib
import time
import uuid

import httpx

from moteur import config
from moteur.reception_mail import signer


def main() -> None:
    parametres = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parametres.add_argument("fichiers", nargs="*", type=pathlib.Path, help="pièces jointes du mail")
    parametres.add_argument("--de", default="compta@fournisseur-exemple.fr", help="expéditeur")
    parametres.add_argument("--objet", default="Facture", help="objet du mail")
    parametres.add_argument("--message-id", default=None, help="identifiant du mail (par défaut : un nouveau)")
    parametres.add_argument("--api", default="http://127.0.0.1:8010", help="adresse de l'API")
    arguments = parametres.parse_args()

    mail = {
        "message_id": arguments.message_id or f"<{uuid.uuid4()}@essai.docuflow>",
        "expediteur": arguments.de,
        "objet": arguments.objet,
        "pieces": [
            {"nom": fichier.name, "type": "application/pdf", "contenu_base64": base64.b64encode(fichier.read_bytes()).decode()}
            for fichier in arguments.fichiers
        ],
    }
    corps = json.dumps(mail).encode()
    horodatage = str(int(time.time()))
    reponse = httpx.post(
        f"{arguments.api}/reception/mail",
        content=corps,
        headers={
            "Content-Type": "application/json",
            "X-DocuFlow-Horodatage": horodatage,
            "X-DocuFlow-Signature": signer(config.lire("RECEPTION_MAIL_SECRET"), horodatage, corps),
        },
        timeout=60,
    )
    print(reponse.status_code, json.dumps(reponse.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
