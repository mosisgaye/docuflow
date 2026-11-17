"""Le catalogue de l'éditeur dit exactement ce que le moteur accepte : ni plus, ni moins."""

import itertools
import pathlib
import re
import typing

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session

from moteur.api import creer_application
from moteur.approbation import NIVEAUX, RELANCES_DEFAUT, Ligne, Relance
from moteur.catalogue_circuit import catalogue

MOTEUR = pathlib.Path(__file__).resolve().parent.parent / "moteur"
CATALOGUE = catalogue()


def accepte(champ: str, comparaison: str) -> bool:
    valeur = ["IBAN_DIFFERENT"] if champ == "anomalie" else "100"
    try:
        Ligne.model_validate({"champ": champ, "comparaison": comparaison, "valeur": valeur})
    except ValidationError:
        return False
    return True


def test_chaque_comparaison_du_catalogue_est_acceptee_et_aucune_n_est_oubliee():
    proposees = {(champ["champ"], c["code"]) for champ in CATALOGUE["champs"] for c in champ["comparaisons"]}
    champs = typing.get_args(Ligne.model_fields["champ"].annotation)
    comparaisons = typing.get_args(Ligne.model_fields["comparaison"].annotation)
    acceptees = {(champ, comparaison) for champ, comparaison in itertools.product(champs, comparaisons) if accepte(champ, comparaison)}

    # Exception voulue : le SIRET n'est pas proposé en « contient » (un SIRET se compare en entier).
    assert proposees == acceptees - {("fournisseur_siret", "contient")}


def test_chaque_libelle_est_en_francais_et_present():
    for champ in CATALOGUE["champs"]:
        assert champ["libelle"] and all(c["libelle"] for c in champ["comparaisons"])
    assert all(anomalie["libelle"] for anomalie in CATALOGUE["anomalies"])


def test_les_anomalies_du_catalogue_sont_celles_que_les_controles_detectent():
    """Lu dans le code des contrôles : une anomalie ajoutée sans libellé fait échouer ce test."""
    source = "\n".join(fichier.read_text(encoding="utf-8") for fichier in MOTEUR.glob("*.py"))
    detectees = dict(re.findall(r'Anomalie\(\s*"([A-Z_]+)",\s*Gravite\.([A-Z]+)', source))

    assert {a["code"]: a["gravite"] for a in CATALOGUE["anomalies"]} == {code: gravite.lower() for code, gravite in detectees.items()}


def test_seules_les_anomalies_non_bloquantes_servent_dans_une_condition():
    utilisables = {a["code"] for a in CATALOGUE["anomalies"] if a["utilisable"]}

    assert {"IBAN_DIFFERENT", "IBAN_NOUVEAU", "ECART_COMMANDE", "SANS_COMMANDE", "FOURNISSEUR_INCONNU"} <= utilisables
    assert "DOUBLON_FACTURE" not in utilisables  # un doublon n'atteint jamais le circuit


def test_les_niveaux_sont_ceux_du_moteur_dans_l_ordre():
    assert [n["code"] for n in CATALOGUE["niveaux"]] == NIVEAUX


@pytest.mark.parametrize("reglage", CATALOGUE["relances"], ids=lambda r: r["nom"])
def test_les_bornes_des_relances_sont_celles_du_moteur(reglage):
    def valide(valeur: int) -> bool:
        essai = {**RELANCES_DEFAUT, reglage["nom"]: valeur}
        if reglage["nom"] == "delai_h":
            essai["delai_urgent_h"] = 1  # pour éprouver le délai normal seul
        if reglage["nom"] == "delai_urgent_h":
            essai["delai_h"] = 336  # l'urgent ne dépasse jamais le normal : on met le normal au plus haut
        try:
            Relance.model_validate(essai)
        except ValidationError:
            return False
        return True

    assert valide(reglage["min"]) and valide(reglage["max"])
    assert not valide(reglage["min"] - 1) and not valide(reglage["max"] + 1)
    assert reglage["defaut"] == RELANCES_DEFAUT[reglage["nom"]]


def test_les_etapes_fixes_ne_se_reglent_pas_et_les_futures_sont_annoncees():
    etapes = {e["type"]: e for e in CATALOGUE["etapes"]}

    assert all(etapes[t]["fixe"] for t in ("reception", "lecture", "controles", "odoo"))
    assert etapes["approbation"]["disponible"] and not etapes["prevenir"]["disponible"]


def test_par_l_api(connexion, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    client = TestClient(creer_application(fabrique_session=fabrique, dossier_fichiers=tmp_path, odoo=None))

    reponse = client.get("/circuit/catalogue")

    assert reponse.status_code == 200
    assert reponse.json() == CATALOGUE
