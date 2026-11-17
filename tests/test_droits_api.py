"""Les droits par rôle, appliqués à toute l'API dès qu'un compte existe. Le compte connecté signe ses actions."""

import json
import pathlib

import pytest
from fastapi.testclient import TestClient
from graphes_exemples import circuit_simple
from sqlalchemy.orm import Session

from moteur import comptes
from moteur.api import creer_application
from moteur.approbation import REGLES_DEMO
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
MOYENNE = "facture-FA-2026-0412.pdf"  # 3 166,20 € TTC : comptable puis directeur financier

PERSONNES = {
    "admin": ("Moussa Gaye", "administrateur", ["gerant"]),
    "claire": ("Claire Fabre", "membre", ["comptable"]),
    "paul": ("Paul Mercier", "approbateur", ["directeur_financier"]),
    "expert": ("Cabinet Expert", "lecture", []),
    "support": ("Support Verifac", "operateur", []),
}


@pytest.fixture(autouse=True)
def secret(monkeypatch):
    monkeypatch.setenv("VERIFAC_SECRET_SESSION", "s" * 40)


@pytest.fixture
def monde(connexion, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    numeros = iter(f"FA-2026-{n:04d}" for n in range(900, 999))

    def extracteur(texte):
        return ResultatExtraction(Facture.model_validate({**ATTENDU[MOYENNE]["facture"], "numero_facture": next(numeros)}), 0.1, "test", "faux")

    jetons = {}
    with fabrique() as session:
        for cle, (nom, role, niveaux) in PERSONNES.items():
            compte = comptes.creer(session, nom, f"{cle}@exemple.fr", role, niveaux, "installation")
            jetons[cle] = comptes.jeton_session(compte)
        session.commit()
    application = creer_application(fabrique_session=fabrique, extracteur=extracteur, dossier_fichiers=tmp_path, traiter_tout_de_suite=True, odoo=None)

    def client(cle: str | None) -> TestClient:
        nouveau = TestClient(application)
        if cle:
            nouveau.cookies.set(comptes.COOKIE, jetons[cle])
        return nouveau

    admin = client("admin")
    admin.post("/regles", json={"auteur": "x", "regles": REGLES_DEMO})
    return client


def deposer(client, marque: str) -> str:
    contenu = (FACTURES / MOYENNE).read_bytes() + f"\n% {marque}\n".encode()
    return client.post("/factures", files={"fichier": (MOYENNE, contenu, "application/pdf")}).json()["id"]


# ───────── Sans session, rien ─────────


def test_sans_session_tout_demande_de_se_connecter(monde):
    anonyme = monde(None)

    reponse = anonyme.get("/factures")

    assert reponse.status_code == 401 and reponse.headers["X-Verifac-Connexion"] == "requise"
    assert anonyme.get("/sante").status_code == 200 and anonyme.get("/moi").status_code == 200  # restent ouverts


def test_une_session_falsifiee_ne_passe_pas(monde):
    faux = monde(None)
    faux.cookies.set(comptes.COOKIE, "abc.def")

    assert faux.get("/factures").status_code == 401


# ───────── Chaque rôle, ce qu'il peut et ne peut pas ─────────


@pytest.mark.parametrize(
    ("cle", "attendus"),
    [
        ("admin", {"voir": 200, "deposer": 201, "brouillon": 200, "publier": 201, "equipe": 201}),
        ("claire", {"voir": 200, "deposer": 201, "brouillon": 200, "publier": 403, "equipe": 403}),
        ("paul", {"voir": 200, "deposer": 403, "brouillon": 403, "publier": 403, "equipe": 403}),
        ("expert", {"voir": 200, "deposer": 403, "brouillon": 403, "publier": 403, "equipe": 403}),
        ("support", {"voir": 200, "deposer": 403, "brouillon": 403, "publier": 403, "equipe": 403}),
    ],
)
def test_chaque_role_a_ses_droits(monde, cle, attendus):
    client = monde(cle)
    contenu = (FACTURES / MOYENNE).read_bytes() + f"\n% {cle}\n".encode()

    obtenus = {
        "voir": client.get("/factures").status_code,
        "deposer": client.post("/factures", files={"fichier": (MOYENNE, contenu, "application/pdf")}).status_code,
        "brouillon": client.put("/circuit/brouillon", json={"auteur": "x", "graphe": circuit_simple()}).status_code,
        "publier": client.post("/circuit/publier", json={"auteur": "x"}).status_code,  # l'administrateur publie le brouillon qu'il vient d'écrire
        "equipe": client.post("/reglages/equipe", json={"nom": "N", "email": f"n-{cle}@exemple.fr", "niveau": "gerant", "auteur": "x"}).status_code,
    }

    assert obtenus == attendus


def test_l_agent_est_refuse_a_la_lecture_seule(monde):
    assert monde("expert").post("/agent", json={"messages": [{"role": "user", "content": "bonjour"}]}).status_code == 403


# ───────── Approuver : son niveau seulement, et c'est le compte qui signe ─────────


def test_le_compte_connecte_signe_meme_si_le_nom_envoye_est_faux(monde):
    claire = monde("claire")
    facture = deposer(claire, "signe")

    fiche = claire.post(f"/factures/{facture}/validation", json={"auteur": "Quelqu'un d'autre"}).json()

    assert fiche["approbations"][0]["personne"] == "Claire Fabre"


def test_on_n_approuve_que_son_niveau(monde):
    claire, paul, admin = monde("claire"), monde("paul"), monde("admin")
    facture = deposer(claire, "niveaux")

    assert admin.post(f"/factures/{facture}/validation", json={"auteur": "x"}).status_code == 403  # gérant : pas son tour
    assert claire.post(f"/factures/{facture}/validation", json={"auteur": "x"}).status_code == 200  # comptable
    assert claire.post(f"/factures/{facture}/validation", json={"auteur": "x"}).status_code == 403  # pas directeur financier
    assert paul.post(f"/factures/{facture}/validation", json={"auteur": "x"}).json()["etat"] == "validee"


def test_l_operateur_n_approuve_jamais(monde):
    facture = deposer(monde("claire"), "operateur")

    assert monde("support").post(f"/factures/{facture}/validation", json={"auteur": "x"}).status_code == 403


# ───────── L'approbateur ne voit que ses factures ─────────


def test_l_approbateur_ne_voit_que_les_factures_ou_il_intervient(monde):
    claire, paul = monde("claire"), monde("paul")
    a_son_tour = deposer(claire, "tour")
    pas_encore = deposer(claire, "pas-encore")
    claire.post(f"/factures/{a_son_tour}/validation", json={"auteur": "x"})  # passe au directeur financier

    visibles = {f["id"] for f in paul.get("/factures").json()}

    assert a_son_tour in visibles and pas_encore not in visibles
    assert paul.get(f"/factures/{pas_encore}").status_code == 404  # on ne dit même pas qu'elle existe
    assert paul.get(f"/factures/{pas_encore}/fichier").status_code == 404
    assert paul.post(f"/factures/{pas_encore}/rejet", json={"auteur": "x", "motif": "non"}).status_code == 404

    paul.post(f"/factures/{a_son_tour}/validation", json={"auteur": "x"})
    assert a_son_tour in {f["id"] for f in paul.get("/factures").json()}  # déjà approuvée par lui : il la voit encore


# ───────── Avec un code d'accès, le compte suffit ─────────


def test_avec_des_comptes_le_code_d_acces_n_est_plus_demande(monde, monkeypatch):
    monkeypatch.setenv("DOCUFLOW_CODE_ACCES", "graine-de-baobab")

    assert monde("claire").get("/factures").status_code == 200
    assert monde(None).get("/factures").status_code == 401
