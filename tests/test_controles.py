import json
import pathlib
from datetime import date

import pytest

from moteur.controles import Gravite, cle_de_luhn_valide, cle_tva_attendue, controler, est_validable
from moteur.modeles import Facture

AUJOURD_HUI = date(2026, 11, 14)
ATTENDU = json.loads((pathlib.Path(__file__).resolve().parent.parent / "factures" / "attendu.json").read_text(encoding="utf-8"))

FACTURE_JUSTE = {
    "numero_facture": "F26-1193",
    "date_facture": "2026-11-10",
    "date_echeance": "2026-12-10",
    "fournisseur_nom": "Garage Central Bertin",
    "fournisseur_siret": "52987431500029",
    "fournisseur_tva": "FR52529874315",
    "client_nom": "Boulangerie Petit Jean",
    "lignes": [
        {"designation": "Vidange et filtre à huile", "quantite": "1", "prix_unitaire_ht": "145.00", "montant_ht": "145.00"},
        {"designation": "Main-d'œuvre (heures)", "quantite": "2.5", "prix_unitaire_ht": "62.00", "montant_ht": "155.00"},
    ],
    "total_ht": "300.00",
    "taux_tva": "20",
    "total_tva": "60.00",
    "total_ttc": "360.00",
}


def codes(modifications: dict) -> list[str]:
    facture = Facture.model_validate({**FACTURE_JUSTE, **modifications})
    return [anomalie.code for anomalie in controler(facture, AUJOURD_HUI)]


def test_une_facture_juste_n_a_aucune_anomalie():
    assert codes({}) == []


@pytest.mark.parametrize(
    ("modifications", "code_attendu"),
    [
        ({"numero_facture": None}, "CHAMP_MANQUANT"),
        ({"fournisseur_siret": None}, "CHAMP_MANQUANT"),
        ({"lignes": []}, "AUCUNE_LIGNE"),
        ({"total_ht": "310.00", "total_tva": "62.00", "total_ttc": "372.00"}, "TOTAL_HT_INCOHERENT"),
        ({"total_ttc": "460.00"}, "TOTAL_TTC_INCOHERENT"),
        ({"total_tva": "50.00", "total_ttc": "350.00"}, "TVA_INCOHERENTE"),
        ({"taux_tva": "19.6", "total_tva": "58.80", "total_ttc": "358.80"}, "TAUX_TVA_INCONNU"),
        ({"fournisseur_siret": "52987431500028"}, "SIRET_INVALIDE"),
        ({"fournisseur_siret": "5298743150002"}, "SIRET_INVALIDE"),
        ({"fournisseur_tva": "FR53529874315"}, "TVA_INTRACOM_INVALIDE"),
        ({"fournisseur_tva": "FR5252987431"}, "TVA_INTRACOM_INVALIDE"),
        ({"fournisseur_tva": "FR28403221989"}, "TVA_SIRET_DIFFERENTS"),
        ({"date_echeance": "2026-11-01"}, "ECHEANCE_AVANT_FACTURE"),
        ({"date_facture": "2026-11-20"}, "DATE_FUTURE"),
    ],
)
def test_chaque_anomalie_est_detectee(modifications, code_attendu):
    assert codes(modifications) == [code_attendu]


def test_une_ligne_mal_calculee_est_detectee():
    lignes = [{"designation": "Pneus", "quantite": "4", "prix_unitaire_ht": "75.00", "montant_ht": "310.00"}]

    obtenus = codes({"lignes": lignes, "total_ht": "310.00", "total_tva": "62.00", "total_ttc": "372.00"})

    assert obtenus == ["LIGNE_INCOHERENTE"]


def test_un_ecart_d_un_centime_est_tolere():
    assert codes({"total_tva": "60.01", "total_ttc": "360.01"}) == []


def test_le_message_explique_le_calcul():
    facture = Facture.model_validate({**FACTURE_JUSTE, "total_ttc": "460.00"})

    anomalie = controler(facture, AUJOURD_HUI)[0]

    assert anomalie.message == "HT + TVA font 360,00 €, le total TTC indique 460,00 €."
    assert anomalie.champ == "total_ttc"


def test_les_anomalies_bloquantes_passent_en_premier():
    facture = Facture.model_validate({**FACTURE_JUSTE, "date_facture": "2026-11-20", "date_echeance": "2026-12-20", "total_ttc": "460.00"})

    anomalies = controler(facture, AUJOURD_HUI)

    assert [anomalie.gravite for anomalie in anomalies] == [Gravite.BLOQUANTE, Gravite.AVERTISSEMENT]


def test_un_avertissement_seul_n_empeche_pas_la_validation():
    facture = Facture.model_validate({**FACTURE_JUSTE, "date_facture": "2026-11-20", "date_echeance": "2026-12-20"})

    assert est_validable(controler(facture, AUJOURD_HUI))


def test_une_anomalie_bloquante_empeche_la_validation():
    facture = Facture.model_validate({**FACTURE_JUSTE, "total_ttc": "460.00"})

    assert not est_validable(controler(facture, AUJOURD_HUI))


def test_un_tva_etranger_n_est_pas_controle_comme_un_tva_francais():
    assert codes({"fournisseur_tva": "DE123456789"}) == []


@pytest.mark.parametrize(("numero", "valide"), [("529874315", True), ("52987431500029", True), ("529874316", False)])
def test_cle_de_luhn(numero, valide):
    assert cle_de_luhn_valide(numero) is valide


def test_cle_tva():
    assert cle_tva_attendue("529874315") == "52"


@pytest.mark.parametrize("fichier", sorted(ATTENDU))
def test_les_factures_d_exemple_donnent_les_anomalies_prevues(fichier):
    facture = Facture.model_validate(ATTENDU[fichier]["facture"])

    obtenus = [anomalie.code for anomalie in controler(facture, AUJOURD_HUI)]

    assert obtenus == ATTENDU[fichier]["anomalies"]
