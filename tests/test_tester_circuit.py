"""Tester le brouillon sur une facture déjà reçue : le même calcul que le moteur, et rien d'écrit."""

import copy
import json
import pathlib
import uuid

import pytest
from fastapi.testclient import TestClient
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


def seuil_dfi(seuil: str) -> list[dict]:
    regles = copy.deepcopy(REGLES_DEMO)
    regles[1]["si"] = {"lignes": [{"champ": "total_ttc", "comparaison": "superieur_a", "valeur": seuil}], "combinaison": "une"}
    return regles


def facture(session, total="3166.20", anomalies=(), lue=True) -> FactureEnBase:
    donnees = {"fournisseur_nom": "Garage Central Bertin", "numero_facture": "F26-1302", "total_ttc": total} if lue else None
    enregistree = FactureEnBase(empreinte=uuid.uuid4().hex, nom_fichier="f.pdf", etat="a_valider", donnees=donnees, anomalies=list(anomalies))
    session.add(enregistree)
    session.flush()
    return enregistree


IBAN = {"code": "IBAN_DIFFERENT", "gravite": "avertissement", "message": "IBAN différent"}
DOUBLON = {"code": "DOUBLON_FACTURE", "gravite": "bloquante", "message": "Doublon"}


# ───────── Le même calcul que le moteur ─────────


def test_sans_brouillon_on_teste_la_version_en_service(session):
    publier(session, REGLES_DEMO, "Moussa")

    resultat = editeur_circuit.tester(session, facture(session))

    assert resultat["circuit_teste"] == "en_service" and resultat["change"] is False
    assert [n["niveau"] for n in resultat["niveaux"]] == ["comptable", "directeur_financier"]
    assert resultat["en_service"] == {"version": 1, "niveaux": ["comptable", "directeur_financier"], "bloque": None}


def test_le_brouillon_change_le_chemin_et_on_le_voit(session):
    publier(session, REGLES_DEMO, "Moussa")
    editeur_circuit.enregistrer(session, seuil_dfi("5000"), {"comptable": {"delai_h": 24, "delai_urgent_h": 12, "maximum": 3}}, "Claire")

    resultat = editeur_circuit.tester(session, facture(session))

    assert resultat["circuit_teste"] == "brouillon" and resultat["change"] is True
    assert [n["niveau"] for n in resultat["niveaux"]] == ["comptable"]
    assert resultat["en_service"]["niveaux"] == ["comptable", "directeur_financier"]
    assert resultat["relances"] == {"comptable": {"delai_h": 24, "delai_urgent_h": 12, "maximum": 3}}


@pytest.mark.parametrize("total", ["100", "1000", "1000.01", "3166.20", "5000.01"])
@pytest.mark.parametrize("anomalies", [(), (IBAN,), ({"code": "FOURNISSEUR_INCONNU", "gravite": "avertissement"},)])
def test_le_resultat_est_celui_du_vrai_calcul(session, total, anomalies):
    version = publier(session, REGLES_DEMO, "Moussa")
    testee = facture(session, total, anomalies)

    resultat = editeur_circuit.tester(session, testee)
    vrai = circuit(testee.donnees, testee.anomalies, version)

    assert (resultat["niveaux"], resultat["bloque"]) == (vrai["niveaux"], vrai["bloque"])


def test_chaque_regle_et_chaque_ligne_dit_si_elle_est_vraie(session):
    regles = [
        {"nom": "Directeur financier", "si": {"combinaison": "une", "lignes": [
            {"champ": "total_ttc", "comparaison": "superieur_a", "valeur": "2500"},
            {"champ": "anomalie", "comparaison": "une_de", "valeur": ["IBAN_DIFFERENT"]},
        ]}, "exige": ["comptable", "directeur_financier"]},
    ]
    editeur_circuit.enregistrer(session, regles, None, "Claire")

    regle = editeur_circuit.tester(session, facture(session, "285.60", (IBAN,)))["regles"][0]

    assert regle["vraie"] is True
    assert regle["lignes"] == [
        {"texte": "Montant TTC supérieur à 2 500 €", "vraie": False},
        {"texte": "Anomalie : IBAN différent de celui connu", "vraie": True},
    ]
    assert regle["effet"] == "exige comptable, directeur financier"


def test_une_facture_arretee_aux_controles_n_atteint_pas_le_circuit(session):
    publier(session, REGLES_DEMO, "Moussa")

    resultat = editeur_circuit.tester(session, facture(session, anomalies=(DOUBLON, IBAN)))

    assert resultat["controles"]["arretee"] is True
    assert resultat["niveaux"] == [] and "Arrêtée aux contrôles (facture déjà reçue (doublon))" in resultat["bloque"]
    assert {"code": "IBAN_DIFFERENT", "libelle": "IBAN différent de celui connu", "gravite": "avertissement"} in resultat["controles"]["anomalies"]


def test_une_facture_pas_encore_lue_ne_sert_pas_de_test(session):
    with pytest.raises(editeur_circuit.TestImpossible):
        editeur_circuit.tester(session, facture(session, lue=False))


# ───────── Rien n'est écrit ─────────


def test_tester_n_ecrit_rien(session):
    publier(session, REGLES_DEMO, "Moussa")
    editeur_circuit.enregistrer(session, seuil_dfi("5000"), None, "Claire")
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
    client.put("/circuit/brouillon", json={"auteur": "Claire", "regles": seuil_dfi("5000")})

    reponse = client.post("/circuit/tester", json={"facture_id": deposee["id"]})

    assert reponse.status_code == 200
    resultat = reponse.json()
    assert resultat["facture"]["id"] == deposee["id"]
    assert [n["niveau"] for n in resultat["niveaux"]] == ["comptable"] and resultat["change"] is True
    assert client.get(f"/factures/{deposee['id']}").json()["circuit"]["version"] == 1  # la facture n'a pas bougé


def test_par_l_api_facture_introuvable_ou_identifiant_faux(client):
    assert client.post("/circuit/tester", json={"facture_id": str(uuid.uuid4())}).status_code == 404
    assert client.post("/circuit/tester", json={"facture_id": "pas-un-identifiant"}).status_code == 422
