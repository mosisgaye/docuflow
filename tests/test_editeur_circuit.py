"""Le brouillon du circuit : on le modifie, on l'annule, et aucune facture ne le voit tant qu'il n'est pas publié."""

import json
import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moteur import editeur_circuit
from moteur.api import creer_application
from moteur.approbation import REGLES_DEMO, publier
from moteur.base import BrouillonCircuit
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
PETITE = "facture-F26-1193.pdf"  # 478,08 € TTC

TOUT_AU_GERANT = [
    {"nom": "Toute facture passe par le gérant", "si": {"toujours": True}, "exige": ["comptable", "gerant"]},
]
RELANCES = {"comptable": {"delai_h": 24, "delai_urgent_h": 12, "maximum": 3}}


# ───────── Sans brouillon : la version en service ─────────


def test_sans_rien_de_publie_l_editeur_part_du_comptable_seul(session):
    vue = editeur_circuit.lire(session)

    assert vue["modifie"] is False and vue["version_en_service"] is None
    assert vue["regles"] == [{"nom": "Toute facture est approuvée par le comptable", "si": {"toujours": True}, "exige": ["comptable"]}]


def test_sans_brouillon_l_editeur_montre_la_version_en_service_en_lignes(session):
    publier(session, REGLES_DEMO, "Moussa", RELANCES)

    vue = editeur_circuit.lire(session)

    assert vue["modifie"] is False and vue["version_en_service"] == 1
    assert vue["relances"] == RELANCES
    seuil = vue["regles"][1]["si"]
    assert seuil == {"lignes": [{"champ": "total_ttc", "comparaison": "superieur_a", "valeur": "1000"}], "combinaison": "une"}


# ───────── Enregistrer, remplacer, annuler ─────────


def test_enregistrer_puis_relire_le_brouillon(session):
    publier(session, REGLES_DEMO, "Moussa")

    vue = editeur_circuit.enregistrer(session, TOUT_AU_GERANT, RELANCES, "Claire")

    assert vue["modifie"] is True and vue["modifie_par"] == "Claire" and vue["modifie_le"] is not None
    assert vue["version_en_service"] == 1
    assert vue["regles"][0]["exige"] == ["comptable", "gerant"]
    assert editeur_circuit.lire(session)["relances"] == RELANCES


def test_un_second_enregistrement_remplace_le_premier(session):
    editeur_circuit.enregistrer(session, REGLES_DEMO, None, "Claire")
    editeur_circuit.enregistrer(session, TOUT_AU_GERANT, None, "Paul")

    assert session.scalar(select(func.count()).select_from(BrouillonCircuit)) == 1
    assert editeur_circuit.lire(session)["modifie_par"] == "Paul"
    assert len(editeur_circuit.lire(session)["regles"]) == 1


def test_annuler_revient_a_la_version_en_service(session):
    publier(session, REGLES_DEMO, "Moussa")
    editeur_circuit.enregistrer(session, TOUT_AU_GERANT, None, "Claire")

    vue = editeur_circuit.annuler(session)

    assert vue["modifie"] is False and len(vue["regles"]) == len(REGLES_DEMO)
    assert editeur_circuit.annuler(session)["modifie"] is False  # annuler deux fois ne gêne pas


# ───────── Ce qui est refusé, avec un message clair ─────────


@pytest.mark.parametrize(
    ("regles", "relances", "message"),
    [
        ([], None, "de 1 à 50 règles"),
        (REGLES_DEMO * 9, None, "de 1 à 50 règles"),
        ([{"nom": "Seuil", "si": {"lignes": [{"champ": "total_ttc", "comparaison": "superieur_a", "valeur": "mille"}]}, "exige": ["gerant"]}], None, "Règle 1 « Seuil »"),
        ([{"nom": "Seuil", "si": {"lignes": [{"champ": "total_ttc", "comparaison": "superieur_a", "valeur": "mille"}]}, "exige": ["gerant"]}], None, "n'est pas un montant"),
        ([REGLES_DEMO[0], {"nom": "x", "si": {"toujours": True}}], None, "Règle 2"),
        ([{"nom": "x", "si": {"toujours": True}, "exige": ["stagiaire"]}], None, "valeur non permise"),
        (REGLES_DEMO, {"comptable": {"delai_h": 24, "delai_urgent_h": 48, "maximum": 2}}, "ne peut pas dépasser le délai normal"),
        (REGLES_DEMO, {"stagiaire": {"delai_h": 24, "delai_urgent_h": 12, "maximum": 2}}, "Niveau inconnu"),
    ],
)
def test_un_brouillon_mal_forme_est_refuse_et_rien_n_est_enregistre(session, regles, relances, message):
    with pytest.raises(editeur_circuit.BrouillonInvalide, match=message):
        editeur_circuit.enregistrer(session, regles, relances, "Claire")

    assert session.get(BrouillonCircuit, 1) is None


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
    enregistre = client.put("/circuit/brouillon", json={"auteur": "Claire", "regles": TOUT_AU_GERANT, "relances": RELANCES})
    assert enregistre.status_code == 200 and enregistre.json()["modifie"] is True

    facture = client.post("/factures", files={"fichier": (PETITE, (FACTURES / PETITE).read_bytes(), "application/pdf")}).json()
    fiche = client.get(f"/factures/{facture['id']}").json()

    assert [n["niveau"] for n in fiche["circuit"]["niveaux"]] == ["comptable"]  # la version 1, pas le brouillon
    assert fiche["circuit"]["version"] == 1
    assert client.get("/regles").json()["version"] == 1  # rien de publié


