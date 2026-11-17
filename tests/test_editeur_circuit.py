"""Le brouillon du circuit (un graphe) : on le modifie, on l'annule, et aucune facture ne le voit avant la publication."""

import json
import pathlib

import pytest
from fastapi.testclient import TestClient
from graphes_exemples import circuit_simple, seuil, tout_au_gerant
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moteur import editeur_circuit
from moteur.api import creer_application
from moteur.approbation import REGLES_DEMO, publier
from moteur.base import BrouillonCircuit, FactureEnBase
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
PETITE = "facture-F26-1193.pdf"  # 478,08 € TTC

RELANCES = {"comptable": {"delai_h": 24, "delai_urgent_h": 12, "maximum": 3}}


def types(graphe: dict) -> list[str]:
    return sorted(noeud["type"] for noeud in graphe["noeuds"])


# ───────── Sans brouillon : la version en service, en graphe ─────────


def test_sans_rien_de_publie_l_editeur_part_du_comptable_seul(session):
    vue = editeur_circuit.lire(session)

    assert vue["modifie"] is False and vue["version_en_service"] is None
    assert types(vue["graphe"]) == ["approbation", "debut", "fin"]


def test_une_version_en_regles_s_ouvre_en_graphe(session):
    publier(session, REGLES_DEMO, "Moussa", RELANCES)

    vue = editeur_circuit.lire(session)

    assert vue["modifie"] is False and vue["version_en_service"] == 1 and vue["relances"] == RELANCES
    conditions = [n for n in vue["graphe"]["noeuds"] if n["type"] == "condition"]
    assert {"lignes": [{"champ": "total_ttc", "comparaison": "superieur_a", "valeur": "1000"}], "combinaison": "une"} in [n["si"] for n in conditions]


def test_une_version_en_graphe_s_ouvre_telle_quelle(session):
    publier(session, [], "Moussa", graphe=circuit_simple())

    vue = editeur_circuit.lire(session)

    assert [(n["id"], n["x"], n["y"]) for n in vue["graphe"]["noeuds"]] == [(n["id"], n["x"], n["y"]) for n in circuit_simple()["noeuds"]]


# ───────── Enregistrer, remplacer, annuler ─────────


def test_enregistrer_puis_relire_le_brouillon(session):
    publier(session, REGLES_DEMO, "Moussa")

    vue = editeur_circuit.enregistrer(session, tout_au_gerant(), RELANCES, "Claire")

    assert vue["modifie"] is True and vue["modifie_par"] == "Claire" and vue["modifie_le"] is not None
    assert vue["version_en_service"] == 1
    assert {n["id"] for n in vue["graphe"]["noeuds"]} == {"debut", "compta", "gerant", "fin"}
    assert editeur_circuit.lire(session)["relances"] == RELANCES


def test_un_second_enregistrement_remplace_le_premier(session):
    editeur_circuit.enregistrer(session, circuit_simple(), None, "Claire")
    editeur_circuit.enregistrer(session, tout_au_gerant(), None, "Paul")

    assert session.scalar(select(func.count()).select_from(BrouillonCircuit)) == 1
    assert editeur_circuit.lire(session)["modifie_par"] == "Paul"
    assert len(editeur_circuit.lire(session)["graphe"]["noeuds"]) == 4


def test_annuler_revient_a_la_version_en_service(session):
    publier(session, [], "Moussa", graphe=circuit_simple())
    editeur_circuit.enregistrer(session, tout_au_gerant(), None, "Claire")

    vue = editeur_circuit.annuler(session)

    assert vue["modifie"] is False and len(vue["graphe"]["noeuds"]) == 5
    assert editeur_circuit.annuler(session)["modifie"] is False  # annuler deux fois ne gêne pas


# ───────── Ce qui est refusé, avec un message clair ─────────


def sans_sortie_non() -> dict:
    graphe = circuit_simple()
    graphe["liens"] = [lien for lien in graphe["liens"] if lien["sortie"] != "non"]
    return graphe


def montant_illisible() -> dict:
    graphe = circuit_simple()
    graphe["noeuds"][2]["si"] = seuil("mille")
    return graphe


@pytest.mark.parametrize(
    ("graphe", "relances", "message"),
    [
        ("tout", None, "des étapes et des liens"),
        (montant_illisible(), None, "« mille » n'est pas un montant"),
        ({"noeuds": [], "liens": []}, None, ""),
        (circuit_simple(), {"comptable": {"delai_h": 24, "delai_urgent_h": 48, "maximum": 2}}, "ne peut pas dépasser le délai normal"),
        (circuit_simple(), {"directeur_financier": {"delai_h": "demain", "delai_urgent_h": 1, "maximum": 1}}, "Relances du directeur financier"),
        (circuit_simple(), {"stagiaire": {"delai_h": 24, "delai_urgent_h": 12, "maximum": 2}}, "Niveau inconnu"),
    ],
)
def test_un_brouillon_mal_forme_est_refuse_et_rien_n_est_enregistre(session, graphe, relances, message):
    with pytest.raises(editeur_circuit.BrouillonInvalide, match=message or None):
        editeur_circuit.enregistrer(session, graphe, relances, "Claire")

    assert session.get(BrouillonCircuit, 1) is None


def test_un_seuil_demesure_est_refuse():
    graphe = circuit_simple()
    graphe["noeuds"][2]["si"] = seuil("1e999999")

    with pytest.raises(editeur_circuit.BrouillonInvalide, match="ne dépasse pas"):
        editeur_circuit.verifier(graphe, None)


