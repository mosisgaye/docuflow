"""Le connecteur Claude de bout en bout : découverte, enregistrement, accord, jetons, outils en lecture seule."""

import base64
import hashlib
import secrets
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from moteur import comptes
from moteur.api import creer_application
from moteur.base import FactureEnBase

RETOUR_CLAUDE = "https://claude.ai/api/mcp/auth_callback"
ENTETES_MCP = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def reglages(monkeypatch):
    monkeypatch.setenv("VERIFAC_SECRET_SESSION", "s" * 40)
    monkeypatch.setenv("VERIFAC_ADRESSE", "http://localhost:5180")


@pytest.fixture
def monde(connexion, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    with fabrique() as session:
        claire = comptes.creer(session, "Claire Fabre", "claire@exemple.fr", "membre", ["comptable"], "test")
        paul = comptes.creer(session, "Paul Mercier", "paul@exemple.fr", "approbateur", ["gerant"], "test")
        session.add(
            FactureEnBase(
                empreinte=uuid.uuid4().hex,
                nom_fichier="f.pdf",
                etat="a_valider",
                numero_facture="F26-1240",
                fournisseur_siret="12345678901234",
                donnees={"fournisseur_nom": "Garage Central Bertin", "total_ttc": "576.00", "date_echeance": "2026-12-01"},
                anomalies=[],
            )
        )
        session.commit()
        ids = {"claire": claire.id, "paul": paul.id}
    application = creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path, odoo=None)
    with TestClient(application, base_url="http://localhost:5180") as client:
        yield client, fabrique, ids


def pkce() -> tuple[str, str]:
    verificateur = secrets.token_urlsafe(48)
    defi = base64.urlsafe_b64encode(hashlib.sha256(verificateur.encode()).digest()).decode().rstrip("=")
    return verificateur, defi


def connecter_claude(client, fabrique, compte_id, decision="autoriser") -> dict:
    """Le parcours que suit Claude : s'enregistrer, demander l'accès, recevoir le code, l'échanger."""
    enregistre = client.post("/register", json={"client_name": "Claude", "redirect_uris": [RETOUR_CLAUDE], "token_endpoint_auth_method": "none"})
    assert enregistre.status_code == 201, enregistre.text
    client_id = enregistre.json()["client_id"]
    verificateur, defi = pkce()
    autorisation = client.get(
        "/authorize",
        params={"response_type": "code", "client_id": client_id, "redirect_uri": RETOUR_CLAUDE, "code_challenge": defi, "code_challenge_method": "S256", "state": "etat-1"},
        follow_redirects=False,
    )
    assert autorisation.status_code == 302, autorisation.text
    page = urlparse(autorisation.headers["location"])
    assert page.path == "/api/oauth/consentement"
    demande = parse_qs(page.query)["demande"][0]

    # La personne est connectée à Verifac : elle voit qui demande, et vers où elle repart.
    with fabrique() as session:
        client.cookies.set(comptes.COOKIE, comptes.jeton_session(session.get(comptes.Compte, compte_id)))
    affichee = client.get("/oauth/consentement", params={"demande": demande})
    assert "Autoriser Claude" in affichee.text and "claude.ai" in affichee.text

    reponse = client.post("/oauth/consentement", data={"demande": demande, "decision": decision}, follow_redirects=False)
    client.cookies.clear()
    retour = urlparse(reponse.headers["location"])
    assert f"{retour.scheme}://{retour.netloc}{retour.path}" == RETOUR_CLAUDE
    parametres = parse_qs(retour.query)
    assert parametres["state"] == ["etat-1"]
    if decision != "autoriser":
        return {"refus": parametres["error"][0]}
    jetons = client.post(
        "/token",
        data={"grant_type": "authorization_code", "code": parametres["code"][0], "redirect_uri": RETOUR_CLAUDE, "client_id": client_id, "code_verifier": verificateur},
    )
    assert jetons.status_code == 200, jetons.text
    return {**jetons.json(), "client_id": client_id, "code": parametres["code"][0], "verificateur": verificateur}


def appeler(client, jeton: str, methode: str, params: dict | None = None):
    return client.post("/mcp", headers={**ENTETES_MCP, "Authorization": f"Bearer {jeton}"}, json={"jsonrpc": "2.0", "id": 1, "method": methode, "params": params or {}})


def outil(client, jeton: str, nom: str, arguments: dict | None = None) -> dict:
    reponse = appeler(client, jeton, "tools/call", {"name": nom, "arguments": arguments or {}})
    assert reponse.status_code == 200, reponse.text
    resultat = reponse.json()["result"]
    assert not resultat.get("isError"), resultat
    return resultat["structuredContent"]