def test_par_l_api_lire_enregistrer_annuler(client):
    assert client.get("/circuit/brouillon").json()["modifie"] is False

    client.put("/circuit/brouillon", json={"auteur": "Claire", "regles": TOUT_AU_GERANT})
    assert client.get("/circuit/brouillon").json()["modifie_par"] == "Claire"

    assert client.delete("/circuit/brouillon").json()["modifie"] is False
    assert client.get("/circuit/brouillon").json()["modifie"] is False


@pytest.mark.parametrize(
    "corps",
    [
        {"regles": TOUT_AU_GERANT},  # sans auteur
        {"auteur": "   ", "regles": TOUT_AU_GERANT},  # auteur vide
        {"auteur": "Claire", "regles": [{"nom": "x", "si": {"toujours": True}}]},  # ni exige ni bloque
        {"auteur": "Claire", "regles": "tout"},  # pas une liste
    ],
)
def test_par_l_api_un_brouillon_refuse_donne_un_422(client, corps):
    reponse = client.put("/circuit/brouillon", json=corps)

    assert reponse.status_code == 422
    assert client.get("/circuit/brouillon").json()["modifie"] is False


def test_par_l_api_le_message_d_erreur_est_lisible(client):
    regle = {"nom": "Seuil", "si": {"lignes": [{"champ": "total_ttc", "comparaison": "superieur_a", "valeur": "mille"}]}, "exige": ["gerant"]}

    detail = client.put("/circuit/brouillon", json={"auteur": "Claire", "regles": [regle]}).json()["detail"]

    assert detail.startswith("Règle 1 « Seuil »") and "« mille » n'est pas un montant" in detail


def test_le_message_dit_quelle_ligne_et_quel_niveau():
    deux_lignes = {"lignes": [{"champ": "total_ttc", "comparaison": "superieur_a", "valeur": "1"}, {"champ": "total_ttc", "comparaison": "contient", "valeur": "1"}]}

    with pytest.raises(editeur_circuit.BrouillonInvalide, match=r"lignes › 2"):
        editeur_circuit.verifier([{"nom": "x", "si": deux_lignes, "exige": ["gerant"]}], None)
    with pytest.raises(editeur_circuit.BrouillonInvalide, match="Relances du directeur financier"):
        editeur_circuit.verifier(REGLES_DEMO, {"directeur_financier": {"delai_h": "demain", "delai_urgent_h": 1, "maximum": 1}})


@pytest.mark.parametrize("autre_nom", ["Toute facture est approuvée par le comptable", "  toute FACTURE est approuvée  par le comptable "])
def test_deux_regles_du_meme_nom_sont_refusees(session, autre_nom):
    """Les différences et le test retrouvent les règles par leur nom : deux du même nom se confondraient."""
    regles = [REGLES_DEMO[0], {**REGLES_DEMO[2], "nom": autre_nom}]

    with pytest.raises(editeur_circuit.BrouillonInvalide, match="la règle 1 porte déjà ce nom"):
        editeur_circuit.enregistrer(session, regles, None, "Claire")


def test_un_seuil_demesure_est_refuse():
    for valeur in ("1e999999", "1000000000.01"):
        with pytest.raises(editeur_circuit.BrouillonInvalide, match="ne dépasse pas"):
            editeur_circuit.verifier([{"nom": "x", "si": {"lignes": [{"champ": "total_ttc", "comparaison": "superieur_a", "valeur": valeur}]}, "exige": ["gerant"]}], None)
    editeur_circuit.verifier([{"nom": "x", "si": {"lignes": [{"champ": "total_ttc", "comparaison": "superieur_a", "valeur": "1000000000"}]}, "exige": ["gerant"]}], None)
