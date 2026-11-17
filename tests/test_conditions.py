"""Conditions en lignes (la forme de l'éditeur) : comparaisons, combinaison, refus, et aucune régression."""

import pytest
from pydantic import ValidationError

from moteur.approbation import REGLES_DEMO, Condition, Regle, circuit, en_lignes, publier


def vraie(condition: dict, donnees: dict | None = None, anomalies: tuple[str, ...] = ()) -> bool:
    return Condition.model_validate(condition).vraie(donnees or {}, [{"code": code} for code in anomalies])


def une(champ: str, comparaison: str, valeur) -> dict:
    return {"lignes": [{"champ": champ, "comparaison": comparaison, "valeur": valeur}]}


# ───────── Chaque comparaison ─────────


@pytest.mark.parametrize(
    ("comparaison", "seuil", "attendu"),
    [
        ("superieur_a", "1000", True),
        ("superieur_a", "1200.50", False),
        ("superieur_ou_egal_a", "1200.50", True),
        ("inferieur_a", "1200.50", False),
        ("inferieur_a", "1500", True),
        ("inferieur_ou_egal_a", "1200.50", True),
        ("egal_a", "1200.5", True),
        ("egal_a", "1200", False),
    ],
)
def test_un_montant_se_compare(comparaison, seuil, attendu):
    assert vraie(une("total_ttc", comparaison, seuil), {"total_ttc": "1200.50"}) is attendu


def test_un_montant_s_ecrit_a_la_francaise():
    condition = Condition.model_validate(une("total_ht", "superieur_a", "2 500,50"))

    assert condition.lignes[0].valeur == "2500.50"
    assert condition.vraie({"total_ht": "2600"}, []) is True


@pytest.mark.parametrize(
    ("comparaison", "valeur", "attendu"),
    [
        ("egal_a", "  garage central BERTIN ", True),
        ("different_de", "Garage Central Bertin", False),
        ("different_de", "Papeterie Durand", True),
        ("contient", "central", True),
        ("contient", "durand", False),
    ],
)
def test_un_nom_se_compare_sans_tenir_compte_des_majuscules(comparaison, valeur, attendu):
    assert vraie(une("fournisseur_nom", comparaison, valeur), {"fournisseur_nom": "Garage Central Bertin"}) is attendu


def test_un_siret_se_compare_sans_les_espaces():
    assert vraie(une("fournisseur_siret", "egal_a", "552 100 554 00021"), {"fournisseur_siret": "55210055400021"}) is True


def test_les_anomalies_une_de_et_aucune_de():
    iban = une("anomalie", "une_de", ["IBAN_DIFFERENT", "IBAN_NOUVEAU"])
    sans_iban = une("anomalie", "aucune_de", ["IBAN_DIFFERENT", "IBAN_NOUVEAU"])

    assert vraie(iban, anomalies=("IBAN_NOUVEAU",)) is True
    assert vraie(iban, anomalies=("ECART_COMMANDE",)) is False
    assert vraie(sans_iban, anomalies=("ECART_COMMANDE",)) is True
    assert vraie(sans_iban, anomalies=("IBAN_DIFFERENT",)) is False


@pytest.mark.parametrize("donnees", [{}, {"total_ttc": None}, {"total_ttc": ""}, {"total_ttc": "illisible"}])
def test_une_information_absente_ne_remplit_jamais_une_ligne(donnees):
    assert vraie(une("total_ttc", "inferieur_a", "1000"), donnees) is False
    assert vraie(une("fournisseur_nom", "different_de", "Durand"), {}) is False


# ───────── Une suffit, ou toutes ─────────

DEUX_LIGNES = [
    {"champ": "total_ttc", "comparaison": "superieur_a", "valeur": "2500"},
    {"champ": "anomalie", "comparaison": "une_de", "valeur": ["IBAN_DIFFERENT"]},
]


