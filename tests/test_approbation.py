"""Workflow d'approbation : règles versionnées, circuit, ordre des niveaux, séparation des tâches."""

import json
import pathlib
from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from moteur.api import creer_application
from moteur.approbation import REGLES_DEMO, Regle, circuit, niveau_attendu, publier
from moteur.base import Etat
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture
from moteur.workflow import TransitionInterdite, rejeter, traiter, valider

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
PETITE = "facture-F26-1193.pdf"  # 478,08 € TTC
MOYENNE = "facture-FA-2026-0412.pdf"  # 3 166,20 € TTC
AUJOURD_HUI = date(2026, 11, 14)


def deposer(session, nom: str):
    donnees = Facture.model_validate(ATTENDU[nom]["facture"])
    return traiter(session, (FACTURES / nom).read_bytes(), nom, lambda texte: ResultatExtraction(donnees, 0.1, "test", "faux"), AUJOURD_HUI).facture


@pytest.fixture
def regles(session):
    return publier(session, REGLES_DEMO, "Moussa")


def niveaux(circuit_calcule: dict) -> list[str]:
    return [n["niveau"] for n in circuit_calcule["niveaux"]]


# ───────── Le langage des règles ─────────


@pytest.mark.parametrize(
    "regle",
    [
        {"nom": "x", "si": {"toujours": True, "anomalie": ["A"]}, "exige": ["comptable"]},  # deux conditions
        {"nom": "x", "si": {"champ": "total_ttc"}, "exige": ["comptable"]},  # champ sans seuil
        {"nom": "x", "si": {"champ": "fournisseur_iban", "superieur_a": "1"}, "exige": ["comptable"]},  # champ inconnu
        {"nom": "x", "si": {"toujours": True}, "exige": ["stagiaire"]},  # niveau inconnu
        {"nom": "x", "si": {"toujours": True}},  # ni exige ni bloque
        {"nom": "x", "si": {"toujours": True}, "exige": ["comptable"], "bloque": "non"},  # les deux
        {"nom": "x", "si": {"toujours": True}, "exige": ["comptable"], "code": "import os"},  # champ en trop
    ],
)
def test_une_regle_mal_formee_est_refusee(regle):
    with pytest.raises(ValidationError):
        Regle.model_validate(regle)


def test_chaque_publication_cree_une_nouvelle_version(session):
    premiere = publier(session, REGLES_DEMO, "Moussa")
    seconde = publier(session, REGLES_DEMO[:1], "Moussa")

    assert (premiere.version, seconde.version) == (1, 2)
    assert len(premiere.regles) == 5  # la première version n'a pas bougé


# ───────── Le circuit ─────────


@pytest.mark.parametrize(
    ("total", "anomalies", "attendus"),
    [
        ("478.08", [], ["comptable"]),
        ("3166.20", [], ["comptable", "directeur_financier"]),
        ("7200.00", [], ["comptable", "directeur_financier", "gerant"]),
        ("478.08", ["ECART_COMMANDE"], ["comptable", "directeur_financier"]),
        ("478.08", ["SANS_COMMANDE"], ["comptable", "directeur_financier"]),
    ],
)
def test_le_circuit_suit_les_regles(session, regles, total, anomalies, attendus):
    calcule = circuit({"total_ttc": total}, [{"code": code} for code in anomalies], regles)

    assert niveaux(calcule) == attendus
    assert calcule["version"] == 1
    assert calcule["bloque"] is None


def test_chaque_niveau_dit_quelle_regle_l_impose(session, regles):
    calcule = circuit({"total_ttc": "3166.20"}, [{"code": "ECART_COMMANDE"}], regles)

    assert calcule["niveaux"][1]["raisons"] == ["Plus de 1 000 € TTC", "Écart avec le bon de commande, ou achat sans commande"]


def test_un_fournisseur_inconnu_bloque_le_circuit(session, regles):
    calcule = circuit({"total_ttc": "100"}, [{"code": "FOURNISSEUR_INCONNU"}], regles)

    assert "Créez d'abord le fournisseur dans Odoo" in calcule["bloque"]