def test_sans_jeton_claude_est_renvoye_vers_la_decouverte(monde):
    client, _, _ = monde
    reponse = client.post("/mcp", headers=ENTETES_MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert reponse.status_code == 401
    assert 'resource_metadata="http://localhost:5180/.well-known/oauth-protected-resource/api/mcp"' in reponse.headers["www-authenticate"]
    ressource = client.get("/.well-known/oauth-protected-resource/api/mcp").json()
    assert ressource["resource"] == "http://localhost:5180/api/mcp" and ressource["authorization_servers"] == ["http://localhost:5180/api"]
    emetteur = client.get("/.well-known/oauth-authorization-server/api").json()
    assert emetteur["issuer"] == "http://localhost:5180/api"
    assert emetteur["code_challenge_methods_supported"] == ["S256"] and emetteur["registration_endpoint"] == "http://localhost:5180/api/register"


def test_le_parcours_complet_puis_les_outils_en_lecture(monde):
    client, fabrique, ids = monde
    jetons = connecter_claude(client, fabrique, ids["claire"])
    assert jetons["token_type"].lower() == "bearer" and jetons["scope"] == "factures:lire"

    noms = {o["name"] for o in appeler(client, jetons["access_token"], "tools/list").json()["result"]["tools"]}
    assert noms == {"lister_factures", "lire_facture", "factures_a_approuver", "resume"}

    liste = outil(client, jetons["access_token"], "lister_factures", {"fournisseur": "bertin"})
    assert [f["numero"] for f in liste["factures"]] == ["F26-1240"]
    detail = outil(client, jetons["access_token"], "lire_facture", {"reference": "F26-1240"})
    assert detail["fournisseur"] == "Garage Central Bertin" and "journal" in detail
    assert outil(client, jetons["access_token"], "resume")["par_etat"] == {"a_valider": 1}


def test_le_code_ne_sert_qu_une_fois(monde):
    client, fabrique, ids = monde
    jetons = connecter_claude(client, fabrique, ids["claire"])
    rejoue = client.post(
        "/token",
        data={"grant_type": "authorization_code", "code": jetons["code"], "redirect_uri": RETOUR_CLAUDE, "client_id": jetons["client_id"], "code_verifier": jetons["verificateur"]},
    )
    assert rejoue.status_code == 400 and rejoue.json()["error"] == "invalid_grant"


def test_le_renouvellement_remplace_l_ancien_jeton(monde):
    client, fabrique, ids = monde
    jetons = connecter_claude(client, fabrique, ids["claire"])
    nouveau = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": jetons["refresh_token"], "client_id": jetons["client_id"]})
    assert nouveau.status_code == 200 and nouveau.json()["refresh_token"] != jetons["refresh_token"]
    assert appeler(client, nouveau.json()["access_token"], "tools/list").status_code == 200
    # L'ancien jeton de renouvellement ne sert plus.
    rejoue = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": jetons["refresh_token"], "client_id": jetons["client_id"]})
    assert rejoue.status_code == 400 and rejoue.json()["error"] == "invalid_grant"


def test_un_refus_ne_donne_rien(monde):
    client, fabrique, ids = monde
    assert connecter_claude(client, fabrique, ids["claire"], decision="refuser") == {"refus": "access_denied"}


def test_un_compte_desactive_coupe_claude(monde):
    client, fabrique, ids = monde
    jetons = connecter_claude(client, fabrique, ids["claire"])
    with fabrique() as session:
        session.get(comptes.Compte, ids["claire"]).actif = False
        session.commit()
    assert appeler(client, jetons["access_token"], "tools/list").status_code == 401


def test_un_approbateur_ne_voit_que_son_tour(monde):
    client, fabrique, ids = monde
    # Paul approuve au niveau gérant ; sans règle publiée, la facture attend le comptable : il ne la voit pas.
    jetons = connecter_claude(client, fabrique, ids["paul"])
    assert outil(client, jetons["access_token"], "lister_factures")["factures"] == []
    assert "erreur" in outil(client, jetons["access_token"], "lire_facture", {"reference": "F26-1240"})


def test_sans_session_la_page_demande_de_se_connecter(monde):
    client, _, _ = monde
    enregistre = client.post("/register", json={"client_name": "Claude", "redirect_uris": [RETOUR_CLAUDE], "token_endpoint_auth_method": "none"}).json()
    _, defi = pkce()
    autorisation = client.get(
        "/authorize",
        params={"response_type": "code", "client_id": enregistre["client_id"], "redirect_uri": RETOUR_CLAUDE, "code_challenge": defi, "code_challenge_method": "S256"},
        follow_redirects=False,
    )
    demande = parse_qs(urlparse(autorisation.headers["location"]).query)["demande"][0]
    page = client.get("/oauth/consentement", params={"demande": demande})
    assert "Connectez-vous à Verifac" in page.text
    # Sans session, impossible de forcer l'accord.
    assert client.post("/oauth/consentement", data={"demande": demande, "decision": "autoriser"}, follow_redirects=False).status_code == 400


def test_deconnecter_partout_coupe_aussi_claude(monde):
    client, fabrique, ids = monde
    jetons = connecter_claude(client, fabrique, ids["claire"])
    with fabrique() as session:
        comptes.deconnecter_partout(session, session.get(comptes.Compte, ids["claire"]))
        session.commit()
    assert appeler(client, jetons["access_token"], "tools/list").status_code == 401
    # Le jeton de renouvellement tombe aussi : Claude doit redemander l'accord.
    renouvele = client.post("/token", data={"grant_type": "refresh_token", "refresh_token": jetons["refresh_token"], "client_id": jetons["client_id"]})
    assert renouvele.status_code == 400 and renouvele.json()["error"] == "invalid_grant"
