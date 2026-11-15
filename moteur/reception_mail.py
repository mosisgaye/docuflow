"""Réception des factures par mail.

Le mail arrive d'abord chez un adaptateur (aujourd'hui un Worker Cloudflare branché sur
l'adresse de dépôt ; demain Microsoft 365, Gmail ou IMAP pour la boîte d'un client).
L'adaptateur transmet le mail BRUT, tel que reçu (format RFC 5322), à POST /reception/mail.
Toutes les messageries savent fournir ce format : l'analyse est faite une seule fois, ici,
par la bibliothèque standard de Python. Ajouter un adaptateur ne touche pas au moteur.

Sécurité : l'adaptateur signe chaque envoi avec sa clé privée Ed25519, sur
« horodatage.corps ». DocuFlow ne connaît que les clés publiques : lire sa configuration
ne permet pas de fabriquer un faux envoi. La clé privée de l'adaptateur Cloudflare a été
créée chez Cloudflare et n'en sort jamais. Une signature fausse, ou un envoi de plus de
5 minutes rejoué plus tard, est refusé.

Chaque pièce jointe PDF devient une facture, exactement comme un dépôt à l'écran :
même file de tâches, même lecture, mêmes contrôles. Le journal de la facture garde
l'expéditeur et l'objet du mail.
"""

import base64
import binascii
import hashlib
import pathlib
import time
import uuid
from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pypdf.errors import PyPdfError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from moteur.base import MailRecu
from moteur.lecture_pdf import image_en_pdf, lire_pdf
from moteur.workflow import ranger_fichier, recevoir

TOLERANCE_HORLOGE_S = 300
TAILLE_MAX_PIECE_OCTETS = 10 * 1024 * 1024
PIECES_MAX = 20


class SignatureInvalide(Exception):
    """L'envoi ne vient pas de notre adaptateur, ou il est trop ancien."""


@dataclass(frozen=True)
class PieceJointe:
    nom: str
    type_mime: str
    contenu: bytes
    jointe: bool = True  # vraie pièce jointe ; faux pour une image affichée dans le corps du mail (logo, signature)


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


def _message(horodatage: str, corps: bytes) -> bytes:
    return horodatage.encode() + b"." + corps


def signer(cle_privee: Ed25519PrivateKey, horodatage: str, corps: bytes) -> str:
    """Signature d'un envoi, en base64. Le Worker fait la même chose en JavaScript."""
    return base64.b64encode(cle_privee.sign(_message(horodatage, corps))).decode()


def cles_publiques(texte: str) -> list[Ed25519PublicKey]:
    """Les clés publiques acceptées, en base64 séparées par des virgules (plusieurs adaptateurs, ou une rotation)."""
    return [Ed25519PublicKey.from_public_bytes(base64.b64decode(morceau.strip())) for morceau in texte.split(",") if morceau.strip()]


