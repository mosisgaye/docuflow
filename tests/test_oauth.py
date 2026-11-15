"""Connexion d'un connecteur par compte (OAuth 2.1 + PKCE) : parcours, jetons chiffrés, renouvellement."""

import asyncio
import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import httpx2
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from moteur import oauth
from moteur.api import creer_application
from moteur.base import ConnecteurBranche, DemandeOAuth, JetonConnecteur
from moteur.connecteurs import Passerelle, _JetonOAuth
from tests.test_connecteurs import serveur_essai

ADRESSE = "https://mcp.hubspot.com"


class FauxEditeur:
    """Serveur d'autorisation d'un éditeur : métadonnées publiées, échange de code avec PKCE, renouvellement."""

    def __init__(self):
        self.defis: dict[str, str] = {}  # code → défi PKCE reçu à l'autorisation
        self.echanges, self.renouvellements = 0, 0
        self.refuser = False

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        if requete.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json={
                "authorization_endpoint": f"{ADRESSE}/oauth/authorize/user",
                "token_endpoint": f"{ADRESSE}/oauth/v3/token",
                "code_challenge_methods_supported": ["S256"],
            })
        if requete.url.path == "/oauth/v3/token":
            donnees = parse_qs(requete.content.decode())
            assert donnees["client_id"] == ["id-client"] and donnees["client_secret"] == ["secret-client"]
            if self.refuser:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "jeton-secret-dans-le-message"})
            if donnees["grant_type"] == ["authorization_code"]:
                # Le cœur de PKCE : le vérificateur doit redonner le défi envoyé au départ.
                attendu = self.defis[donnees["code"][0]]
                calcule = base64.urlsafe_b64encode(hashlib.sha256(donnees["code_verifier"][0].encode()).digest()).rstrip(b"=").decode()
                if calcule != attendu:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                self.echanges += 1
                return httpx.Response(200, json={"access_token": "acces-1", "refresh_token": "renouvellement-1", "expires_in": 1800})
            if donnees["grant_type"] == ["refresh_token"]:
                assert donnees["refresh_token"] == ["renouvellement-1"]
                self.renouvellements += 1
                return httpx.Response(200, json={"access_token": f"acces-{self.renouvellements + 1}", "expires_in": 1800})
        return httpx.Response(404)


@pytest.fixture(autouse=True)
def reglages(monkeypatch):
    monkeypatch.setenv("HUBSPOT_CLIENT_ID", "id-client")
    monkeypatch.setenv("HUBSPOT_CLIENT_SECRET", "secret-client")
    monkeypatch.setenv("CONNECTEURS_CLE_CHIFFREMENT", Fernet.generate_key().decode())
    monkeypatch.setenv("OAUTH_RETOUR", "http://localhost:5180/api/oauth/retour")


@pytest.fixture
def editeur():
    return FauxEditeur()


@pytest.fixture
def client_http(editeur):
    return httpx.Client(transport=httpx.MockTransport(editeur))


def autoriser(editeur: FauxEditeur, adresse: str) -> tuple[str, str]:
    """Ce que fait l'éditeur quand la personne accepte : il garde le défi et renvoie un code."""
    parametres = parse_qs(urlparse(adresse).query)
    assert parametres["code_challenge_method"] == ["S256"]
    assert parametres["redirect_uri"] == ["http://localhost:5180/api/oauth/retour"]
    assert parametres["resource"] == [ADRESSE]
    code = f"code-{len(editeur.defis)}"
    editeur.defis[code] = parametres["code_challenge"][0]
    return parametres["state"][0], code


# ───────── Le parcours ─────────


def test_le_parcours_complet_range_des_jetons_chiffres(session, editeur, client_http):
    adresse = oauth.commencer(session, "hubspot", ADRESSE, "Moussa", client_http)
    etat, code = autoriser(editeur, adresse)

    demande = oauth.terminer(session, etat, code, {"hubspot": ADRESSE}, client_http)

    assert (demande.connecteur, demande.auteur) == ("hubspot", "Moussa")
    enregistre = session.get(JetonConnecteur, "hubspot")
    assert "acces-1" not in enregistre.acces and "renouvellement-1" not in enregistre.renouvellement  # chiffrés en base
    assert oauth.jeton(session, "hubspot", ADRESSE, client_http) == "acces-1"
    assert session.get(DemandeOAuth, etat) is None  # un « state » ne sert qu'une fois


