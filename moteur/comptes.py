"""Les comptes : qui utilise Verifac, avec quels droits, et comment on se connecte.

Connexion sans mot de passe : la personne donne son adresse et reçoit un mail avec
- un lien, qui ouvre une page « Se connecter » (c'est le clic sur le bouton qui connecte : les
  messageries d'entreprise ouvrent les liens pour les analyser, elles ne doivent pas les consommer) ;
- un code à 6 chiffres, pour se connecter sur un autre appareil que celui où l'on lit le mail.
Lien et code : usage unique, 15 minutes, seules leurs empreintes sont gardées, 5 essais de code au plus,
3 demandes au plus par quart d'heure et par compte.

La session est un cookie signé (HMAC) de 30 jours qui porte le compte et sa version de session :
augmenter la version déconnecte toutes les sessions du compte.

Les rôles d'accès (distincts des niveaux d'approbation : comptable, directeur financier, gérant) :
- administrateur : tout, plus l'équipe, les réglages, les connecteurs, les clés d'API, la publication du circuit ;
- membre : traiter les factures (déposer, décider, exporter), le brouillon du circuit, l'agent ;
- approbateur : seulement les factures où il intervient, et les approuver ou les rejeter ;
- lecture : tout voir, rien changer ;
- operateur : le prestataire (technique et support). N'approuve jamais, ne publie jamais.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moteur import config
from moteur.base import Compte, DemandeConnexion  # noqa: F401 - Compte sert aussi à l'API

ROLES = ("administrateur", "membre", "approbateur", "lecture", "operateur")
LIBELLES_ROLES = {
    "administrateur": "Administrateur",
    "membre": "Membre",
    "approbateur": "Approbateur",
    "lecture": "Lecture seule",
    "operateur": "Opérateur Verifac",
}
NIVEAUX = ("comptable", "directeur_financier", "gerant")
# Les rôles qu'un administrateur du client peut donner. L'opérateur se crée seulement depuis le serveur.
ROLES_CLIENT = ("administrateur", "membre", "approbateur", "lecture")

# Ce que chaque rôle peut faire. Les adresses de l'API exigent un de ces droits.
DROITS = {
    "voir": {"administrateur", "membre", "approbateur", "lecture", "operateur"},
    "approuver": {"administrateur", "membre", "approbateur"},
    "traiter": {"administrateur", "membre"},  # déposer, exporter, relancer une lecture
    "circuit": {"administrateur", "membre"},  # modifier le brouillon, tester
    "agent": {"administrateur", "membre"},  # converser avec l'agent (il peut écrire le brouillon)
    "administrer": {"administrateur"},  # équipe, réception, connecteurs, clés d'API, abonnements, publier le circuit
    "operer": {"operateur"},  # console technique
}

DUREE_LIEN = timedelta(minutes=15)
DUREE_SESSION = timedelta(days=30)
ESSAIS_CODE_MAX = 5
DEMANDES_MAX = 3  # par compte et par quart d'heure
COURRIEL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CompteInvalide(ValueError):
    """Un compte refusé (adresse, rôle, niveau…) : le message dit pourquoi."""


class ConnexionRefusee(ValueError):
    """Lien ou code invalide, expiré, déjà utilisé, ou trop d'essais. Le message reste vague exprès."""


def peut(compte: Compte | None, droit: str) -> bool:
    return compte is not None and compte.actif and compte.role in DROITS[droit]


def normaliser_email(email: str) -> str:
    return email.strip().lower()


def vue(compte: Compte) -> dict:
    return {
        "id": str(compte.id),
        "nom": compte.nom,
        "email": compte.email,
        "role": compte.role,
        "libelle_role": LIBELLES_ROLES[compte.role],
        "niveaux": list(compte.niveaux or []),
        "actif": compte.actif,
        "derniere_connexion": compte.derniere_connexion,
        "droits": sorted(droit for droit, roles in DROITS.items() if compte.role in roles),
    }


# ───────── Les comptes ─────────