def test_sans_regles_publiees_une_validation_suffit(session):
    facture = deposer(session, MOYENNE)

    valider(session, facture.id, "Claire")

    assert facture.etat == Etat.VALIDEE


# ───────── L'approbation, niveau par niveau ─────────


def test_une_facture_moyenne_passe_par_deux_niveaux(session, regles):
    facture = deposer(session, MOYENNE)
    assert niveaux(facture.circuit) == ["comptable", "directeur_financier"]

    valider(session, facture.id, "Claire")
    assert facture.etat == Etat.EN_APPROBATION
    assert niveau_attendu(session, facture) == "directeur_financier"

    valider(session, facture.id, "Paul")
    assert facture.etat == Etat.VALIDEE
    assert [(e.type, e.auteur, e.detail.get("niveau")) for e in facture.evenements[-2:]] == [
        ("APPROBATION", "Claire", "comptable"),
        ("VALIDATION", "Paul", "directeur_financier"),
    ]


def test_une_petite_facture_est_validee_par_le_comptable_seul(session, regles):
    facture = deposer(session, PETITE)

    valider(session, facture.id, "Claire")

    assert facture.etat == Etat.VALIDEE


def test_la_meme_personne_n_approuve_pas_deux_niveaux(session, regles):
    facture = deposer(session, MOYENNE)
    valider(session, facture.id, "Claire")

    with pytest.raises(TransitionInterdite, match="autre personne"):
        valider(session, facture.id, " claire ")  # même personne, autre écriture

    assert facture.etat == Etat.EN_APPROBATION


def test_si_les_donnees_changent_l_approbation_ne_vaut_plus(session, regles):
    facture = deposer(session, MOYENNE)
    valider(session, facture.id, "Claire")

    facture.donnees = {**facture.donnees, "total_ttc": "3266.20"}  # une donnée corrigée après l'approbation

    assert niveau_attendu(session, facture) == "comptable"  # il faut approuver de nouveau
    valider(session, facture.id, "Claire")
    valider(session, facture.id, "Paul")
    assert facture.etat == Etat.VALIDEE


def test_la_facture_garde_la_version_des_regles_de_son_circuit(session, regles):
    facture = deposer(session, MOYENNE)

    publier(session, [{"nom": "Tout chez le gérant", "si": {"toujours": True}, "exige": ["gerant"]}], "Moussa")

    assert facture.circuit["version"] == 1
    assert niveaux(facture.circuit) == ["comptable", "directeur_financier"]


def test_une_facture_bloquee_ne_peut_pas_etre_approuvee(session, regles):
    facture = deposer(session, PETITE)
    facture.circuit = {**facture.circuit, "bloque": "Fournisseur inconnu dans Odoo : Créez d'abord le fournisseur dans Odoo."}

    with pytest.raises(TransitionInterdite, match="Créez d'abord le fournisseur"):
        valider(session, facture.id, "Claire")


def test_on_peut_rejeter_en_cours_d_approbation(session, regles):
    facture = deposer(session, MOYENNE)
    valider(session, facture.id, "Claire")

    rejeter(session, facture.id, "Paul", "Montant non prévu au budget")

    assert facture.etat == Etat.REJETEE


# ───────── Par l'API ─────────


def test_par_l_api_le_refus_est_explique(connexion, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    with fabrique() as session:
        publier(session, REGLES_DEMO, "Moussa")
        session.commit()
    donnees = Facture.model_validate(ATTENDU[MOYENNE]["facture"])
    client = TestClient(
        creer_application(
            fabrique_session=fabrique, extracteur=lambda texte: ResultatExtraction(donnees, 0.1, "test", "faux"),
            dossier_fichiers=tmp_path, traiter_tout_de_suite=True, odoo=None,
        )
    )
    facture = client.post("/factures", files={"fichier": (MOYENNE, (FACTURES / MOYENNE).read_bytes(), "application/pdf")}).json()

    premiere = client.post(f"/factures/{facture['id']}/validation", json={"auteur": "Claire"})
    seconde = client.post(f"/factures/{facture['id']}/validation", json={"auteur": "Claire"})

    assert premiere.json()["etat"] == "en_approbation"
    assert seconde.status_code == 409
    assert "autre personne" in seconde.json()["detail"]