# ───────── Par l'API, et aucune facture ne voit le brouillon ─────────


@pytest.fixture
def client(connexion, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    donnees = Facture.model_validate(ATTENDU[PETITE]["facture"])
    return TestClient(
        creer_application(
            fabrique_session=fabrique,
            extracteur=lambda texte: ResultatExtraction(donnees, 0.1, "test", "faux"),
            dossier_fichiers=tmp_path,
            traiter_tout_de_suite=True,
            odoo=None,
        )
    )


def test_par_l_api_le_brouillon_ne_change_aucune_facture(client):
    client.post("/regles", json={"auteur": "Moussa", "regles": REGLES_DEMO})
    enregistre = client.put("/circuit/brouillon", json={"auteur": "Claire", "graphe": tout_au_gerant(), "relances": RELANCES})
    assert enregistre.status_code == 200 and enregistre.json()["modifie"] is True

    facture = client.post("/factures", files={"fichier": (PETITE, (FACTURES / PETITE).read_bytes(), "application/pdf")}).json()
    fiche = client.get(f"/factures/{facture['id']}").json()

    assert [n["niveau"] for n in fiche["circuit"]["niveaux"]] == ["comptable"]  # la version 1, pas le brouillon
    assert fiche["circuit"]["version"] == 1


def test_par_l_api_lire_enregistrer_annuler(client):
    assert client.get("/circuit/brouillon").json()["modifie"] is False

    client.put("/circuit/brouillon", json={"auteur": "Claire", "graphe": tout_au_gerant()})
    assert client.get("/circuit/brouillon").json()["modifie_par"] == "Claire"

    assert client.delete("/circuit/brouillon").json()["modifie"] is False
    assert client.get("/circuit/brouillon").json()["modifie"] is False


@pytest.mark.parametrize(
    "corps",
    [
        {"graphe": tout_au_gerant()},  # sans auteur
        {"auteur": "   ", "graphe": tout_au_gerant()},  # auteur vide
        {"auteur": "Claire", "graphe": "tout"},  # pas un graphe
        {"auteur": "Claire", "regles": REGLES_DEMO},  # l'ancienne forme
    ],
)
def test_par_l_api_un_brouillon_refuse_donne_un_422(client, corps):
    reponse = client.put("/circuit/brouillon", json=corps)

    assert reponse.status_code == 422
    assert client.get("/circuit/brouillon").json()["modifie"] is False


def test_par_l_api_le_message_d_erreur_est_lisible(client):
    detail = client.put("/circuit/brouillon", json={"auteur": "Claire", "graphe": montant_illisible()}).json()["detail"]

    assert detail.endswith("« mille » n'est pas un montant.")


# ───────── Un circuit en construction est gardé, mais ne se publie pas ─────────


def avec_etape_seule() -> dict:
    graphe = circuit_simple()
    graphe["noeuds"].append({"id": "gerant", "type": "approbation", "x": 500, "y": 300, "niveau": "gerant"})  # pas encore reliée
    return graphe


@pytest.mark.parametrize(
    ("graphe", "manque"),
    [
        (sans_sortie_non(), "La condition « Plus de 1 000 € » doit avoir une sortie Oui et une sortie Non."),
        (avec_etape_seule(), "L'étape « Gérant » doit avoir une seule sortie, reliée à l'étape suivante."),
    ],
)
def test_un_circuit_incomplet_est_garde_avec_ce_qui_manque(session, graphe, manque):
    vue = editeur_circuit.enregistrer(session, graphe, None, "Claire")

    assert vue["a_completer"] == manque
    relu = editeur_circuit.lire(session)  # après un rechargement, rien n'est perdu
    assert {n["id"] for n in relu["graphe"]["noeuds"]} == {n["id"] for n in graphe["noeuds"]}
    assert relu["a_completer"] == manque


def test_un_circuit_incomplet_ne_se_publie_pas_et_ne_se_teste_pas(session):
    publier(session, [], "Moussa", graphe=circuit_simple())
    editeur_circuit.enregistrer(session, avec_etape_seule(), None, "Claire")
    facture = FactureEnBase(empreinte="x" * 64, nom_fichier="f.pdf", etat="a_valider", donnees={"total_ttc": "100"}, anomalies=[])
    session.add(facture)
    session.flush()

    with pytest.raises(editeur_circuit.PublicationImpossible, match="incomplet : L.étape « Gérant » doit avoir une seule sortie"):
        editeur_circuit.publier_brouillon(session, "Claire")
    with pytest.raises(editeur_circuit.TestImpossible, match="incomplet"):
        editeur_circuit.tester(session, facture)


def test_un_circuit_complet_n_a_rien_a_completer(session):
    assert editeur_circuit.enregistrer(session, circuit_simple(), None, "Claire")["a_completer"] is None
    assert editeur_circuit.lire(session)["graphe"]["liens"][0]["sortie"] is None  # la sortie vide est toujours présente


def test_par_l_api_incomplet_enregistre_mais_publication_refusee(client):
    enregistre = client.put("/circuit/brouillon", json={"auteur": "Claire", "graphe": sans_sortie_non()})
    assert enregistre.status_code == 200 and "sortie Oui et une sortie Non" in enregistre.json()["a_completer"]

    publie = client.post("/circuit/publier", json={"auteur": "Claire"})
    assert publie.status_code == 409 and "incomplet" in publie.json()["detail"]