def verifier(nom: str, email: str, role: str, niveaux: list[str]) -> tuple[str, str, str, list[str]]:
    nom, email = " ".join(nom.split()), normaliser_email(email)
    if not 1 <= len(nom) <= 100:
        raise CompteInvalide("Le nom compte de 1 à 100 caractères.")
    if len(email) > 320 or not COURRIEL.match(email):
        raise CompteInvalide(f"« {email} » n'est pas une adresse mail.")
    if role not in ROLES:
        raise CompteInvalide(f"Rôle inconnu : {role}.")
    inconnus = set(niveaux) - set(NIVEAUX)
    if inconnus:
        raise CompteInvalide(f"Niveau d'approbation inconnu : {', '.join(sorted(inconnus))}.")
    if role in ("lecture", "operateur") and niveaux:
        raise CompteInvalide("Un compte en lecture seule ou opérateur n'approuve pas : il n'a pas de niveau d'approbation.")
    return nom, email, role, [n for n in NIVEAUX if n in niveaux]


def creer(session: Session, nom: str, email: str, role: str, niveaux: list[str], auteur: str) -> Compte:
    nom, email, role, niveaux = verifier(nom, email, role, niveaux)
    if session.scalar(select(Compte).where(Compte.email == email)):
        raise CompteInvalide(f"{email} a déjà un compte.")
    compte = Compte(nom=nom, email=email, role=role, niveaux=niveaux, actif=True, version_session=1, cree_par=auteur)
    session.add(compte)
    session.flush()
    return compte


def administrateurs_actifs(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Compte).where(Compte.role == "administrateur", Compte.actif.is_(True))) or 0


def modifier(session: Session, compte: Compte, role: str | None = None, niveaux: list[str] | None = None, actif: bool | None = None) -> Compte:
    """Change le rôle, les niveaux ou l'état d'un compte. Il reste toujours au moins un administrateur actif."""
    nouveau_role = role or compte.role
    _, _, nouveau_role, nouveaux_niveaux = verifier(compte.nom, compte.email, nouveau_role, compte.niveaux if niveaux is None else niveaux)
    nouvel_actif = compte.actif if actif is None else actif
    if compte.role == "administrateur" and compte.actif and (nouveau_role != "administrateur" or not nouvel_actif) and administrateurs_actifs(session) <= 1:
        raise CompteInvalide("Il faut toujours au moins un administrateur : nommez-en un autre avant.")
    retire = (compte.actif and not nouvel_actif) or nouveau_role != compte.role
    compte.role, compte.niveaux, compte.actif = nouveau_role, nouveaux_niveaux, nouvel_actif
    if retire:
        compte.version_session += 1  # un rôle retiré ou un compte désactivé : ses sessions tombent
    session.flush()
    return compte


def existe_un_compte(session: Session) -> bool:
    return session.scalar(select(Compte.id).limit(1)) is not None


# ───────── La connexion par lien ou par code ─────────


def _secret() -> bytes:
    secret = config.lire("VERIFAC_SECRET_SESSION", "")
    if len(secret) < 32:
        raise ConnexionRefusee("La connexion n'est pas configurée (VERIFAC_SECRET_SESSION, 32 caractères au moins).")
    return secret.encode()


def _empreinte(valeur: str) -> str:
    return hashlib.sha256(valeur.encode()).hexdigest()


def _empreinte_code(demande_id: uuid.UUID, code: str) -> str:
    # Avec le secret : sans lui, une base volée ne permet pas de retrouver les codes par essais.
    return hmac.new(_secret(), f"{demande_id}:{code}".encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class Envoi:
    """Ce qu'il faut envoyer par mail après l'enregistrement : jamais gardé en clair en base."""

    compte_id: uuid.UUID
    email: str
    nom: str
    jeton: str
    code: str


def demander(session: Session, email: str, maintenant: datetime | None = None) -> Envoi | None:
    """Prépare un lien et un code pour ce compte. None si l'adresse est inconnue, inactive, ou trop sollicitée.

    La réponse à la personne est la même dans tous les cas : on ne dit pas si une adresse a un compte.
    """
    maintenant = maintenant or datetime.now(UTC)
    compte = session.scalar(select(Compte).where(Compte.email == normaliser_email(email)))
    if compte is None or not compte.actif:
        return None
    recentes = session.scalar(
        select(func.count()).select_from(DemandeConnexion).where(DemandeConnexion.compte_id == compte.id, DemandeConnexion.cree_le > maintenant - timedelta(minutes=15))
    )
    if recentes >= DEMANDES_MAX:
        return None
    jeton = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1_000_000):06d}"
    demande = DemandeConnexion(id=uuid.uuid4(), compte_id=compte.id, empreinte_jeton=_empreinte(jeton), essais=0, expire_le=maintenant + DUREE_LIEN, cree_le=maintenant)
    demande.empreinte_code = _empreinte_code(demande.id, code)
    session.add(demande)
    session.flush()
    return Envoi(compte.id, compte.email, compte.nom, jeton, code)


