"""Différences et publication : ce que le brouillon (un graphe) change, en phrases, puis la version suivante."""

import copy
import json
import pathlib

import pytest
from fastapi.testclient import TestClient
from graphes_exemples import avec_blocage_iban, circuit_simple, seuil
from sqlalchemy.orm import Session

from moteur import editeur_circuit
from moteur.api import creer_application
from moteur.approbation import REGLES_DEMO, publier, version_en_vigueur
from moteur.base import BrouillonCircuit
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
MOYENNE = "facture-FA-2026-0412.pdf"  # 3 166,20 € TTC


# ───────── Les phrases ─────────


@pytest.mark.parametrize(
    ("condition", "attendu"),
    [
        ({"toujours": True}, "Toujours"),
        ({"champ": "total_ttc", "superieur_a": "1000"}, "Montant TTC supérieur à 1 000 €"),
        ({"lignes": [{"champ": "total_ht", "comparaison": "inferieur_ou_egal_a", "valeur": "2500.5"}]}, "Montant HT inférieur ou égal à 2 500,50 €"),
        ({"lignes": [{"champ": "fournisseur_nom", "comparaison": "contient", "valeur": "Garage"}]}, "Nom du fournisseur contient « Garage »"),
        ({"anomalie": ["IBAN_DIFFERENT"]}, "Anomalie : IBAN différent de celui connu"),
        ({"lignes": [{"champ": "anomalie", "comparaison": "aucune_de", "valeur": ["SANS_COMMANDE"]}]}, "Aucune anomalie : Achat sans bon de commande"),
        (
            {"combinaison": "toutes", "lignes": [
                {"champ": "total_ttc", "comparaison": "superieur_a", "valeur": "500"},
                {"champ": "anomalie", "comparaison": "une_de", "valeur": ["IBAN_NOUVEAU"]},
            ]},
            "Montant TTC supérieur à 500 € et Anomalie : IBAN jamais vu pour ce fournisseur",
        ),
    ],
)
def test_une_condition_se_lit_en_francais(condition, attendu):
    assert editeur_circuit.resume_condition(condition) == attendu


# ───────── Les différences ─────────


def test_sans_brouillon_aucune_difference(session):
    publier(session, [], "Moussa", graphe=circuit_simple())

    assert editeur_circuit.differences(session) == {"version_en_service": 1, "modifie": False, "changements": []}


def test_un_seuil_change_se_dit_en_une_phrase(session):
    publier(session, [], "Moussa", graphe=circuit_simple())
    editeur_circuit.enregistrer(session, circuit_simple("2500"), None, "Claire")

    changements = editeur_circuit.differences(session)["changements"]

    assert [c["genre"] for c in changements] == ["modification"]
    assert changements[0]["texte"] == "Plus de 1 000 € : si Montant TTC supérieur à 1 000 € → si Montant TTC supérieur à 2 500 €."


def test_ajout_lien_et_relances(session):
    publier(session, [], "Moussa", graphe=circuit_simple())
    editeur_circuit.enregistrer(session, avec_blocage_iban(circuit_simple()), {"comptable": {"delai_h": 24, "delai_urgent_h": 12, "maximum": 2}}, "Claire")

    textes = [c["texte"] for c in editeur_circuit.differences(session)["changements"]]

    assert "Étape ajoutée : IBAN changé (si Anomalie : IBAN différent de celui connu ou IBAN jamais vu pour ce fournisseur)." in textes
    assert "Étape ajoutée : IBAN à vérifier (bloque : Appelez le fournisseur.)." in textes
    assert "Après « Début », la facture va maintenant vers « IBAN changé » au lieu de « Comptable »." in textes
    assert (
        "Relances du comptable : relance après 48 h (24 h si l'échéance approche), 2 au plus"
        " → relance après 24 h (12 h si l'échéance approche), 2 au plus." in textes
    )
    assert len(textes) == 4


def test_retirer_une_etape(session):
    publier(session, [], "Moussa", graphe=avec_blocage_iban(circuit_simple()))
    editeur_circuit.enregistrer(session, circuit_simple(), None, "Claire")

    textes = [c["texte"] for c in editeur_circuit.differences(session)["changements"]]

    assert "Étape retirée : IBAN changé." in textes and "Étape retirée : IBAN à vérifier." in textes


def deplace() -> dict:
    graphe = circuit_simple()
    for noeud in graphe["noeuds"]:
        noeud["x"] += 37
    return graphe


def ecrit_autrement() -> dict:
    graphe = circuit_simple()
    graphe["noeuds"][2]["si"] = seuil("1 000,00")
    return graphe


@pytest.mark.parametrize("meme_sens", [deplace(), ecrit_autrement()])
def test_deplacer_ou_ecrire_autrement_n_est_pas_un_changement(session, meme_sens):
    publier(session, [], "Moussa", graphe=circuit_simple())
    editeur_circuit.enregistrer(session, meme_sens, None, "Claire")

    assert editeur_circuit.differences(session)["changements"] == []