def en_base64(cle: Ed25519PublicKey) -> str:
    return base64.b64encode(cle.public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


def verifier_signature(
    cles: list[Ed25519PublicKey], horodatage: str | None, signature: str | None, corps: bytes, maintenant: float | None = None
) -> None:
    if not horodatage or not signature:
        raise SignatureInvalide("Signature absente.")
    try:
        instant = int(horodatage)
    except ValueError as erreur:
        raise SignatureInvalide("Horodatage illisible.") from erreur
    if abs((maintenant if maintenant is not None else time.time()) - instant) > TOLERANCE_HORLOGE_S:
        raise SignatureInvalide("Envoi trop ancien ou horloge décalée.")
    try:
        brute = base64.b64decode(signature, validate=True)
    except (binascii.Error, ValueError) as erreur:
        raise SignatureInvalide("Signature illisible.") from erreur
    for cle in cles:
        try:
            cle.verify(brute, _message(horodatage, corps))
            return
        except InvalidSignature:
            continue
    raise SignatureInvalide("Signature fausse.")


def _expediteur(mail: EmailMessage) -> str:
    try:
        adresses = mail["From"].addresses if mail["From"] is not None else ()
        if adresses and adresses[0].addr_spec:
            return adresses[0].addr_spec[:320]
    except (AttributeError, IndexError, TypeError, ValueError):
        pass  # en-tête From mal formé : on garde le texte tel quel
    return (str(mail.get("From", "")).strip() or "expéditeur inconnu")[:320]


def lire_mail_brut(brut: bytes) -> MailEntrant:
    """Analyse un mail brut. Ne lève jamais d'erreur : un mail abîmé donne simplement moins d'informations."""
    mail = BytesParser(policy=policy.default).parsebytes(brut)
    # Sans Message-ID (rare), l'empreinte du mail en tient lieu : un renvoi à l'identique reste reconnu.
    message_id = str(mail.get("Message-ID", "")).strip() or f"<sans-identifiant-{hashlib.sha256(brut).hexdigest()[:32]}@docuflow>"
    pieces = []
    for partie in mail.walk():
        if partie.is_multipart():
            continue
        nom = partie.get_filename()
        # Le corps du mail (texte, HTML) n'est pas une pièce jointe. Un PDF sans nom en est une.
        if not nom and partie.get_content_disposition() != "attachment" and partie.get_content_type() != "application/pdf":
            continue
        try:
            contenu = partie.get_payload(decode=True) or b""
        except (binascii.Error, ValueError):
            contenu = b""
        pieces.append(PieceJointe(nom or "piece-jointe", partie.get_content_type(), contenu, partie.get_content_disposition() == "attachment"))
    return MailEntrant(message_id[:998], _expediteur(mail), str(mail.get("Subject", "")).strip()[:2000], pieces)


TAILLE_MIN_PHOTO_OCTETS = 30 * 1024  # en dessous, une image de mail est un logo ou une icône, pas une facture


def _en_pdf(piece: PieceJointe) -> tuple[PieceJointe | None, str | None]:
    """La pièce sous forme de PDF, ou la raison pour laquelle elle n'est pas une facture.

    Une photo de facture jointe au mail est mise dans un PDF. Une image affichée dans le corps
    du mail, ou trop petite, est un logo ou une signature : elle est ignorée.
    """
    if piece.contenu.startswith(b"%PDF-"):
        return piece, None
    pdf = image_en_pdf(piece.contenu)
    if pdf is None:
        return None, "Ce n'est pas un PDF."  # ni PDF ni image : document Word, archive…
    if not piece.jointe or len(piece.contenu) < TAILLE_MIN_PHOTO_OCTETS:
        return None, "Image dans le corps du mail ou trop petite : probablement un logo, ignorée."
    return PieceJointe(f"{pathlib.Path(piece.nom).stem or 'photo'}.pdf", "application/pdf", pdf), None


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
        piece_pdf, raison = _en_pdf(piece)
        raison = raison or _examiner(piece_pdf)
        if raison:
            pieces.append({"nom": piece.nom, "resultat": "ignoree", "raison": raison})
            continue
        ranger_fichier(dossier, piece_pdf.contenu)
        resultat = recevoir(session, piece_pdf.contenu, pathlib.Path(piece_pdf.nom).name or "facture.pdf", origine)
        pieces.append({"nom": piece.nom, "resultat": "deja_recue" if resultat.deja_vue else "facture", "facture_id": str(resultat.facture.id)})
    for piece in mail.pieces[PIECES_MAX:]:
        pieces.append({"nom": piece.nom, "resultat": "ignoree", "raison": f"Plus de {PIECES_MAX} pièces jointes dans le mail."})

    enregistrement.pieces = pieces
    enregistrement.statut = "traite" if any(piece["resultat"] != "ignoree" for piece in pieces) else "sans_facture"
    session.flush()
    return CompteRenduMail(enregistrement, deja_vu=False)
