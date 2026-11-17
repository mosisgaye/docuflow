"""Différences et publication : ce que le brouillon change, en phrases, puis la version suivante."""

import copy
import json
import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from moteur import editeur_circuit
from moteur.api import creer_application
from moteur.approbation import REGLES_DEMO, en_lignes, publier, version_en_vigueur
from moteur.base import BrouillonCircuit
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
MOYENNE = "facture-FA-2026-0412.pdf"  # 3 166,20 € TTC


def seuil_dfi(seuil: str) -> list[dict]:
    """Les règles de démonstration, avec un autre seuil pour le directeur financier."""
    regles = copy.deepcopy(REGLES_DEMO)
    regles[1]["si"] = {"lignes": [{"champ": "total_ttc", "comparaison": "superieur_a", "valeur": seuil}], "combinaison": "une"}
    return regles


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
    publier(session, REGLES_DEMO, "Moussa")

    assert editeur_circuit.differences(session) == {"version_en_service": 1, "modifie": False, "changements": []}


def test_un_seuil_change_se_dit_en_une_phrase(session):
    publier(session, REGLES_DEMO, "Moussa")
    editeur_circuit.enregistrer(session, seuil_dfi("2500"), None, "Claire")

    changements = editeur_circuit.differences(session)["changements"]

    assert [c["genre"] for c in changements] == ["modification"]
    assert changements[0]["texte"] == (
        "Plus de 1 000 € TTC : Montant TTC supérieur à 1 000 €, exige directeur financier"
        " → Montant TTC supérieur à 2 500 €, exige directeur financier."
    )


def test_ajout_retrait_et_relances(session):
    publier(session, REGLES_DEMO, "Moussa")
    regles = [r for r in REGLES_DEMO if r["nom"] != "Plus de 5 000 € TTC"]
    regles.append({"nom": "Garage : toujours le gérant", "si": {"lignes": [{"champ": "fournisseur_nom", "comparaison": "contient", "valeur": "Garage"}]}, "exige": ["gerant"]})
    editeur_circuit.enregistrer(session, regles, {"comptable": {"delai_h": 24, "delai_urgent_h": 12, "maximum": 2}}, "Claire")

    textes = [c["texte"] for c in editeur_circuit.differences(session)["changements"]]

    assert "Règle retirée : Plus de 5 000 € TTC." in textes
    assert "Règle ajoutée : Garage : toujours le gérant (Nom du fournisseur contient « Garage », exige gérant)." in textes
    assert (
        "Relances du comptable : relance après 48 h (24 h si l'échéance approche), 2 au plus"
        " → relance après 24 h (12 h si l'échéance approche), 2 au plus." in textes
    )
    assert len(textes) == 3


@pytest.mark.parametrize(
    "meme_sens",
    [
        [{**r, "si": en_lignes(r["si"])} for r in REGLES_DEMO],  # réécrites en lignes
        seuil_dfi("1000.00"),  # le même seuil, écrit autrement
        seuil_dfi("1 000"),
        list(reversed(REGLES_DEMO)),  # un autre ordre
    ],
)
def test_le_meme_circuit_ecrit_autrement_n_est_pas_un_changement(session, meme_sens):
    publier(session, REGLES_DEMO, "Moussa")
    editeur_circuit.enregistrer(session, meme_sens, None, "Claire")

    assert editeur_circuit.differences(session)["changements"] == []


# ───────── La publication ─────────


def test_publier_cree_la_version_suivante_avec_ses_changements_et_jette_le_brouillon(session):
    publier(session, REGLES_DEMO, "Moussa")
    editeur_circuit.enregistrer(session, seuil_dfi("2500"), None, "Claire")

    version = editeur_circuit.publier_brouillon(session, "Paul")

    assert version.version == 2 and version.publie_par == "Paul"
    assert version_en_vigueur(session).version == 2
    assert version.changements == [editeur_circuit.comparer({"regles": REGLES_DEMO}, {"regles": seuil_dfi("2500")})[0]["texte"]]
    assert session.get(BrouillonCircuit, 1) is None
    assert editeur_circuit.lire(session)["modifie"] is False


def test_la_premiere_publication_part_de_rien(session):
    editeur_circuit.enregistrer(session, REGLES_DEMO, None, "Claire")

    version = editeur_circuit.publier_brouillon(session, "Claire")

    assert version.version == 1 and len(version.changements) == 5  # 5 ajouts : la règle du comptable est déjà là


@pytest.mark.parametrize("brouillon", [None, "identique"])
def test_rien_a_publier_est_refuse(session, brouillon):
    publier(session, REGLES_DEMO, "Moussa")
    if brouillon:
        editeur_circuit.enregistrer(session, REGLES_DEMO, None, "Claire")

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
        creer_application(
            fabrique_session=fabrique,
            extracteur=extracteur,
            dossier_fichiers=tmp_path,
            traiter_tout_de_suite=True,
            odoo=None,
        )
    )


def deposer(client, suffixe: bytes = b"") -> dict:
    contenu = (FACTURES / MOYENNE).read_bytes() + suffixe  # un autre fichier : pas un doublon de fichier
    facture = client.post("/factures", files={"fichier": (MOYENNE, contenu, "application/pdf")}).json()
    return client.get(f"/factures/{facture['id']}").json()


def test_par_l_api_publier_ne_touche_que_les_factures_suivantes(client):
    client.post("/regles", json={"auteur": "Moussa", "regles": REGLES_DEMO})
    avant = deposer(client)  # 3 166,20 € : comptable puis directeur financier
    assert [n["niveau"] for n in avant["circuit"]["niveaux"]] == ["comptable", "directeur_financier"]

    client.put("/circuit/brouillon", json={"auteur": "Claire", "regles": seuil_dfi("5000")})
    assert len(client.get("/circuit/differences").json()["changements"]) == 1
    publie = client.post("/circuit/publier", json={"auteur": "Paul"})
    assert publie.status_code == 201 and publie.json()["version"] == 2

    apres = deposer(client, b"\n% seconde facture\n")
    toujours = client.get(f"/factures/{avant['id']}").json()

    assert apres["id"] != avant["id"]
    assert [n["niveau"] for n in apres["circuit"]["niveaux"]] == ["comptable"]  # 3 166,20 € < 5 000 €
    assert apres["circuit"]["version"] == 2
    assert toujours["circuit"]["version"] == 1  # la facture en cours n'a pas bougé
    assert [n["niveau"] for n in toujours["circuit"]["niveaux"]] == ["comptable", "directeur_financier"]


def test_par_l_api_rien_a_publier_donne_un_409_et_un_auteur_est_exige(client):
    assert client.post("/circuit/publier", json={"auteur": "Paul"}).status_code == 409
    assert client.post("/circuit/publier", json={"auteur": "  "}).status_code == 422
    assert client.post("/circuit/publier", json={}).status_code == 422