# ───────── La publication ─────────


def test_publier_cree_la_version_suivante_avec_son_graphe_et_jette_le_brouillon(session):
    publier(session, REGLES_DEMO, "Moussa")  # une version d'avant, en règles
    editeur_circuit.enregistrer(session, circuit_simple("2500"), None, "Claire")

    version = editeur_circuit.publier_brouillon(session, "Paul")

    assert version.version == 2 and version.publie_par == "Paul" and version.regles == []
    assert [n["id"] for n in version.graphe["noeuds"]] == [n["id"] for n in circuit_simple()["noeuds"]]
    assert version.changements and version_en_vigueur(session).version == 2
    assert session.get(BrouillonCircuit, 1) is None
    assert editeur_circuit.lire(session)["modifie"] is False


def test_la_premiere_publication_part_de_rien(session):
    editeur_circuit.enregistrer(session, circuit_simple(), None, "Claire")

    version = editeur_circuit.publier_brouillon(session, "Claire")

    assert version.version == 1 and version.graphe is not None


@pytest.mark.parametrize("brouillon", [None, "identique", "deplace"])
def test_rien_a_publier_est_refuse(session, brouillon):
    publier(session, [], "Moussa", graphe=circuit_simple())
    if brouillon:
        editeur_circuit.enregistrer(session, circuit_simple() if brouillon == "identique" else deplace(), None, "Claire")

    with pytest.raises(editeur_circuit.PublicationImpossible):
        editeur_circuit.publier_brouillon(session, "Claire")

    assert version_en_vigueur(session).version == 1


# ───────── Par l'API : une facture en cours garde sa version ─────────


@pytest.fixture
def client(connexion, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    numeros = iter(["FA-2026-0412", "FA-2026-0413"])  # deux factures distinctes, du même montant

    def extracteur(texte):
        donnees = Facture.model_validate({**ATTENDU[MOYENNE]["facture"], "numero_facture": next(numeros)})
        return ResultatExtraction(donnees, 0.1, "test", "faux")

    return TestClient(
        creer_application(fabrique_session=fabrique, extracteur=extracteur, dossier_fichiers=tmp_path, traiter_tout_de_suite=True, odoo=None)
    )


def deposer(client, suffixe: bytes = b"") -> dict:
    contenu = (FACTURES / MOYENNE).read_bytes() + suffixe  # un autre fichier : pas un doublon de fichier
    facture = client.post("/factures", files={"fichier": (MOYENNE, contenu, "application/pdf")}).json()
    return client.get(f"/factures/{facture['id']}").json()


def test_par_l_api_publier_ne_touche_que_les_factures_suivantes(client):
    client.post("/regles", json={"auteur": "Moussa", "regles": REGLES_DEMO})
    avant = deposer(client)  # 3 166,20 € : comptable puis directeur financier
    assert [n["niveau"] for n in avant["circuit"]["niveaux"]] == ["comptable", "directeur_financier"]

    client.put("/circuit/brouillon", json={"auteur": "Claire", "graphe": circuit_simple("5000")})
    assert client.get("/circuit/differences").json()["changements"]
    publie = client.post("/circuit/publier", json={"auteur": "Paul"})
    assert publie.status_code == 201 and publie.json()["version"] == 2

    apres = deposer(client, b"\n% seconde facture\n")
    toujours = client.get(f"/factures/{avant['id']}").json()

    assert apres["id"] != avant["id"]
    assert [n["niveau"] for n in apres["circuit"]["niveaux"]] == ["comptable"]  # 3 166,20 € < 5 000 €
    assert apres["circuit"]["version"] == 2
    assert {"id": "seuil", "sortie": "non"} in apres["circuit"]["chemin"]  # le chemin suivi est gardé avec la facture
    assert toujours["circuit"]["version"] == 1  # la facture en cours n'a pas bougé
    assert [n["niveau"] for n in toujours["circuit"]["niveaux"]] == ["comptable", "directeur_financier"]


def test_par_l_api_rien_a_publier_donne_un_409_et_un_auteur_est_exige(client):
    assert client.post("/circuit/publier", json={"auteur": "Paul"}).status_code == 409
    assert client.post("/circuit/publier", json={"auteur": "  "}).status_code == 422
    assert client.post("/circuit/publier", json={}).status_code == 422


def test_le_graphe_publie_est_un_copie_independante(session):
    graphe = circuit_simple()
    editeur_circuit.enregistrer(session, graphe, None, "Claire")
    version = editeur_circuit.publier_brouillon(session, "Claire")

    graphe["noeuds"][2]["si"] = seuil("9999")  # modifier l'objet envoyé ne change pas la version publiée

    assert version.graphe["noeuds"][2]["si"]["lignes"][0]["valeur"] == "1000"
    assert copy.deepcopy(version.graphe) == version.graphe
