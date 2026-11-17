"""Versions publiées et exécutions : l'historique du circuit, et le chemin réellement suivi par chaque facture."""

import copy
import json
import pathlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from moteur import editeur_circuit
from moteur.api import creer_application
from moteur.approbation import REGLES_DEMO, publier
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
MOYENNE = "facture-FA-2026-0412.pdf"  # 3 166,20 € TTC : comptable puis directeur financier


def seuil_dfi(seuil: str) -> list[dict]:
    regles = copy.deepcopy(REGLES_DEMO)
    regles[1]["si"] = {"lignes": [{"champ": "total_ttc", "comparaison": "superieur_a", "valeur": seuil}], "combinaison": "une"}
    return regles


# ───────── Les versions ─────────


def test_sans_rien_de_publie_aucune_version(session):
    assert editeur_circuit.versions(session) == []


def test_les_versions_vont_de_la_plus_recente_a_la_plus_ancienne(session):
    publier(session, REGLES_DEMO, "Moussa")  # avant l'éditeur : pas de liste de changements
    editeur_circuit.enregistrer(session, seuil_dfi("2500"), {"comptable": {"delai_h": 24, "delai_urgent_h": 12, "maximum": 2}}, "Claire")
    editeur_circuit.publier_brouillon(session, "Paul")

    liste = editeur_circuit.versions(session)

    assert [(v["version"], v["en_service"], v["publie_par"]) for v in liste] == [(2, True, "Paul"), (1, False, "Moussa")]
    assert liste[0]["nombre_regles"] == len(REGLES_DEMO) and liste[0]["relances_reglees"] is True
    assert len(liste[0]["changements"]) == 2  # le seuil, et les relances du comptable
    assert liste[1]["changements"] is None and liste[1]["relances_reglees"] is False


# ───────── Les étapes du chemin, lues dans le journal ─────────


@pytest.mark.parametrize(
    ("type_", "etat", "auteur", "detail", "attendu"),
    [
        ("RECEPTION", "recue", "moteur", {}, "Reçue"),
        ("EXTRACTION", "extraite", "moteur", {}, "Lue"),
        ("EXTRACTION_ECHOUEE", "echec", "moteur", {}, "Lecture impossible"),
        ("CONTROLE", "a_valider", "moteur", {}, "Contrôles"),
        ("CONTROLE", "en_anomalie", "moteur", {}, "Contrôles : arrêtée"),
        ("APPROBATION", "en_approbation", "Claire", {"libelle": "Comptable"}, "Comptable ✓ (Claire)"),
        ("VALIDATION", "validee", "Paul", {"libelle": "Directeur financier"}, "Directeur financier ✓ (Paul)"),
        ("NOTIFICATION", "a_valider", "moteur", {"niveau": "comptable", "rappel": "48 heures"}, "Relance : Comptable"),
        ("NOTIFICATION", "a_valider", "moteur", {"niveau": "comptable"}, None),  # le premier mail n'est pas une étape
        ("REJET", "rejetee", "Claire", {"motif": "IBAN"}, "Rejetée (Claire)"),
        ("EXPORT", "exportee", "Claire", {}, "Envoyée au logiciel"),
        ("NOUVEL_ESSAI", "recue", "moteur", {}, None),
    ],
)
def test_chaque_evenement_devient_une_etape_lisible(type_, etat, auteur, detail, attendu):
    assert editeur_circuit._etape(SimpleNamespace(type=type_, etat=etat, auteur=auteur, detail=detail)) == attendu


# ───────── Par l'API, sur de vraies factures ─────────


@pytest.fixture
def client(connexion, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    numeros = iter(f"FA-2026-{n:04d}" for n in range(500, 600))

    def extracteur(texte):
        donnees = Facture.model_validate({**ATTENDU[MOYENNE]["facture"], "numero_facture": next(numeros)})
        return ResultatExtraction(donnees, 0.1, "test", "faux")

    return TestClient(
        creer_application(fabrique_session=fabrique, extracteur=extracteur, dossier_fichiers=tmp_path, traiter_tout_de_suite=True, odoo=None)
    )


def deposer(client, marque: str) -> str:
    contenu = (FACTURES / MOYENNE).read_bytes() + f"\n% {marque}\n".encode()  # un autre fichier à chaque fois
    return client.post("/factures", files={"fichier": (MOYENNE, contenu, "application/pdf")}).json()["id"]


def test_par_l_api_le_chemin_de_chaque_facture(client):
    client.post("/regles", json={"auteur": "Moussa", "regles": REGLES_DEMO})
    validee, en_attente, rejetee = deposer(client, "a"), deposer(client, "b"), deposer(client, "c")
    client.post(f"/factures/{validee}/validation", json={"auteur": "Claire"})
    client.post(f"/factures/{validee}/validation", json={"auteur": "Paul"})
    client.post(f"/factures/{en_attente}/validation", json={"auteur": "Claire"})
    client.post(f"/factures/{rejetee}/rejet", json={"auteur": "Claire", "motif": "IBAN inconnu"})

    lignes = {ligne["facture_id"]: ligne for ligne in client.get("/circuit/executions").json()["executions"]}

    assert lignes[validee]["chemin"] == ["Reçue", "Lue", "Contrôles", "Comptable ✓ (Claire)", "Directeur financier ✓ (Paul)"]
    assert lignes[validee]["resultat"] == "Validée" and lignes[validee]["en_cours"] is False
    assert lignes[en_attente]["chemin"][-1] == "Comptable ✓ (Claire)"
    assert lignes[en_attente]["resultat"] == "En attente : directeur financier" and lignes[en_attente]["en_cours"] is True
    assert lignes[rejetee]["chemin"][-1] == "Rejetée (Claire)" and lignes[rejetee]["resultat"] == "Rejetée"
    assert all(ligne["version_circuit"] == 1 and ligne["total_ttc"] == "3166.20" for ligne in lignes.values())


def test_par_l_api_les_plus_recentes_d_abord_et_la_limite(client):
    ids = [deposer(client, str(n)) for n in range(3)]

    lignes = client.get("/circuit/executions", params={"limite": 2}).json()["executions"]

    assert [ligne["facture_id"] for ligne in lignes] == [ids[2], ids[1]]
    assert len(client.get("/circuit/executions", params={"limite": 100000}).json()["executions"]) == 3
    assert len(client.get("/circuit/executions", params={"limite": 0}).json()["executions"]) == 1


def test_une_execution_en_cours_dure_jusqu_a_maintenant(session, client):
    facture_id = deposer(client, "x")
    plus_tard = datetime.now(UTC) + timedelta(hours=26)

    ligne = next(ligne for ligne in editeur_circuit.executions(session, maintenant=plus_tard) if ligne["facture_id"] == facture_id)

    assert ligne["en_cours"] is True and ligne["duree_s"] >= 26 * 3600


def test_par_l_api_les_versions(client):
    assert client.get("/circuit/versions").json() == {"versions": []}
    client.post("/regles", json={"auteur": "Moussa", "regles": REGLES_DEMO})

    assert [v["version"] for v in client.get("/circuit/versions").json()["versions"]] == [1]
