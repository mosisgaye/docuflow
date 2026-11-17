"""Le serveur MCP de Verifac : Claude (claude.ai, Claude Desktop, Claude Code) lit les factures du client.

Ce que Claude peut faire : LIRE, au nom de la personne qui a donné son accord, avec les droits de son compte.
Rien n'est approuvé, rejeté, modifié ni exporté par ce chemin : les décisions restent dans Verifac.

La connexion suit ce que Claude exige (https://claude.com/docs/connectors/building/authentication) :
1. sans jeton, /mcp répond 401 avec « WWW-Authenticate: Bearer resource_metadata=… » ;
2. Claude lit les métadonnées (RFC 9728, puis RFC 8414), s'enregistre tout seul (RFC 7591) ;
3. la personne arrive sur la page d'accord de Verifac (/oauth/consentement), se connecte par mail et code
   si besoin, voit qui demande l'accès et vers quelle adresse il repart, puis accepte ou refuse ;
4. Claude échange le code (PKCE S256 obligatoire) contre un jeton d'accès d'une heure et un jeton de
   renouvellement de 30 jours, remplacé à chaque usage.

Les routes OAuth et le transport MCP viennent du SDK officiel (mcp) ; ce module fournit le stockage
(empreintes en base, jamais les jetons eux-mêmes), la page d'accord et les outils.

Adresses publiques (VERIFAC_ADRESSE + /api, car Vercel renvoie /api/* au moteur) :
- serveur MCP : https://verifac.company/api/mcp
- émetteur OAuth : https://verifac.company/api (autorisation /api/authorize, jeton /api/token, enregistrement /api/register)
- les adresses /.well-known/* à la racine de verifac.company sont renvoyées au moteur par vercel.json.
"""

import base64
import hashlib
import hmac
import html
import json
import secrets
import time
import uuid
from collections.abc import Callable
from typing import Any
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import MCPServer
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from mcp_types import ToolAnnotations
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from moteur import comptes, config
from moteur.base import ClientOAuth, CodeOAuth, Compte, Etat, FactureEnBase, JetonOAuth

PORTEE = "factures:lire"
DUREE_DEMANDE = 600  # secondes pour donner son accord
DUREE_CODE = timedelta(minutes=5)
DUREE_ACCES = timedelta(hours=1)
DUREE_RENOUVELLEMENT = timedelta(days=30)
LECTURE = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def adresse_api() -> str:
    """L'adresse publique du moteur : https://verifac.company/api en production, http://localhost:5180/api en local."""
    return config.lire("VERIFAC_ADRESSE", "http://localhost:5180").rstrip("/") + "/api"


def _empreinte(valeur: str) -> str:
    return hashlib.sha256(valeur.encode()).hexdigest()


def _maintenant() -> datetime:
    return datetime.now(UTC)


# ───────── La demande d'accord, signée : elle voyage dans l'adresse de la page d'accord ─────────


def signer_demande(donnees: dict) -> str:
    charge = base64.urlsafe_b64encode(json.dumps({**donnees, "e": int(time.time()) + DUREE_DEMANDE}).encode()).decode().rstrip("=")
    signature = hmac.new(comptes._secret(), charge.encode(), hashlib.sha256).hexdigest()
    return f"{charge}.{signature}"


def lire_demande(valeur: str) -> dict | None:
    """La demande si la signature est bonne et qu'elle n'a pas expiré, sinon None."""
    if not valeur or "." not in valeur:
        return None
    charge, signature = valeur.rsplit(".", 1)
    if not hmac.compare_digest(signature, hmac.new(comptes._secret(), charge.encode(), hashlib.sha256).hexdigest()):
        return None
    try:
        donnees = json.loads(base64.urlsafe_b64decode(charge + "=" * (-len(charge) % 4)))
    except ValueError:
        return None
    return donnees if donnees.get("e", 0) >= time.time() else None


# ───────── Le stockage OAuth : clients, codes et jetons, en base, par empreinte ─────────


