"""Simule un mail reçu à l'adresse de dépôt, comme le ferait l'adaptateur Cloudflare.

Sert à essayer la réception par mail sans messagerie. Le mail est signé avec une clé
d'essai, créée au premier lancement dans donnees/cle-essai-mail.pem (jamais versionnée).
Sa clé publique est affichée : l'ajouter à RECEPTION_MAIL_CLES_PUBLIQUES dans .env.

    uv run python -m outils.envoyer_mail_test factures/facture-F26-1193.pdf
    uv run python -m outils.envoyer_mail_test a.pdf b.pdf --de compta@fournisseur.fr --objet "Factures novembre"
"""

import argparse
import json
import pathlib
import time
import uuid
from email.message import EmailMessage

import httpx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, load_pem_private_key

from moteur import config
from moteur.reception_mail import en_base64, signer

CLE_ESSAI = config.RACINE / "donnees" / "cle-essai-mail.pem"


def cle_essai() -> Ed25519PrivateKey:
    if not CLE_ESSAI.exists():
        CLE_ESSAI.parent.mkdir(parents=True, exist_ok=True)
        cle = Ed25519PrivateKey.generate()
        CLE_ESSAI.write_bytes(cle.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
        CLE_ESSAI.chmod(0o600)
    return load_pem_private_key(CLE_ESSAI.read_bytes(), password=None)


def main() -> None:
    parametres = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parametres.add_argument("fichiers", nargs="*", type=pathlib.Path, help="pièces jointes du mail")
    parametres.add_argument("--de", default="compta@fournisseur-exemple.fr", help="expéditeur")
    parametres.add_argument("--objet", default="Facture", help="objet du mail")
    parametres.add_argument("--message-id", default=None, help="identifiant du mail (par défaut : un nouveau)")
    parametres.add_argument("--api", default="http://127.0.0.1:8010", help="adresse de l'API")
    arguments = parametres.parse_args()
    cle = cle_essai()
    print(f"Clé publique d'essai : {en_base64(cle.public_key())}")

    mail = EmailMessage()
    mail["From"] = arguments.de
    mail["To"] = "depot@factures.moussagaye.com"
    mail["Subject"] = arguments.objet
    mail["Message-ID"] = arguments.message_id or f"<{uuid.uuid4()}@essai.docuflow>"
    mail.set_content("Bonjour, veuillez trouver la facture en pièce jointe.")
    for fichier in arguments.fichiers:
        mail.add_attachment(fichier.read_bytes(), maintype="application", subtype="pdf", filename=fichier.name)
    corps = mail.as_bytes()
    horodatage = str(int(time.time()))
    reponse = httpx.post(
        f"{arguments.api}/reception/mail",
        content=corps,
        headers={
            "Content-Type": "message/rfc822",
            "X-DocuFlow-Horodatage": horodatage,
            "X-DocuFlow-Signature": signer(cle, horodatage, corps),
        },
        timeout=60,
    )
    print(reponse.status_code, json.dumps(reponse.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