def test_un_state_ne_sert_qu_une_fois(session, editeur, client_http):
    etat, code = autoriser(editeur, oauth.commencer(session, "hubspot", ADRESSE, "Moussa", client_http))
    oauth.terminer(session, etat, code, {"hubspot": ADRESSE}, client_http)

    with pytest.raises(oauth.ErreurOAuth, match="déjà utilisée"):
        oauth.terminer(session, etat, code, {"hubspot": ADRESSE}, client_http)


def test_un_state_inconnu_est_refuse(session, client_http):
    with pytest.raises(oauth.ErreurOAuth):
        oauth.terminer(session, "invente", "code", {"hubspot": ADRESSE}, client_http)


def test_une_demande_trop_ancienne_est_refusee(session, editeur, client_http):
    etat, code = autoriser(editeur, oauth.commencer(session, "hubspot", ADRESSE, "Moussa", client_http))
    session.get(DemandeOAuth, etat).cree_le = datetime.now(UTC) - timedelta(minutes=11)

    with pytest.raises(oauth.ErreurOAuth, match="expiré"):
        oauth.terminer(session, etat, code, {"hubspot": ADRESSE}, client_http)


def test_un_mauvais_verificateur_pkce_est_refuse_par_l_editeur(session, editeur, client_http):
    etat, code = autoriser(editeur, oauth.commencer(session, "hubspot", ADRESSE, "Moussa", client_http))
    editeur.defis[code] = "defi-different"

    with pytest.raises(oauth.ErreurOAuth, match="refusé"):
        oauth.terminer(session, etat, code, {"hubspot": ADRESSE}, client_http)


def test_un_refus_de_l_editeur_ne_recopie_pas_son_message(session, editeur, client_http):
    etat, code = autoriser(editeur, oauth.commencer(session, "hubspot", ADRESSE, "Moussa", client_http))
    editeur.refuser = True

    with pytest.raises(oauth.ErreurOAuth) as erreur:
        oauth.terminer(session, etat, code, {"hubspot": ADRESSE}, client_http)
    assert "invalid_grant" in str(erreur.value) and "jeton-secret" not in str(erreur.value)


def test_sans_identifiants_rien_ne_commence(session, client_http, monkeypatch):
    monkeypatch.delenv("HUBSPOT_CLIENT_SECRET")

    with pytest.raises(oauth.ErreurOAuth, match="HUBSPOT_CLIENT_ID"):
        oauth.commencer(session, "hubspot", ADRESSE, "Moussa", client_http)
    assert oauth.pret("hubspot") is False


# ───────── Renouvellement ─────────


def connecter(session, editeur, client_http):
    etat, code = autoriser(editeur, oauth.commencer(session, "hubspot", ADRESSE, "Moussa", client_http))
    oauth.terminer(session, etat, code, {"hubspot": ADRESSE}, client_http)


def test_un_jeton_qui_expire_est_renouvele_tout_seul(session, editeur, client_http):
    connecter(session, editeur, client_http)
    session.get(JetonConnecteur, "hubspot").expire_le = datetime.now(UTC) + timedelta(seconds=30)  # dans la marge

    assert oauth.jeton(session, "hubspot", ADRESSE, client_http) == "acces-2"
    assert editeur.renouvellements == 1
    # Le jeton de renouvellement n'a pas été renvoyé : on garde l'ancien.
    assert oauth.jeton(session, "hubspot", ADRESSE, client_http, forcer=True) == "acces-3"


def test_un_jeton_valide_n_est_pas_renouvele(session, editeur, client_http):
    connecter(session, editeur, client_http)

    oauth.jeton(session, "hubspot", ADRESSE, client_http)

    assert editeur.renouvellements == 0