def _valide(demande: DemandeConnexion | None, maintenant: datetime) -> bool:
    return demande is not None and demande.utilisee_le is None and demande.expire_le > maintenant and demande.essais < ESSAIS_CODE_MAX


def _terminer(session: Session, demande: DemandeConnexion, maintenant: datetime) -> Compte:
    compte = session.get(Compte, demande.compte_id)
    if compte is None or not compte.actif:
        raise ConnexionRefusee("Ce lien ou ce code ne permet plus de se connecter.")
    demande.utilisee_le = maintenant
    compte.derniere_connexion = maintenant
    session.flush()
    return compte


def par_lien(session: Session, jeton: str, maintenant: datetime | None = None) -> Compte:
    maintenant = maintenant or datetime.now(UTC)
    demande = session.scalar(select(DemandeConnexion).where(DemandeConnexion.empreinte_jeton == _empreinte(jeton)).with_for_update())
    if not _valide(demande, maintenant):
        raise ConnexionRefusee("Ce lien n'est plus valable. Demandez-en un nouveau.")
    return _terminer(session, demande, maintenant)


def par_code(session: Session, email: str, code: str, maintenant: datetime | None = None) -> Compte:
    """Le code de la dernière demande encore valable de ce compte. Chaque code faux compte un essai."""
    maintenant = maintenant or datetime.now(UTC)
    compte = session.scalar(select(Compte).where(Compte.email == normaliser_email(email)))
    demande = (
        session.scalar(
            select(DemandeConnexion).where(DemandeConnexion.compte_id == compte.id).order_by(DemandeConnexion.cree_le.desc()).limit(1).with_for_update()
        )
        if compte
        else None
    )
    if not _valide(demande, maintenant):
        raise ConnexionRefusee("Ce code n'est plus valable. Demandez-en un nouveau.")
    if not hmac.compare_digest(demande.empreinte_code, _empreinte_code(demande.id, re.sub(r"\s", "", code))):
        demande.essais += 1
        session.flush()
        raise ConnexionRefusee("Code incorrect." if demande.essais < ESSAIS_CODE_MAX else "Trop d'essais. Demandez un nouveau code.")
    return _terminer(session, demande, maintenant)


# ───────── La session ─────────

COOKIE = "verifac_session"


def _b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode()


def jeton_session(compte: Compte, maintenant: datetime | None = None) -> str:
    maintenant = maintenant or datetime.now(UTC)
    charge = _b64(json.dumps({"c": str(compte.id), "v": compte.version_session, "e": int((maintenant + DUREE_SESSION).timestamp())}).encode())
    signature = _b64(hmac.new(_secret(), charge.encode(), hashlib.sha256).digest())
    return f"{charge}.{signature}"


def lire_session(session: Session, valeur: str | None, maintenant: datetime | None = None) -> Compte | None:
    """Le compte de la session, ou None (absente, falsifiée, expirée, compte désactivé ou déconnecté partout)."""
    if not valeur or "." not in valeur:
        return None
    maintenant = maintenant or datetime.now(UTC)
    charge, signature = valeur.rsplit(".", 1)
    try:
        attendue = _b64(hmac.new(_secret(), charge.encode(), hashlib.sha256).digest())
    except ConnexionRefusee:
        return None
    if not hmac.compare_digest(signature, attendue):
        return None
    try:
        contenu = json.loads(base64.urlsafe_b64decode(charge + "=" * (-len(charge) % 4)))
        compte = session.get(Compte, uuid.UUID(contenu["c"]))
    except (ValueError, KeyError, TypeError):
        return None
    if compte is None or not compte.actif or contenu["v"] != compte.version_session or contenu["e"] < maintenant.timestamp():
        return None
    return compte