class Fournisseur:
    """Le serveur d'autorisation OAuth de Verifac, tel que le SDK MCP l'appelle (OAuthAuthorizationServerProvider)."""

    def __init__(self, fabrique_session: Callable[[], Session]):
        self.fabrique_session = fabrique_session

    @contextmanager
    def _session(self):
        with self.fabrique_session() as session:
            yield session
            session.commit()

    # Clients
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self._session() as session:
            client = session.get(ClientOAuth, client_id)
            return OAuthClientInformationFull.model_validate(client.infos) if client else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        with self._session() as session:
            session.merge(ClientOAuth(client_id=client_info.client_id, infos=client_info.model_dump(mode="json", exclude_none=True)))

    # Autorisation : on envoie la personne sur la page d'accord de Verifac
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        demande = signer_demande(
            {
                "c": client.client_id,
                "n": client.client_name or "Une application",
                "r": str(params.redirect_uri),
                "x": params.redirect_uri_provided_explicitly,
                "p": params.code_challenge,
                "s": params.state,
                "o": [PORTEE],
                "res": params.resource,
            }
        )
        return f"{adresse_api()}/oauth/consentement?demande={demande}"

    # Codes
    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> AuthorizationCode | None:
        with self._session() as session:
            code = session.get(CodeOAuth, _empreinte(authorization_code))
            if code is None or code.client_id != client.client_id or code.utilise_le is not None or code.expire_le < _maintenant():
                return None
            return AuthorizationCode(
                code=authorization_code,
                scopes=code.scopes,
                expires_at=code.expire_le.timestamp(),
                client_id=code.client_id,
                code_challenge=code.code_challenge,
                redirect_uri=code.redirect_uri,
                redirect_uri_provided_explicitly=code.redirect_explicite,
                resource=code.resource,
                subject=str(code.compte_id),
            )

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        with self._session() as session:
            # Usage unique, même si deux échanges arrivent en même temps : seule la ligne encore libre est prise.
            pris = session.execute(
                update(CodeOAuth)
                .where(CodeOAuth.empreinte == _empreinte(authorization_code.code), CodeOAuth.utilise_le.is_(None))
                .values(utilise_le=_maintenant())
            ).rowcount
            if not pris:
                raise TokenError("invalid_grant", "Ce code a déjà servi.")
            return self._donner_jetons(session, client.client_id, uuid.UUID(authorization_code.subject), authorization_code.scopes, authorization_code.resource)

    # Jetons
    def _donner_jetons(self, session: Session, client_id: str, compte_id: uuid.UUID, scopes: list[str], resource: str | None) -> OAuthToken:
        acces, renouvellement = f"vfa_{secrets.token_urlsafe(32)}", f"vfr_{secrets.token_urlsafe(32)}"
        maintenant = _maintenant()
        for valeur, sorte, duree in ((acces, "acces", DUREE_ACCES), (renouvellement, "renouvellement", DUREE_RENOUVELLEMENT)):
            session.add(
                JetonOAuth(
                    empreinte=_empreinte(valeur), sorte=sorte, client_id=client_id, compte_id=compte_id, scopes=scopes, resource=resource, expire_le=maintenant + duree
                )
            )
        return OAuthToken(access_token=acces, token_type="Bearer", expires_in=int(DUREE_ACCES.total_seconds()), refresh_token=renouvellement, scope=" ".join(scopes))

    def _jeton_valable(self, session: Session, valeur: str, sorte: str) -> JetonOAuth | None:
        jeton = session.get(JetonOAuth, _empreinte(valeur))
        if jeton is None or jeton.sorte != sorte or jeton.revoque_le is not None or jeton.expire_le < _maintenant():
            return None
        compte = session.get(Compte, jeton.compte_id)
        return jeton if compte is not None and compte.actif else None  # un compte désactivé coupe aussi Claude

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        with self._session() as session:
            jeton = self._jeton_valable(session, refresh_token, "renouvellement")
            if jeton is None or jeton.client_id != client.client_id:
                return None
            return RefreshToken(
                token=refresh_token, client_id=jeton.client_id, scopes=jeton.scopes, expires_at=int(jeton.expire_le.timestamp()), resource=jeton.resource, subject=str(jeton.compte_id)
            )

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        with self._session() as session:
            # Rotation : l'ancien jeton de renouvellement ne sert qu'une fois.
            pris = session.execute(
                update(JetonOAuth).where(JetonOAuth.empreinte == _empreinte(refresh_token.token), JetonOAuth.revoque_le.is_(None)).values(revoque_le=_maintenant())
            ).rowcount
            if not pris:
                raise TokenError("invalid_grant", "Ce jeton de renouvellement a déjà servi.")
            return self._donner_jetons(session, client.client_id, uuid.UUID(refresh_token.subject), scopes or refresh_token.scopes, refresh_token.resource)

    async def load_access_token(self, token: str) -> AccessToken | None:
        with self._session() as session:
            jeton = self._jeton_valable(session, token, "acces")
            if jeton is None:
                return None
            return AccessToken(
                token=token, client_id=jeton.client_id, scopes=jeton.scopes, expires_at=int(jeton.expire_le.timestamp()), resource=jeton.resource, subject=str(jeton.compte_id)
            )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        with self._session() as session:
            session.execute(update(JetonOAuth).where(JetonOAuth.empreinte == _empreinte(token.token)).values(revoque_le=_maintenant()))