def test_une_cle_de_chiffrement_changee_demande_de_reconnecter(session, editeur, client_http, monkeypatch):
    connecter(session, editeur, client_http)
    monkeypatch.setenv("CONNECTEURS_CLE_CHIFFREMENT", Fernet.generate_key().decode())

    with pytest.raises(oauth.ErreurOAuth, match="Reconnectez"):
        oauth.jeton(session, "hubspot", ADRESSE, client_http)


def test_sur_un_refus_401_le_jeton_est_renouvele_et_la_requete_rejouee(connexion, editeur, client_http, monkeypatch):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    with fabrique() as session:
        connecter(session, editeur, client_http)
        session.commit()
    monkeypatch.setattr(oauth, "_appeler_jetons", lambda adresse, donnees, client: editeur_renouvelle(editeur))
    vus = []

    def serveur_mcp(requete):
        vus.append(requete.headers["Authorization"])
        return httpx2.Response(401 if requete.headers["Authorization"] == "Bearer acces-1" else 200, json={})

    async def appeler():
        client = httpx2.AsyncClient(auth=_JetonOAuth(fabrique, "hubspot", ADRESSE, "acces-1"), transport=httpx2.MockTransport(serveur_mcp))
        return await client.post(ADRESSE)

    reponse = asyncio.run(appeler())

    assert reponse.status_code == 200
    assert vus == ["Bearer acces-1", "Bearer acces-2"]


def editeur_renouvelle(editeur: FauxEditeur) -> dict:
    editeur.renouvellements += 1
    return {"access_token": f"acces-{editeur.renouvellements + 1}", "expires_in": 1800}


# ───────── Par l'API ─────────


@pytest.fixture
def api(connexion, client_http, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    passerelle = Passerelle(fabrique, cibles={"hubspot": lambda: serveur_essai({"lectures": 0, "suppressions": 0})})
    yield TestClient(creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path, passerelle=passerelle, odoo=None, client_oauth=client_http), follow_redirects=False)
    passerelle.fermer()


def test_par_l_api_le_compte_est_connecte_et_le_connecteur_branche(api, editeur, connexion):
    assert next(c for c in api.get("/connecteurs").json() if c["id"] == "hubspot")["connexion_prete"] is True

    depart = api.post("/connecteurs/hubspot/oauth", json={"auteur": "Moussa"}).json()["adresse"]
    assert depart.startswith(f"{ADRESSE}/oauth/authorize/user?")
    etat, code = autoriser(editeur, depart)

    retour = api.get("/oauth/retour", params={"state": etat, "code": code})

    assert retour.status_code == 303
    assert retour.headers["location"] == "http://localhost:5180/?oauth=ok&connecteur=hubspot"
    with Session(bind=connexion) as session:
        branche = session.get(ConnecteurBranche, "hubspot")
        assert (branche.actif, branche.branche_par) == (True, "Moussa")


def test_un_refus_chez_l_editeur_revient_sans_rien_brancher(api, connexion):
    retour = api.get("/oauth/retour", params={"error": "access_denied"})

    assert retour.headers["location"] == "http://localhost:5180/?oauth=refuse"
    with Session(bind=connexion) as session:
        assert session.scalars(select(ConnecteurBranche)).all() == []


def test_un_retour_avec_un_faux_state_echoue_proprement(api):
    retour = api.get("/oauth/retour", params={"state": "invente", "code": "x"})

    assert retour.headers["location"] == "http://localhost:5180/?oauth=echec"  # ni secret ni message dans l'adresse


def test_debrancher_efface_les_jetons(api, editeur, connexion):
    etat, code = autoriser(editeur, api.post("/connecteurs/hubspot/oauth", json={"auteur": "Moussa"}).json()["adresse"])
    api.get("/oauth/retour", params={"state": etat, "code": code})

    api.delete("/connecteurs/hubspot/branchement")

    with Session(bind=connexion) as session:
        assert session.get(JetonConnecteur, "hubspot") is None


def test_un_connecteur_par_cle_ne_passe_pas_par_oauth(api):
    assert api.post("/connecteurs/odoo/oauth", json={"auteur": "Moussa"}).status_code == 409
