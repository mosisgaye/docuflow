"""Chaque lecture par l'IA garde la trace de la consigne exacte utilisée."""

import json
import pathlib
from datetime import date

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moteur import agent, extraction_llm
from moteur.api import creer_application
from moteur.base import Consigne
from moteur.consignes import VersionConsigne, enregistrer
from moteur.extraction_llm import OpenAI, ResultatExtraction, extraire, version_consigne
from moteur.facturx import LECTEUR
from moteur.modeles import Facture
from moteur.workflow import traiter

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
GARAGE = ATTENDU["facture-F26-1193.pdf"]["facture"]


def test_la_meme_consigne_a_toujours_la_meme_empreinte():
    assert version_consigne(OpenAI).empreinte == version_consigne(OpenAI).empreinte
    assert len(version_consigne(OpenAI).empreinte) == 12


def test_modifier_un_seul_caractere_change_l_empreinte(monkeypatch):
    avant = version_consigne(OpenAI).empreinte
    monkeypatch.setattr(extraction_llm, "CONSIGNE", extraction_llm.CONSIGNE + " ")

    assert version_consigne(OpenAI).empreinte != avant


def test_le_format_de_reponse_fait_partie_de_la_version():
    texte = "même texte"

    assert VersionConsigne("extraction", texte, {"a": 1}).empreinte != VersionConsigne("extraction", texte, {"a": 2}).empreinte


def test_une_consigne_n_est_enregistree_qu_une_fois(session):
    version = version_consigne(OpenAI)

    enregistrer(session, version)
    enregistrer(session, version)

    assert session.scalar(select(func.count()).select_from(Consigne).where(Consigne.id == version.empreinte)) == 1
    assert session.get(Consigne, version.empreinte).texte == extraction_llm.CONSIGNE


def test_extraire_renvoie_la_consigne_reellement_envoyee(monkeypatch):
    monkeypatch.setenv("LLM_FOURNISSEUR", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "cle-de-test")
    recues = []

    def repondre(requete):
        recues.append(json.loads(requete.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(GARAGE)}}]})

    resultat = extraire("Facture n° F26-1193", client=httpx.Client(transport=httpx.MockTransport(repondre)))

    assert resultat.consigne == version_consigne(OpenAI)
    envoye = recues[0]
    assert envoye["messages"][0]["content"] == resultat.consigne.texte.format(texte="Facture n° F26-1193")
    assert envoye["response_format"]["json_schema"]["schema"] == resultat.consigne.schema


def test_le_journal_renvoie_a_la_consigne_utilisee(session):
    version = version_consigne(OpenAI)
    lecture = lambda texte: ResultatExtraction(Facture.model_validate(GARAGE), 0.1, "openai", "modele", version)  # noqa: E731

    facture = traiter(session, (FACTURES / "facture-F26-1193.pdf").read_bytes(), "f.pdf", lecture, date(2026, 11, 14)).facture

    empreinte = facture.evenements[1].detail["consigne"]
    assert empreinte == version.empreinte
    assert session.get(Consigne, empreinte).texte == extraction_llm.CONSIGNE


def test_une_lecture_factur_x_note_la_version_du_lecteur(session):
    contenu = (FACTURES / "facture-facturx-FX-2026-0057.pdf").read_bytes()

    facture = traiter(session, contenu, "fx.pdf", lambda texte: None, date(2026, 11, 14)).facture

    assert facture.evenements[1].detail["lecteur"] == LECTEUR
    assert "consigne" not in facture.evenements[1].detail


def test_la_consigne_de_l_assistant_est_enregistree_au_demarrage(connexion, tmp_path):
    creer_application(fabrique_session=lambda: Session(bind=connexion, join_transaction_mode="create_savepoint"), dossier_fichiers=tmp_path)

    with Session(bind=connexion, join_transaction_mode="create_savepoint") as session:
        enregistree = session.get(Consigne, agent.version_consigne().empreinte)
        assert enregistree is not None
        assert enregistree.usage == "assistant"
        assert enregistree.texte == agent.CONSIGNE


def test_l_api_demarre_meme_si_la_consigne_est_deja_connue(connexion, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731

    creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path)
    application = creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path)

    assert TestClient(application).get("/sante").status_code == 200