@pytest.mark.parametrize(
    ("total", "anomalies", "une_suffit", "toutes"),
    [
        ("285.60", ("IBAN_DIFFERENT",), True, False),
        ("3000", (), True, False),
        ("3000", ("IBAN_DIFFERENT",), True, True),
        ("285.60", (), False, False),
    ],
)
def test_une_suffit_ou_toutes(total, anomalies, une_suffit, toutes):
    donnees = {"total_ttc": total}

    assert vraie({"lignes": DEUX_LIGNES}, donnees, anomalies) is une_suffit  # « une » par défaut
    assert vraie({"lignes": DEUX_LIGNES, "combinaison": "une"}, donnees, anomalies) is une_suffit
    assert vraie({"lignes": DEUX_LIGNES, "combinaison": "toutes"}, donnees, anomalies) is toutes


# ───────── Ce qui est refusé ─────────


@pytest.mark.parametrize(
    "condition",
    [
        {"lignes": []},  # aucune ligne
        {"lignes": DEUX_LIGNES * 11},  # plus de 20 lignes
        {"combinaison": "toutes"},  # combinaison sans lignes
        {"lignes": DEUX_LIGNES, "toujours": True},  # deux formes
        une("total_ttc", "contient", "100"),  # comparaison de texte sur un montant
        une("total_ttc", "superieur_a", "mille"),  # pas un nombre
        une("total_ttc", "superieur_a", "-5"),  # négatif
        une("total_ttc", "superieur_a", "NaN"),
        une("total_ttc", "superieur_a", ["100"]),  # une liste pour un montant
        une("fournisseur_nom", "superieur_a", "A"),  # comparaison de montant sur un texte
        une("fournisseur_nom", "egal_a", "   "),  # texte vide
        une("fournisseur_nom", "egal_a", "x" * 201),
        une("anomalie", "egal_a", ["IBAN_DIFFERENT"]),
        une("anomalie", "une_de", "IBAN_DIFFERENT"),  # pas une liste
        une("anomalie", "une_de", []),
        une("anomalie", "une_de", ["iban; drop table"]),  # pas un code
        une("fournisseur_iban", "egal_a", "FR76"),  # champ inconnu
        {"lignes": [{"champ": "total_ttc", "comparaison": "egal_a", "valeur": "1", "code": "import os"}]},  # clé en trop
    ],
)
def test_une_condition_mal_formee_est_refusee(condition):
    with pytest.raises(ValidationError):
        Regle.model_validate({"nom": "x", "si": condition, "exige": ["comptable"]})


# ───────── Aucune régression ─────────


def test_les_regles_deja_publiees_restent_valides():
    for regle in REGLES_DEMO:
        Regle.model_validate(regle)


CAS = [
    (total, anomalies)
    for total in ("0", "478.08", "1000", "1000.01", "3166.20", "5000", "5000.01", "7200")
    for anomalies in ((), ("ECART_COMMANDE",), ("SANS_COMMANDE",), ("IBAN_DIFFERENT",), ("IBAN_NOUVEAU",), ("FOURNISSEUR_INCONNU",), ("TVA_INCOHERENTE",))
]


def test_reecrites_en_lignes_les_regles_donnent_le_meme_circuit(session):
    """Les règles en production, ouvertes dans l'éditeur puis republiées, ne changent aucun circuit."""
    ancienne = publier(session, REGLES_DEMO, "Moussa")
    reecrites = publier(session, [{**regle, "si": en_lignes(regle["si"])} for regle in REGLES_DEMO], "Moussa")

    assert all("lignes" in regle["si"] or regle["si"] == {"toujours": True} for regle in reecrites.regles)
    for total, anomalies in CAS:
        donnees, liste = {"total_ttc": total}, [{"code": code} for code in anomalies]
        avant, apres = circuit(donnees, liste, ancienne), circuit(donnees, liste, reecrites)
        assert (avant["niveaux"], avant["bloque"]) == (apres["niveaux"], apres["bloque"]), (total, anomalies)


def test_en_lignes_garde_toujours_tel_quel():
    assert en_lignes({"toujours": True}) == {"toujours": True}
    assert en_lignes({"champ": "total_ht", "superieur_a": "1000"}) == {
        "lignes": [{"champ": "total_ht", "comparaison": "superieur_a", "valeur": "1000"}],
        "combinaison": "une",
    }
