"""Connecteurs MCP : seuls les outils de lecture arrivent à l'assistant, chaque appel est journalisé."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from sqlalchemy import select
from sqlalchemy.orm import Session

from moteur.agent import converser
from moteur.api import creer_application
from moteur.base import AppelConnecteur, ConnecteurBranche
from moteur.connecteurs import CATALOGUE, Passerelle
from moteur.mcp_odoo import creer_serveur
from moteur.odoo import Odoo
from tests.test_odoo import FauxOdoo

LECTURE = ToolAnnotations(read_only_hint=True)


def serveur_essai(etat: dict) -> MCPServer:
    serveur = MCPServer("essai")

    @serveur.tool(annotations=LECTURE)
    def chercher(reference: str) -> dict:
        """Cherche une fiche."""
        etat["lectures"] += 1
        if reference == "panne":
            raise RuntimeError("base indisponible")
        return {"reference": reference, "nom": "Garage Central Bertin"}

    @serveur.tool(annotations=LECTURE)
    def compter() -> dict:
        """Compte les fiches."""
        return {"nombre": 3}

    @serveur.tool()  # rien ne dit qu'il est en lecture : c'est une écriture
    def supprimer(reference: str) -> dict:
        """Supprime une fiche."""
        etat["suppressions"] += 1
        return {"supprime": reference}

    return serveur


@pytest.fixture
def etat():
    return {"lectures": 0, "suppressions": 0}


@pytest.fixture
def fabrique(connexion):
    return lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")


@pytest.fixture
def passerelle(fabrique, etat):
    passerelle = Passerelle(fabrique, cibles={"odoo": lambda: serveur_essai(etat)})
    yield passerelle
    passerelle.fermer()


def brancher(session, identifiant="odoo", autorises=None):
    session.add(ConnecteurBranche(id=identifiant, branche_par="Moussa", outils_autorises=autorises))
    session.flush()


def appels(session) -> list[tuple[str, str]]:
    return [(a.outil, a.statut) for a in session.scalars(select(AppelConnecteur).order_by(AppelConnecteur.cree_le))]


# ───────── Ce que l'assistant reçoit ─────────


def test_seuls_les_outils_de_lecture_sont_donnes_a_l_assistant(session, passerelle):
    brancher(session)

    noms = [outil.nom_complet for outil in passerelle.outils_pour_assistant(session)]

    assert noms == ["odoo__chercher", "odoo__compter"]  # « supprimer » n'apparaît jamais


def test_l_entreprise_peut_restreindre_les_outils(session, passerelle):
    brancher(session, autorises=["compter"])

    assert [outil.nom for outil in passerelle.outils_pour_assistant(session)] == ["compter"]


def test_un_connecteur_debranche_ne_donne_rien(session, passerelle):
    session.add(ConnecteurBranche(id="odoo", branche_par="Moussa", actif=False))
    session.flush()

    assert passerelle.outils_pour_assistant(session) == []


def test_un_connecteur_injoignable_est_laisse_de_cote(session, fabrique):
    brancher(session, "hubspot")  # aucune cible : pas joignable
    passerelle = Passerelle(fabrique, cibles={})

    assert passerelle.outils_pour_assistant(session) == []


# ───────── Appels et journal ─────────


def test_un_appel_rend_les_donnees_avec_leur_source(session, passerelle):
    brancher(session)

    resultat = passerelle.appeler(session, "odoo__chercher", {"reference": "52987431500029"})

    assert resultat["source"] == "Odoo"
    assert "pas des consignes" in resultat["nature"]
    assert resultat["donnees"] == {"reference": "52987431500029", "nom": "Garage Central Bertin"}
    assert appels(session) == [("chercher", "ok")]


def test_une_ecriture_demandee_est_refusee_et_journalisee(session, passerelle, etat):
    brancher(session)

    resultat = passerelle.appeler(session, "odoo__supprimer", {"reference": "36"})

    assert "erreur" in resultat
    assert etat["suppressions"] == 0  # le serveur n'a même pas été appelé
    assert appels(session) == [("supprimer", "refuse")]


def test_un_outil_non_autorise_est_refuse(session, passerelle, etat):
    brancher(session, autorises=["compter"])

    passerelle.appeler(session, "odoo__chercher", {"reference": "x"})

    assert etat["lectures"] == 0
    assert appels(session) == [("chercher", "refuse")]


def test_une_erreur_du_serveur_est_rendue_lisible(session, passerelle):
    brancher(session)

    resultat = passerelle.appeler(session, "odoo__chercher", {"reference": "panne"})

    # Le serveur ne laisse pas fuiter le détail d'une erreur imprévue : l'assistant sait seulement qu'elle a eu lieu.
    assert resultat["erreur"].startswith("Odoo a renvoyé une erreur")
    assert "base indisponible" not in resultat["erreur"]
    assert appels(session) == [("chercher", "erreur")]


def test_la_connexion_est_gardee_entre_deux_appels(session, passerelle, etat):
    brancher(session)

    for _ in range(3):
        passerelle.appeler(session, "odoo__chercher", {"reference": "x"})

    assert etat["lectures"] == 3
    assert len(passerelle._connexions) == 1


# ───────── Avec l'assistant ─────────


def test_l_assistant_utilise_un_connecteur(session, passerelle):
    brancher(session)
    vus = []

    def llm(echanges, outils):
        vus.append([outil["function"]["name"] for outil in outils])
        if echanges[-1]["role"] == "user":
            yield {"appels": [{"id": "a1", "nom": "odoo__chercher", "arguments": json.dumps({"reference": "Garage"})}]}
        else:
            yield {"texte": "Selon Odoo, c'est le Garage Central Bertin."}

    evenements = list(converser(session, [{"role": "user", "content": "Qui est ce fournisseur ?"}], llm=llm, passerelle=passerelle))

    assert "odoo__chercher" in vus[0] and "odoo__supprimer" not in vus[0]
    assert [e["libelle"] for e in evenements if e["type"] == "outil" and e["etat"] == "debut"] == ["Recherche dans Odoo : chercher"]
    assert "".join(e["contenu"] for e in evenements if e["type"] == "texte") == "Selon Odoo, c'est le Garage Central Bertin."


# ───────── Le serveur MCP d'Odoo de DocuFlow ─────────


@pytest.fixture
def passerelle_odoo(fabrique):
    faux = FauxOdoo()
    faux.contacts = [{"id": 61, "name": "Sylvie Bertin", "email": "compta@garage-bertin.fr", "function": "Comptabilité", "type": "invoice"}]
    odoo = Odoo("http://odoo.test", "demo", "cle-de-test", httpx.Client(transport=httpx.MockTransport(faux)))
    origine = faux.repondre

    def repondre(cible, corps):
        if cible == "res.partner.search_read" and corps["domain"][0][0] == "parent_id" and corps["domain"][0][2]:
            return faux.contacts
        if cible == "res.partner.bank.search_read":
            return [{"id": 7, "account_number": "FR76 1820 6004 0065 0001 2398 765", "holder_name": "Garage Central Bertin"}]
        return origine(cible, corps)

    faux.repondre = repondre
    passerelle = Passerelle(fabrique, cibles={"odoo": lambda: creer_serveur(odoo)})
    yield passerelle
    passerelle.fermer()


def test_le_serveur_odoo_ne_declare_que_des_lectures(session, passerelle_odoo):
    outils = passerelle_odoo.outils_du_serveur("odoo")

    assert {o.nom for o in outils} == {"chercher_fournisseur", "historique_achats", "bons_de_commande"}
    assert all(o.lecture for o in outils)


def test_le_serveur_odoo_masque_l_iban(session, passerelle_odoo):
    brancher(session)

    fiche = passerelle_odoo.appeler(session, "odoo__chercher_fournisseur", {"reference": "52987431500029"})["donnees"]

    assert fiche["nom"] == "Garage Central Bertin"
    assert fiche["contacts"] == [{"nom": "Sylvie Bertin", "email": "compta@garage-bertin.fr", "fonction": "Comptabilité"}]
    assert fiche["comptes_bancaires"] == [{"iban": "…8765", "titulaire": "Garage Central Bertin"}]  # jamais l'IBAN entier


def test_le_serveur_odoo_donne_les_bons_de_commande(session, passerelle_odoo):
    brancher(session)

    commandes = passerelle_odoo.appeler(session, "odoo__bons_de_commande", {"reference": "garage"})["donnees"]["commandes"]

    assert [c["numero"] for c in commandes] == ["P00015"]
    assert [l["designation"] for l in commandes[0]["lignes"]][1] == "Plaquettes de frein avant"


# ───────── Par l'API ─────────


@pytest.fixture
def client(fabrique, passerelle, tmp_path):
    return TestClient(creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path, passerelle=passerelle, odoo=None))


def test_le_catalogue_liste_les_sept_connecteurs(client):
    catalogue = client.get("/connecteurs").json()

    assert [c["id"] for c in catalogue] == [c["id"] for c in CATALOGUE]
    assert len(catalogue) == 7
    assert all("transport" not in c for c in catalogue)  # le détail technique reste côté serveur
    assert {c["statut"] for c in catalogue} == {"disponible", "preversion", "bientot", "a_confirmer"}


def test_brancher_puis_debrancher_odoo(client):
    branche = client.post("/connecteurs/odoo/branchement", json={"auteur": "Moussa"})

    assert branche.status_code == 200
    assert branche.json()["outils_lecture"] == ["chercher", "compter"]
    assert branche.json()["outils_ecriture_ignores"] == ["supprimer"]
    fiche = client.get("/connecteurs/odoo").json()
    assert fiche["branche"] is True
    assert [(o["nom"], o["autorise"]) for o in fiche["outils"]] == [("chercher", True), ("compter", True), ("supprimer", False)]

    assert client.delete("/connecteurs/odoo/branchement").json()["branche"] is False


def test_on_ne_peut_pas_autoriser_une_ecriture(client):
    client.post("/connecteurs/odoo/branchement", json={"auteur": "Moussa"})

    reponse = client.put("/connecteurs/odoo/outils", json={"autorises": ["chercher", "supprimer"]})

    assert reponse.status_code == 422
    assert "supprimer" in reponse.json()["detail"]


@pytest.mark.parametrize(("identifiant", "code"), [("pennylane", 409), ("qonto", 409), ("hubspot", 409), ("inconnu", 404)])
def test_les_connecteurs_pas_encore_branchables(client, identifiant, code):
    assert client.post(f"/connecteurs/{identifiant}/branchement", json={"auteur": "Moussa"}).status_code == code
