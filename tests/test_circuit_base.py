"""Éditeur de circuit, la base : relances versionnées avec les règles, et brouillon unique."""

import pytest
from sqlalchemy.exc import IntegrityError

from moteur.approbation import REGLES_DEMO, RELANCES_DEFAUT, circuit, publier, verifier_relances
from moteur.base import BrouillonCircuit

RELANCES = {"comptable": {"delai_h": 24, "delai_urgent_h": 12, "maximum": 3}, "gerant": {"delai_h": 72, "delai_urgent_h": 24, "maximum": 1}}


def test_une_version_sans_relances_reste_comme_avant(session):
    version = publier(session, REGLES_DEMO, "Moussa")

    assert version.relances is None
    assert "relances" not in circuit({"total_ttc": "100"}, [], version)  # le circuit garde la même forme


def test_une_version_garde_ses_relances_et_le_circuit_les_emporte(session):
    version = publier(session, REGLES_DEMO, "Moussa", RELANCES)

    assert version.relances == RELANCES
    assert circuit({"total_ttc": "100"}, [], version)["relances"] == RELANCES


def test_les_relances_par_defaut_sont_celles_d_aujourd_hui():
    from moteur import relances

    assert RELANCES_DEFAUT["delai_h"] * 3600 == relances.DELAI_NORMAL.total_seconds()
    assert RELANCES_DEFAUT["delai_urgent_h"] * 3600 == relances.DELAI_URGENT.total_seconds()
    assert RELANCES_DEFAUT["maximum"] == relances.RELANCES_MAX


def test_on_peut_couper_les_relances_d_un_niveau():
    assert verifier_relances({"comptable": {"delai_h": 48, "delai_urgent_h": 24, "maximum": 0}})["comptable"]["maximum"] == 0


@pytest.mark.parametrize(
    "relances",
    [
        {"comptable": {"delai_h": 0, "delai_urgent_h": 0, "maximum": 2}},  # délai nul
        {"comptable": {"delai_h": 337, "delai_urgent_h": 24, "maximum": 2}},  # plus de deux semaines
        {"comptable": {"delai_h": 24, "delai_urgent_h": 48, "maximum": 2}},  # urgent plus long que normal
        {"comptable": {"delai_h": 48, "delai_urgent_h": 24, "maximum": 6}},  # trop de relances
        {"comptable": {"delai_h": 48, "delai_urgent_h": 24}},  # maximum absent
        {"comptable": {"delai_h": 48, "delai_urgent_h": 24, "maximum": 2, "script": "x"}},  # clé en trop
        {"stagiaire": {"delai_h": 48, "delai_urgent_h": 24, "maximum": 2}},  # niveau inconnu
        [{"delai_h": 48}],  # pas un dictionnaire par niveau
    ],
)
def test_des_relances_mal_formees_sont_refusees(session, relances):
    with pytest.raises(ValueError):
        publier(session, REGLES_DEMO, "Moussa", relances)


def test_le_brouillon_est_unique(session):
    session.add(BrouillonCircuit(regles=REGLES_DEMO, modifie_par="Moussa"))
    session.flush()

    session.add(BrouillonCircuit(id=2, regles=REGLES_DEMO, modifie_par="Moussa"))
    with pytest.raises(IntegrityError):
        session.flush()
