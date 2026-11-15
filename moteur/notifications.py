"""Prévenir par mail la personne qui doit approuver une facture.

Le mail contient UN lien signé vers une page de confirmation. Le lien seul n'approuve rien :
les messageries ouvrent souvent les liens d'elles-mêmes pour les analyser, et une approbation
ne doit jamais partir sans un clic sur le bouton de cette page.

Le lien est signé (HMAC-SHA256 avec APPROBATION_SECRET) et porte la facture, le niveau, la
personne et l'empreinte des données. Il ne vaut plus dès que :
- le niveau a été approuvé (usage unique, de fait), ou la facture rejetée ;
- les données de la facture ont changé ;
- 7 jours ont passé.

Le mail ne part qu'après l'enregistrement en base (transaction validée) : un mail ne peut pas
annoncer une approbation qui n'existe pas. Envoi par Resend, avec une clé d'idempotence :
un même envoi rejoué ne donne pas deux mails.

Réglages : RESEND_API_KEY, MAIL_EXPEDITEUR, APPROBATION_SECRET, APPROBATION_DESTINATAIRE
(ou APPROBATION_DESTINATAIRE_COMPTABLE, _DIRECTEUR_FINANCIER, _GERANT par niveau),
APPROBATION_ADRESSE (par défaut http://localhost:5180/api).
"""

import base64
import hashlib
import hmac
import html
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from moteur import config
from moteur.approbation import LIBELLES, empreinte
from moteur.base import FactureEnBase

DUREE_LIEN_S = 7 * 24 * 3600
CLE_SESSION = "notifications_en_attente"

journal = logging.getLogger("moteur.notifications")


class LienInvalide(Exception):
    pass


@dataclass(frozen=True)
class Message:
    destinataire: str
    sujet: str
    html: str
    texte: str
    idempotence: str


# ───────── Les liens signés ─────────


def _secret() -> bytes:
    secret = config.lire("APPROBATION_SECRET", "")
    if not secret:
        raise LienInvalide("Les liens d'approbation ne sont pas configurés (APPROBATION_SECRET).")
    return secret.encode()


def _b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode()


def _deb64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def signer_lien(facture_id: uuid.UUID, niveau: str, personne: str, donnees: dict | None, maintenant: float | None = None) -> str:
    charge = {"f": str(facture_id), "n": niveau, "p": personne, "h": empreinte(donnees)[:32], "x": int((maintenant or time.time()) + DUREE_LIEN_S)}
    corps = _b64(json.dumps(charge, separators=(",", ":")).encode())
    return f"{corps}.{_b64(hmac.new(_secret(), corps.encode(), hashlib.sha256).digest())}"


