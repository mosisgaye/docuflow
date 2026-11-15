"""Réception des factures par mail.

Le mail arrive d'abord chez un adaptateur (aujourd'hui un Worker Cloudflare branché sur
l'adresse de dépôt ; demain Microsoft 365, Gmail ou IMAP pour la boîte d'un client).
L'adaptateur le ramène à une forme unique, MailEntrant, et l'envoie à POST /reception/mail.
Le moteur ne connaît que cette forme : ajouter un adaptateur ne touche pas au moteur.

Sécurité : l'adaptateur signe chaque envoi avec un secret partagé (HMAC-SHA256 sur
« horodatage.corps »). Une signature fausse, ou un envoi de plus de 5 minutes rejoué
plus tard, est refusé.

Chaque pièce jointe PDF devient une facture, exactement comme un dépôt à l'écran :
même file de tâches, même lecture, mêmes contrôles. Le journal de la facture garde
l'expéditeur et l'objet du mail.
"""

import base64
import binascii
import hashlib
import hmac
import pathlib
import time
import uuid
from dataclasses import dataclass

from pypdf.errors import PyPdfError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from moteur.base import MailRecu
from moteur.lecture_pdf import lire_pdf
from moteur.workflow import ranger_fichier, recevoir

TOLERANCE_HORLOGE_S = 300
TAILLE_MAX_PIECE_OCTETS = 10 * 1024 * 1024
PIECES_MAX = 20


class SignatureInvalide(Exception):
    """L'envoi ne vient pas de notre adaptateur, ou il est trop ancien."""


class PieceIllisible(Exception):
    """Le contenu d'une pièce jointe n'est pas un base64 valide."""


@dataclass(frozen=True)
class PieceJointe:
    nom: str
    type_mime: str
    contenu: bytes


@dataclass(frozen=True)
class MailEntrant:
    message_id: str
    expediteur: str
    objet: str
    pieces: list[PieceJointe]


@dataclass(frozen=True)
class CompteRenduMail:
    mail: MailRecu
    deja_vu: bool  # vrai si ce mail avait déjà été reçu : rien n'a été refait


def signer(secret: str, horodatage: str, corps: bytes) -> str:
    """La signature attendue pour un envoi. Utilisée par l'adaptateur et par les tests."""
    return hmac.new(secret.encode(), horodatage.encode() + b"." + corps, hashlib.sha256).hexdigest()


def verifier_signature(secret: str, horodatage: str | None, signature: str | None, corps: bytes, maintenant: float | None = None) -> None:
    if not horodatage or not signature:
        raise SignatureInvalide("Signature absente.")
    try:
        instant = int(horodatage)
    except ValueError as erreur:
        raise SignatureInvalide("Horodatage illisible.") from erreur
    if abs((maintenant if maintenant is not None else time.time()) - instant) > TOLERANCE_HORLOGE_S:
        raise SignatureInvalide("Envoi trop ancien ou horloge décalée.")
    # compare_digest : la comparaison prend le même temps quelle que soit la signature reçue.
    if not hmac.compare_digest(signer(secret, horodatage, corps), signature):
        raise SignatureInvalide("Signature fausse.")


def decoder(contenu_base64: str) -> bytes:
    try:
        return base64.b64decode(contenu_base64, validate=True)
    except (binascii.Error, ValueError) as erreur:
        raise PieceIllisible("Pièce jointe mal encodée.") from erreur


def _examiner(piece: PieceJointe) -> str | None:
    """Pourquoi la pièce ne peut pas devenir une facture, ou None si elle le peut."""
    # On juge le contenu, pas le nom ni le type annoncé : un « facture.pdf » peut être n'importe quoi.
    if not piece.contenu.startswith(b"%PDF-"):
        return "Ce n'est pas un PDF."
    if len(piece.contenu) > TAILLE_MAX_PIECE_OCTETS:
        return "PDF trop volumineux (10 Mo au maximum)."
    try:
        lire_pdf(piece.contenu)
    except PyPdfError:
        return "PDF illisible."
    return None


def recevoir_mail(session: Session, mail: MailEntrant, dossier: pathlib.Path) -> CompteRenduMail:
    """Enregistre le mail et met chacune de ses factures en file de lecture. Idempotent sur le Message-ID."""
    # Même principe que pour les fichiers : on réserve le Message-ID d'abord. Si le même mail
    # arrive deux fois en même temps, le second attend le premier puis le reconnaît.
    nouvel_id = session.execute(
        insert(MailRecu)
        .values(id=uuid.uuid4(), message_id=mail.message_id, expediteur=mail.expediteur, objet=mail.objet, statut="sans_facture", pieces=[])
        .on_conflict_do_nothing(index_elements=[MailRecu.message_id])
        .returning(MailRecu.id)
    ).scalar_one_or_none()
    if nouvel_id is None:
        return CompteRenduMail(session.scalars(select(MailRecu).where(MailRecu.message_id == mail.message_id)).one(), deja_vu=True)

    enregistrement = session.get(MailRecu, nouvel_id)
    origine = {"source": "mail", "mail_id": str(nouvel_id), "expediteur": mail.expediteur, "objet": mail.objet}
    pieces = []
    for piece in mail.pieces[:PIECES_MAX]:
        raison = _examiner(piece)
        if raison:
            pieces.append({"nom": piece.nom, "resultat": "ignoree", "raison": raison})
            continue
        ranger_fichier(dossier, piece.contenu)
        resultat = recevoir(session, piece.contenu, pathlib.Path(piece.nom).name or "facture.pdf", origine)
        pieces.append({"nom": piece.nom, "resultat": "deja_recue" if resultat.deja_vue else "facture", "facture_id": str(resultat.facture.id)})
    for piece in mail.pieces[PIECES_MAX:]:
        pieces.append({"nom": piece.nom, "resultat": "ignoree", "raison": f"Plus de {PIECES_MAX} pièces jointes dans le mail."})

    enregistrement.pieces = pieces
    enregistrement.statut = "traite" if any(piece["resultat"] != "ignoree" for piece in pieces) else "sans_facture"
    session.flush()
    return CompteRenduMail(enregistrement, deja_vu=False)
