"""Tester le brouillon (un graphe) sur une facture déjà reçue : le parcours du moteur, et rien d'écrit."""

import copy
import json
import pathlib
import uuid

import pytest
from fastapi.testclient import TestClient
from graphes_exemples import avec_blocage_iban, circuit_simple
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moteur import editeur_circuit
from moteur.api import creer_application
from moteur.approbation import REGLES_DEMO, circuit, publier
from moteur.base import Evenement, FactureEnBase
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
MOYENNE = "facture-FA-2026-0412.pdf"  # 3 166,20 € TTC

IBAN = {"code": "IBAN_DIFFERENT", "gravite": "avertissement", "message": "IBAN différent"}
DOUBLON = {"code": "DOUBLON_FACTURE", "gravite": "bloquante", "message": "Doublon"}


def facture(session, total="3166.20", anomalies=(), lue=True) -> FactureEnBase:
    donnees = {"fournisseur_nom": "Garage Central Bertin", "numero_facture": "F26-1302", "total_ttc": total} if lue else None
    enregistree = FactureEnBase(empreinte=uuid.uuid4().hex, nom_fichier="f.pdf", etat="a_valider", donnees=donnees, anomalies=list(anomalies))
    session.add(enregistree)
    session.flush()
    return enregistree


def niveaux(resultat: dict) -> list[str]:
    return [n["niveau"] for n in resultat["niveaux"]]


# ───────── Le parcours du moteur ─────────


def test_sans_brouillon_on_teste_la_version_en_service(session):
    publier(session, [], "Moussa", graphe=circuit_simple())

    resultat = editeur_circuit.tester(session, facture(session))

    assert resultat["circuit_teste"] == "en_service" and resultat["change"] is False
    assert niveaux(resultat) == ["comptable", "directeur_financier"]
    assert [etape["id"] for etape in resultat["chemin"]] == ["debut", "compta", "seuil", "dfi", "fin"]
    assert resultat["en_service"] == {"version": 1, "niveaux": ["comptable", "directeur_financier"], "bloque": None}


def test_le_brouillon_change_le_chemin_et_on_le_voit(session):
    publier(session, [], "Moussa", graphe=circuit_simple())
    editeur_circuit.enregistrer(session, circuit_simple("5000"), {"comptable": {"delai_h": 24, "delai_urgent_h": 12, "maximum": 3}}, "Claire")

    resultat = editeur_circuit.tester(session, facture(session))

    assert resultat["circuit_teste"] == "brouillon" and resultat["change"] is True
    assert niveaux(resultat) == ["comptable"]
    assert {"id": "seuil", "sortie": "non"} in resultat["chemin"]
    assert resultat["en_service"]["niveaux"] == ["comptable", "directeur_financier"]
    assert resultat["relances"] == {"comptable": {"delai_h": 24, "delai_urgent_h": 12, "maximum": 3}}


@pytest.mark.parametrize("total", ["100", "1000", "1000.01", "3166.20", "5000.01"])
@pytest.mark.parametrize("anomalies", [(), (IBAN,), ({"code": "FOURNISSEUR_INCONNU", "gravite": "avertissement"},)])
def test_le_resultat_est_celui_du_vrai_calcul(session, total, anomalies):
    version = publier(session, [], "Moussa", graphe=avec_blocage_iban(circuit_simple()))
    testee = facture(session, total, anomalies)

    resultat = editeur_circuit.tester(session, testee)
    vrai = circuit(testee.donnees, testee.anomalies, version)

    assert (resultat["niveaux"], resultat["bloque"], resultat["chemin"]) == (vrai["niveaux"], vrai["bloque"], vrai["chemin"])


def test_une_version_en_regles_se_teste_comme_elle_se_calcule(session):
    version = publier(session, REGLES_DEMO, "Moussa")
    testee = facture(session, "3166.20")

    assert niveaux(editeur_circuit.tester(session, testee)) == niveaux(circuit(testee.donnees, testee.anomalies, version))


def test_chaque_condition_traversee_dit_si_elle_est_vraie(session):
    editeur_circuit.enregistrer(session, avec_blocage_iban(circuit_simple("2500")), None, "Claire")

    resultat = editeur_circuit.tester(session, facture(session, "285.60"))

    assert resultat["conditions"] == [
        {"id": "iban", "nom": "IBAN changé", "vraie": False, "lignes": [{"texte": "Anomalie : IBAN différent de celui connu ou IBAN jamais vu pour ce fournisseur", "vraie": False}]},
        {"id": "seuil", "nom": "Plus de 1 000 €", "vraie": False, "lignes": [{"texte": "Montant TTC supérieur à 2 500 €", "vraie": False}]},
    ]