def lire_lien(jeton: str, maintenant: float | None = None) -> dict:
    """Vérifie la signature et la date, et renvoie le contenu du lien. Ne regarde pas encore la facture."""
    try:
        corps, signature = jeton.split(".")
        attendue = _b64(hmac.new(_secret(), corps.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(attendue, signature):
            raise LienInvalide("Lien falsifié.")
        charge = json.loads(_deb64(corps))
    except (ValueError, json.JSONDecodeError) as erreur:
        raise LienInvalide("Lien illisible.") from erreur
    if charge["x"] < (maintenant or time.time()):
        raise LienInvalide("Ce lien a expiré.")
    return charge


def adresse_lien(jeton: str) -> str:
    return f"{config.lire('APPROBATION_ADRESSE', 'http://localhost:5180/api').rstrip('/')}/approbation/{jeton}"


# ───────── Le mail ─────────


def destinataire(niveau: str) -> str | None:
    return config.lire(f"APPROBATION_DESTINATAIRE_{niveau.upper()}", "") or config.lire("APPROBATION_DESTINATAIRE", "") or None


def _euros(valeur) -> str:
    return f"{float(valeur):,.2f} €".replace(",", " ").replace(".", ",") if valeur is not None else "montant inconnu"


def composer(facture: FactureEnBase, niveau: str, personne: str, rappel: str | None = None) -> Message:
    donnees = facture.donnees or {}
    niveau_circuit = next((n for n in (facture.circuit or {}).get("niveaux", []) if n["niveau"] == niveau), {"raisons": []})
    lien = adresse_lien(signer_lien(facture.id, niveau, personne, facture.donnees))
    numero, fournisseur, montant = donnees.get("numero_facture") or "?", donnees.get("fournisseur_nom") or "Fournisseur", _euros(donnees.get("total_ttc"))
    avertissements = [a["message"] for a in facture.anomalies]
    sujet = f"{'Rappel : approbation' if rappel else 'Approbation'} demandée : facture {numero} de {fournisseur} ({montant})"
    lignes_texte = [
        f"Bonjour,",
        "",
        f"La facture {numero} de {fournisseur}, d'un montant de {montant}, attend votre approbation en tant que {LIBELLES[niveau].lower()}.",
        f"Pourquoi vous : {' ; '.join(niveau_circuit['raisons'])}.",
        *([f"Rappel : {rappel}"] if rappel else []),
        *([f"À regarder : {' '.join(avertissements)}"] if avertissements else []),
        "",
        f"Examiner la facture et décider : {lien}",
        "",
        "Le lien ouvre une page de confirmation : rien n'est approuvé tant que vous n'avez pas cliqué sur le bouton.",
        "Il expire dans 7 jours, et ne vaut plus si la facture change.",
        "",
        "Verifac",
    ]
    e = html.escape
    corps_html = f"""<div style="font-family:Arial,sans-serif;font-size:15px;line-height:1.5;color:#13203a;max-width:560px">
<p>Bonjour,</p>
<p>La facture <b>{e(numero)}</b> de <b>{e(fournisseur)}</b>, d'un montant de <b>{e(montant)}</b>, attend votre approbation en tant que <b>{e(LIBELLES[niveau].lower())}</b>.</p>
<p style="color:#55627b">Pourquoi vous : {e(' ; '.join(niveau_circuit['raisons']))}.</p>
{f'<p style="background:#e6eeff;color:#1746c9;padding:8px 12px;border-radius:8px"><b>Rappel :</b> {e(rappel)}</p>' if rappel else ''}
{''.join(f'<p style="background:#fdeed6;color:#8a4a00;padding:8px 12px;border-radius:8px">{e(a)}</p>' for a in avertissements)}
<p><a href="{e(lien)}" style="display:inline-block;background:#1f5bff;color:#ffffff;padding:12px 18px;border-radius:10px;text-decoration:none;font-weight:bold">Examiner la facture et décider</a></p>
<p style="color:#55627b;font-size:13px">Le lien ouvre une page de confirmation : rien n'est approuvé tant que vous n'avez pas cliqué sur le bouton. Il expire dans 7 jours, et ne vaut plus si la facture change.</p>
<p style="color:#55627b;font-size:13px">Verifac</p>
</div>"""
    # Un rappel a sa propre clé : sinon Resend le prendrait pour un doublon du premier mail.
    idempotence = f"approbation-{facture.id}-{niveau}-{empreinte(facture.donnees)[:16]}" + (f"-rappel-{hashlib.sha256(rappel.encode()).hexdigest()[:12]}" if rappel else "")
    return Message(personne, sujet, corps_html, "\n".join(lignes_texte), idempotence)


def envoyer_par_resend(message: Message, client: httpx.Client | None = None) -> dict:
    cle = config.lire("RESEND_API_KEY", "")
    if not cle:
        raise RuntimeError("Clé Resend absente (RESEND_API_KEY).")
    reponse = (client or httpx.Client(timeout=15)).post(
        "https://api.resend.com/emails",
        json={"from": config.lire("MAIL_EXPEDITEUR", "DocuFlow <docuflow@moussagaye.com>"), "to": [message.destinataire], "subject": message.sujet, "html": message.html, "text": message.texte},
        headers={"Authorization": f"Bearer {cle}", "Idempotency-Key": message.idempotence},
    )
    if reponse.status_code >= 300:
        raise RuntimeError(f"Resend a refusé l'envoi (code {reponse.status_code}).")
    return {"id": reponse.json().get("id")}


# ───────── Après l'enregistrement ─────────


def demander(session: Session, facture: FactureEnBase, niveau: str, rappel: str | None = None) -> bool:
    """Prépare la demande d'approbation pour ce niveau. Elle partira après la validation de la transaction.

    Renvoie faux si les mails ne sont pas configurés (l'approbation se fait alors dans DocuFlow).
    """
    personne = destinataire(niveau)
    if personne is None or not config.lire("APPROBATION_SECRET", ""):
        return False
    session.info.setdefault(CLE_SESSION, []).append((facture.id, niveau, personne, rappel))
    return True


def envoyer_en_attente(session: Session, fabrique_session: Callable[[], Session], envoyer: Callable[[Message], dict] = envoyer_par_resend) -> None:
    """À appeler juste après session.commit() : envoie les mails préparés et note le résultat au journal."""
    from moteur.workflow import MOTEUR, _journaliser  # import ici : workflow importe ce module

    for facture_id, niveau, personne, rappel in session.info.pop(CLE_SESSION, []):
        with fabrique_session() as autre:
            facture = autre.get(FactureEnBase, facture_id)
            detail = {"niveau": niveau, "destinataire": personne, **({"rappel": rappel} if rappel else {})}
            try:
                resultat = envoyer(composer(facture, niveau, personne, rappel))
                _journaliser(autre, facture, "NOTIFICATION", MOTEUR, {**detail, "id": resultat.get("id")})
            except Exception as erreur:  # noqa: BLE001 - un mail raté ne doit jamais casser le parcours
                journal.warning("Mail d'approbation non envoyé (%s, %s) : %s", facture_id, niveau, erreur)
                _journaliser(autre, facture, "NOTIFICATION_ECHOUEE", MOTEUR, {**detail, "raison": str(erreur)[:300]})
            autre.commit()