def deconnecter_partout(session: Session, compte: Compte) -> None:
    compte.version_session += 1
    session.flush()


# ───────── Le mail de connexion ─────────


def adresse_application() -> str:
    return config.lire("VERIFAC_ADRESSE", "http://localhost:5180").rstrip("/")


def composer_mail(envoi: Envoi):
    """Le mail : un bouton vers la page « Se connecter » (le clic connecte, pas l'ouverture), et le code."""
    import html

    from moteur.notifications import Message  # notifications s'appuie sur la base, pas sur ce module

    lien = f"{adresse_application()}/?connexion={envoi.jeton}"
    code = f"{envoi.code[:3]} {envoi.code[3:]}"
    texte = "\n".join(
        [
            f"Bonjour {envoi.nom},",
            "",
            f"Pour vous connecter à Verifac, ouvrez ce lien puis cliquez sur « Se connecter » : {lien}",
            "",
            f"Ou saisissez ce code : {code}",
            "",
            "Le lien et le code servent une seule fois et expirent dans 15 minutes.",
            "Si vous n'avez rien demandé, ignorez ce mail : personne ne peut se connecter sans lui.",
            "",
            "Verifac",
        ]
    )
    e = html.escape
    corps = f"""<div style="font-family:Arial,sans-serif;font-size:15px;line-height:1.5;color:#13203a;max-width:520px">
<p>Bonjour {e(envoi.nom)},</p>
<p>Pour vous connecter à Verifac :</p>
<p><a href="{e(lien)}" style="display:inline-block;background:#0b7f57;color:#ffffff;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:bold">Ouvrir Verifac et se connecter</a></p>
<p>Ou saisissez ce code : <b style="font-size:20px;letter-spacing:3px">{e(code)}</b></p>
<p style="color:#55627b;font-size:13px">Le lien et le code servent une seule fois et expirent dans 15 minutes. Si vous n'avez rien demandé, ignorez ce mail : personne ne peut se connecter sans lui.</p>
<p style="color:#55627b;font-size:13px">Verifac</p>
</div>"""
    return Message(envoi.email, "Votre connexion à Verifac", corps, texte, f"connexion-{_empreinte(envoi.jeton)[:24]}")


# ───────── Le droit exigé par chaque adresse de l'API ─────────

# (méthode, motif de l'adresse, droit). Lu dans l'ordre : la première ligne qui correspond s'applique.
# Une adresse absente de la liste exige le droit le plus fort : on n'ouvre rien par oubli.
REGLES_ACCES = [
    ("POST", r"/factures/[^/]+/(validation|rejet)", "approuver"),
    ("POST", r"/factures/[^/]+/export", "traiter"),
    ("POST", r"/factures", "traiter"),
    ("GET", r"/factures(/.*)?", "voir"),
    ("GET", r"/statistiques", "voir"),
    ("POST", r"/circuit/publier", "administrer"),
    ("GET", r"/circuit/.*", "voir"),
    ("PUT", r"/circuit/brouillon", "circuit"),
    ("DELETE", r"/circuit/brouillon", "circuit"),
    ("POST", r"/circuit/tester", "circuit"),
    ("GET", r"/regles", "voir"),
    ("POST", r"/agent", "agent"),
    ("GET", r"/connecteurs(/.*)?", "voir"),
    ("GET", r"/reglages/(equipe|reception)", "voir"),
    ("GET", r"/comptes", "voir"),
    ("GET", r"/console", "operer"),
    ("POST", r"/console/premier-administrateur", "operer"),
]


def droit_requis(methode: str, chemin: str) -> str:
    for verbe, motif, droit in REGLES_ACCES:
        if methode == verbe and re.fullmatch(motif, chemin):
            return droit
    return "administrer"
