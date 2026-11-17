"""Éditeur de circuit, la base : relances versionnées avec les règles, et brouillon unique."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from moteur import relances
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


# ───────── Les relances suivent le réglage figé dans la facture ─────────

MAINTENANT = datetime(2026, 11, 15, 12, tzinfo=UTC)


def facture(circuit_calcule: dict | None, echeance_dans_jours: int = 30):
    echeance = (date(2026, 11, 15) + timedelta(days=echeance_dans_jours)).isoformat()
    return SimpleNamespace(circuit=circuit_calcule, donnees={"date_echeance": echeance})


def mail(il_y_a_h: float, rappel: str | None = None):
    detail = {"niveau": "comptable", "destinataire": "claire@exemple.fr", **({"rappel": rappel} if rappel else {})}
    return SimpleNamespace(type="NOTIFICATION", detail=detail, cree_le=MAINTENANT - timedelta(hours=il_y_a_h))


def reglee(**comptable) -> dict:
    return {"version": 1, "niveaux": [{"niveau": "comptable", "raisons": []}], "bloque": None, "relances": {"comptable": {**RELANCES_DEFAUT, **comptable}}}


def test_un_delai_regle_fait_relancer_plus_tot():
    assert relances.a_relancer(facture(None), "comptable", [mail(25)], MAINTENANT) is None  # défaut : 48 h
    assert "25 heures" in relances.a_relancer(facture(reglee(delai_h=24, delai_urgent_h=12)), "comptable", [mail(25)], MAINTENANT)


def test_un_delai_urgent_regle_est_respecte():
    proche = facture(reglee(delai_urgent_h=12), echeance_dans_jours=2)

    assert relances.a_relancer(proche, "comptable", [mail(11)], MAINTENANT) is None
    assert relances.a_relancer(proche, "comptable", [mail(13)], MAINTENANT) == "l'échéance de paiement tombe dans 2 jours."


def test_le_maximum_regle_est_respecte():
    deux_deja = [mail(300), mail(200, "x"), mail(100, "y")]

    assert relances.a_relancer(facture(None), "comptable", deux_deja, MAINTENANT) is None  # défaut : 2 au plus
    assert relances.a_relancer(facture(reglee(maximum=3)), "comptable", deux_deja, MAINTENANT) is not None
    assert relances.a_relancer(facture(reglee(maximum=0)), "comptable", [mail(300)], MAINTENANT) is None  # coupées


def test_un_niveau_sans_reglage_garde_les_delais_par_defaut():
    autre_niveau = {**reglee(), "relances": {"gerant": {"delai_h": 1, "delai_urgent_h": 1, "maximum": 5}}}

    assert relances.a_relancer(facture(autre_niveau), "comptable", [mail(47)], MAINTENANT) is None
    assert relances.a_relancer(facture(autre_niveau), "comptable", [mail(49)], MAINTENANT) is not None


def test_une_facture_garde_les_relances_de_sa_version(session):
    rapide = publier(session, REGLES_DEMO, "Moussa", {"comptable": {"delai_h": 24, "delai_urgent_h": 12, "maximum": 2}})
    en_cours = facture(circuit({"total_ttc": "100"}, [], rapide))

    publier(session, REGLES_DEMO, "Moussa")  # la version suivante revient aux délais par défaut

    assert relances.a_relancer(en_cours, "comptable", [mail(25)], MAINTENANT) is not None  # toujours 24 h