def donner_code(session: Session, demande: dict, compte: Compte) -> str:
    """Après l'accord de la personne : le code à rendre à Claude, valable 5 minutes et une seule fois."""
    code = f"vfc_{secrets.token_urlsafe(32)}"
    session.add(
        CodeOAuth(
            empreinte=_empreinte(code),
            client_id=demande["c"],
            compte_id=compte.id,
            scopes=demande["o"],
            code_challenge=demande["p"],
            redirect_uri=demande["r"],
            redirect_explicite=bool(demande["x"]),
            resource=demande.get("res"),
            expire_le=_maintenant() + DUREE_CODE,
        )
    )
    return construct_redirect_uri(demande["r"], code=code, state=demande.get("s"))


def refuser(demande: dict) -> str:
    return construct_redirect_uri(demande["r"], error="access_denied", error_description="La personne a refusé l'accès.", state=demande.get("s"))


# ───────── La page d'accord ─────────


def page_consentement(demande_signee: str, demande: dict | None, compte: Compte | None) -> str:
    """Une page autonome : connexion par mail et code si besoin, puis Autoriser / Refuser."""
    e = html.escape
    if demande is None:
        corps = "<h1>Demande expirée</h1><p>Cette demande d'accès a expiré ou n'est pas valable. Recommencez depuis Claude.</p>"
    elif compte is None:
        corps = f"""
<h1>Connectez-vous à Verifac</h1>
<p><strong>{e(demande["n"])}</strong> demande à lire vos factures. Connectez-vous d'abord : vous recevrez un code par mail.</p>
<form id="mail"><label>Adresse mail<input name="email" type="email" required autocomplete="email"></label><button>Recevoir un code</button></form>
<form id="code" hidden><label>Code reçu par mail<input name="code" inputmode="numeric" autocomplete="one-time-code" required></label><button>Se connecter</button></form>
<p id="message" role="status"></p>
<script>
const message = document.getElementById('message'); let email = '';
document.getElementById('mail').onsubmit = async (ev) => {{ ev.preventDefault(); email = ev.target.email.value.trim();
  const r = await fetch('{adresse_api()}/connexion/demande', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{email}})}});
  message.textContent = r.ok ? 'Si cette adresse a un compte, un code vient de partir.' : 'Envoi impossible, réessayez.';
  if (r.ok) {{ ev.target.hidden = true; document.getElementById('code').hidden = false; }} }};
document.getElementById('code').onsubmit = async (ev) => {{ ev.preventDefault();
  const r = await fetch('{adresse_api()}/connexion/code', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{email, code: ev.target.code.value.replace(/\\s/g, '')}})}});
  if (r.ok) location.reload(); else message.textContent = 'Code refusé ou expiré.'; }};
</script>"""
    else:
        hote = e(demande["r"].split("/")[2] if "://" in demande["r"] else demande["r"])
        corps = f"""
<h1>Autoriser {e(demande["n"])} ?</h1>
<p><strong>{e(demande["n"])}</strong> demande à <strong>lire</strong> les factures Verifac auxquelles votre compte a accès
({e(compte.nom)}, {e(comptes.LIBELLES_ROLES[compte.role].lower())}) : leur état, leurs montants, leurs anomalies et leur journal.</p>
<ul><li>Rien ne pourra être approuvé, rejeté, modifié ni envoyé en comptabilité.</li><li>L'accès s'arrête dès que votre compte est déconnecté de partout, change de rôle ou est désactivé (Réglages › Mon équipe).</li></ul>
<p class="hote">Vous serez renvoyé vers <strong>{hote}</strong>.</p>
<form method="post"><input type="hidden" name="demande" value="{e(demande_signee)}">
<button name="decision" value="autoriser">Autoriser</button> <button name="decision" value="refuser" class="second">Refuser</button></form>"""
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Verifac · Autoriser l'accès</title>
<style>
:root {{ color-scheme: light dark; --fond: #f7f8f6; --carte: #fff; --texte: #1d2320; --texte-2: #55605a; --vert: #11704a; --trait: #dde2de; }}
@media (prefers-color-scheme: dark) {{ :root {{ --fond: #121513; --carte: #1a1e1c; --texte: #e8ece9; --texte-2: #a3aea7; --vert: #1f9d68; --trait: #2c332f; }} }}
body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--fond); color: var(--texte); font: 15px/1.55 system-ui, sans-serif; }}
main {{ width: min(30rem, calc(100% - 32px)); background: var(--carte); border: 1px solid var(--trait); border-radius: 12px; padding: 1.5rem; }}
h1 {{ font-size: 1.25rem; margin: 0 0 .75rem; }} p, li {{ color: var(--texte-2); }} strong {{ color: var(--texte); }}
.hote {{ padding: .5rem .75rem; border-radius: 8px; border: 1px solid var(--trait); }}
label {{ display: grid; gap: .3rem; margin: .75rem 0; font-weight: 500; }}
input {{ font: inherit; padding: .55rem .7rem; border: 1px solid var(--trait); border-radius: 8px; background: transparent; color: inherit; }}
button {{ font: inherit; font-weight: 600; padding: .6rem 1.1rem; border-radius: 8px; border: 0; background: var(--vert); color: #fff; cursor: pointer; min-height: 44px; }}
button.second {{ background: transparent; color: var(--texte); border: 1px solid var(--trait); }}
</style></head><body><main><p style="margin:0 0 1rem;font-weight:700;color:var(--vert)">Verifac</p>{corps}</main></body></html>"""


# ───────── Les outils, en lecture seule ─────────


def _compte_courant(session: Session) -> Compte:
    jeton = get_access_token()
    compte = session.get(Compte, uuid.UUID(jeton.subject)) if jeton and jeton.subject else None
    if compte is None or not compte.actif or not comptes.peut(compte, "voir"):
        raise PermissionError("Ce compte n'a plus accès aux factures.")
    return compte


def _visible(session: Session, compte: Compte, facture: FactureEnBase) -> bool:
    """Même règle que dans Verifac : un approbateur ne voit que son tour et ce qu'il a approuvé."""
    if compte.role != "approbateur":
        return True
    from moteur.approbation import approbations_valides, niveau_attendu

    moi = compte.nom.strip().casefold()
    return niveau_attendu(session, facture) in (compte.niveaux or []) or any(a.personne.strip().casefold() == moi for a in approbations_valides(session, facture))


def creer_serveur(fabrique_session: Callable[[], Session]) -> tuple[MCPServer, Fournisseur]:
    fournisseur = Fournisseur(fabrique_session)
    base = adresse_api()
    serveur = MCPServer(
        name="Verifac",
        instructions=(
            "Verifac traite les factures fournisseurs d'une entreprise : lecture, contrôles, circuit d'approbation. "
            "Ces outils LISENT seulement. Pour approuver ou rejeter, la personne passe par Verifac. "
            "Montants en euros ; états : recue, extraite, a_valider, en_approbation, en_anomalie, validee, rejetee, exportee, echec."
        ),
        auth_server_provider=fournisseur,  # le SDK en tire aussi le vérificateur des jetons de /mcp
        auth=AuthSettings(
            issuer_url=base,
            resource_server_url=f"{base}/mcp",
            required_scopes=[PORTEE],
            client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=[PORTEE], default_scopes=[PORTEE]),
            revocation_options=RevocationOptions(enabled=True),
            validate_token_resource=False,
        ),
    )

    def avec_session(lire: Callable[[Session, Compte], object]) -> object:
        with fabrique_session() as session:
            return lire(session, _compte_courant(session))

    @serveur.tool(annotations=LECTURE, structured_output=True)
    def lister_factures(etat: str | None = None, fournisseur: str | None = None, limite: int = 20) -> dict[str, Any]:
        """Les factures, des plus récentes aux plus anciennes. Filtres facultatifs : état (a_valider, en_anomalie,
        validee…) et nom du fournisseur (une partie suffit). 50 au plus."""
        from moteur.api import _publique

        def lire(session: Session, compte: Compte) -> dict:
            requete = select(FactureEnBase).order_by(FactureEnBase.cree_le.desc())
            if etat:
                requete = requete.where(FactureEnBase.etat == etat)
            if fournisseur:
                requete = requete.where(FactureEnBase.donnees["fournisseur_nom"].astext.ilike(f"%{fournisseur.strip()}%"))
            vues = [_publique(f) for f in session.scalars(requete.limit(200)) if _visible(session, compte, f)]
            return {"factures": vues[: max(1, min(limite, 50))], "total": len(vues)}

        return avec_session(lire)

    @serveur.tool(annotations=LECTURE, structured_output=True)
    def lire_facture(reference: str) -> dict[str, Any]:
        """Une facture en détail : données lues, anomalies et journal complet. « reference » est son numéro
        (par exemple F26-1240) ou son identifiant."""
        from moteur.api import _publique

        def lire(session: Session, compte: Compte) -> dict:
            facture = None
            try:
                facture = session.get(FactureEnBase, uuid.UUID(reference))
            except ValueError:
                facture = session.scalars(select(FactureEnBase).where(FactureEnBase.numero_facture == reference.strip()).order_by(FactureEnBase.cree_le.desc())).first()
            if facture is None or not _visible(session, compte, facture):
                return {"erreur": f"Aucune facture « {reference} »."}
            return _publique(facture, complete=True)

        return avec_session(lire)

    @serveur.tool(annotations=LECTURE, structured_output=True)
    def factures_a_approuver() -> dict[str, Any]:
        """Les factures qui attendent l'approbation de la personne connectée, à son niveau (comptable,
        directeur financier, gérant)."""
        from moteur.api import _publique
        from moteur.approbation import niveau_attendu

        def lire(session: Session, compte: Compte) -> dict:
            en_attente = session.scalars(select(FactureEnBase).where(FactureEnBase.etat.in_([Etat.A_VALIDER.value, Etat.EN_APPROBATION.value])).order_by(FactureEnBase.cree_le))
            mien = [{**_publique(f), "niveau_attendu": n} for f in en_attente if (n := niveau_attendu(session, f)) in (compte.niveaux or [])]
            return {"approbateur": compte.nom, "niveaux": compte.niveaux, "factures": mien}

        return avec_session(lire)

    @serveur.tool(annotations=LECTURE, structured_output=True)
    def resume() -> dict[str, Any]:
        """Le point sur les factures : nombre par état, montant TTC qui attend une décision, factures en anomalie."""

        def lire(session: Session, compte: Compte) -> dict:
            factures = [f for f in session.scalars(select(FactureEnBase)) if _visible(session, compte, f)]
            par_etat: dict[str, int] = {}
            for f in factures:
                par_etat[f.etat] = par_etat.get(f.etat, 0) + 1
            en_decision = [f for f in factures if f.etat in (Etat.A_VALIDER.value, Etat.EN_APPROBATION.value)]
            montant = sum(float((f.donnees or {}).get("total_ttc") or 0) for f in en_decision)
            return {"factures": len(factures), "par_etat": par_etat, "ttc_en_attente_de_decision": round(montant, 2), "en_anomalie": par_etat.get(Etat.EN_ANOMALIE.value, 0)}

        return avec_session(lire)

    return serveur, fournisseur


def jetons_actifs(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(JetonOAuth).where(JetonOAuth.revoque_le.is_(None), JetonOAuth.expire_le > _maintenant())) or 0