def test_un_blocage_arrete_le_chemin(session):
    editeur_circuit.enregistrer(session, avec_blocage_iban(circuit_simple()), None, "Claire")

    resultat = editeur_circuit.tester(session, facture(session, anomalies=(IBAN,)))

    assert resultat["bloque"] == "IBAN à vérifier : Appelez le fournisseur."
    assert [etape["id"] for etape in resultat["chemin"]] == ["debut", "iban", "stop"]


def test_une_facture_arretee_aux_controles_n_atteint_pas_le_circuit(session):
    publier(session, [], "Moussa", graphe=circuit_simple())

    resultat = editeur_circuit.tester(session, facture(session, anomalies=(DOUBLON, IBAN)))

    assert resultat["controles"]["arretee"] is True and resultat["change"] is False
    assert resultat["niveaux"] == [] and resultat["chemin"] == []
    assert "Arrêtée aux contrôles (facture déjà reçue (doublon))" in resultat["bloque"]
    assert {"code": "IBAN_DIFFERENT", "libelle": "IBAN différent de celui connu", "gravite": "avertissement"} in resultat["controles"]["anomalies"]


def test_une_facture_pas_encore_lue_ne_sert_pas_de_test(session):
    with pytest.raises(editeur_circuit.TestImpossible):
        editeur_circuit.tester(session, facture(session, lue=False))


# ───────── Rien n'est écrit ─────────


def test_tester_n_ecrit_rien(session):
    publier(session, [], "Moussa", graphe=circuit_simple())
    editeur_circuit.enregistrer(session, circuit_simple("5000"), None, "Claire")
    testee = facture(session, anomalies=(IBAN,))
    testee.circuit = {"version": 1, "niveaux": [{"niveau": "comptable", "raisons": []}], "bloque": None}
    session.flush()
    avant = (copy.deepcopy(testee.circuit), copy.deepcopy(testee.donnees), testee.etat, testee.modifie_le)
    evenements = session.scalar(select(func.count()).select_from(Evenement))

    editeur_circuit.tester(session, testee)

    assert not session.new and not session.dirty and not session.deleted  # rien d'ajouté ni de modifié
    session.flush()
    session.refresh(testee)
    assert (testee.circuit, testee.donnees, testee.etat, testee.modifie_le) == avant
    assert session.scalar(select(func.count()).select_from(Evenement)) == evenements
    assert editeur_circuit.lire(session)["modifie"] is True  # le brouillon est toujours là


# ───────── Par l'API ─────────


@pytest.fixture
def client(connexion, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    donnees = Facture.model_validate(ATTENDU[MOYENNE]["facture"])
    return TestClient(
        creer_application(
            fabrique_session=fabrique,
            extracteur=lambda texte: ResultatExtraction(donnees, 0.1, "test", "faux"),
            dossier_fichiers=tmp_path,
            traiter_tout_de_suite=True,
            odoo=None,
        )
    )


def test_par_l_api_sur_une_vraie_facture_deposee(client):
    client.post("/regles", json={"auteur": "Moussa", "regles": REGLES_DEMO})
    deposee = client.post("/factures", files={"fichier": (MOYENNE, (FACTURES / MOYENNE).read_bytes(), "application/pdf")}).json()
    client.put("/circuit/brouillon", json={"auteur": "Claire", "graphe": circuit_simple("5000")})

    reponse = client.post("/circuit/tester", json={"facture_id": deposee["id"]})

    assert reponse.status_code == 200
    resultat = reponse.json()
    assert resultat["facture"]["id"] == deposee["id"]
    assert niveaux(resultat) == ["comptable"] and resultat["change"] is True
    assert client.get(f"/factures/{deposee['id']}").json()["circuit"]["version"] == 1  # la facture n'a pas bougé


def test_par_l_api_facture_introuvable_ou_identifiant_faux(client):
    assert client.post("/circuit/tester", json={"facture_id": str(uuid.uuid4())}).status_code == 404
    assert client.post("/circuit/tester", json={"facture_id": "pas-un-identifiant"}).status_code == 422
