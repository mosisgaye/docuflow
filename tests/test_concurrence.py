"""Deux dépôts en même temps : le moteur ne doit ni planter, ni créer de doublon.

Ces tests utilisent de vraies transactions parallèles (une par fil d'exécution),
validées en base. La table est vidée à la fin de chaque test.
"""

import json
import pathlib
import threading
import time
from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from moteur.base import Etat, FactureEnBase
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture
from moteur.workflow import traiter

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))


class LLMLent:
    """Répond après un délai, pour que les deux dépôts se chevauchent vraiment."""

    def __init__(self, nom_fichier: str):
        self.facture = Facture.model_validate(ATTENDU[nom_fichier]["facture"])
        self.appels = 0
        self.verrou = threading.Lock()

    def __call__(self, texte: str) -> ResultatExtraction:
        with self.verrou:
            self.appels += 1
        time.sleep(0.4)
        return ResultatExtraction(self.facture, 0.4, "test", "lent")


@pytest.fixture
def base_propre(moteur_base):
    yield moteur_base
    with moteur_base.begin() as connexion:
        connexion.execute(text("truncate evenements, factures"))


def deposer_en_parallele(moteur_base, depots: list[tuple[bytes, str]], extracteur) -> tuple[list, list]:
    resultats, erreurs = [], []
    depart = threading.Barrier(len(depots))

    def deposer(contenu: bytes, nom: str) -> None:
        try:
            with Session(moteur_base) as session:
                depart.wait()
                resultat = traiter(session, contenu, nom, extracteur, date(2026, 11, 14))
                session.commit()
                resultats.append((resultat.facture.id, resultat.deja_vue, resultat.facture.etat))
        except Exception as erreur:  # noqa: BLE001 - on veut voir toute erreur
            erreurs.append(repr(erreur))

    fils = [threading.Thread(target=deposer, args=depot) for depot in depots]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=30)
    return resultats, erreurs


def test_le_meme_fichier_depose_deux_fois_en_meme_temps(base_propre):
    contenu = (FACTURES / "facture-F26-1193.pdf").read_bytes()
    llm = LLMLent("facture-F26-1193.pdf")

    resultats, erreurs = deposer_en_parallele(base_propre, [(contenu, "a.pdf"), (contenu, "b.pdf")], llm)

    assert erreurs == []
    assert len({identifiant for identifiant, _, _ in resultats}) == 1
    assert sorted(deja_vue for _, deja_vue, _ in resultats) == [False, True]
    assert llm.appels == 1
    with Session(base_propre) as session:
        assert session.scalar(select(func.count()).select_from(FactureEnBase)) == 1


def test_la_meme_facture_dans_deux_fichiers_deposes_en_meme_temps(base_propre):
    # Deux fichiers différents, mais le LLM y lit le même fournisseur et le même numéro.
    llm = LLMLent("facture-F26-1193.pdf")
    depots = [((FACTURES / "facture-F26-1193.pdf").read_bytes(), "original.pdf"), ((FACTURES / "facture-2026-11-087.pdf").read_bytes(), "copie.pdf")]

    resultats, erreurs = deposer_en_parallele(base_propre, depots, llm)

    assert erreurs == []
    assert sorted(etat for _, _, etat in resultats) == sorted([Etat.A_VALIDER.value, Etat.EN_ANOMALIE.value])
    with Session(base_propre) as session:
        doublon = session.scalars(select(FactureEnBase).where(FactureEnBase.etat == Etat.EN_ANOMALIE.value)).one()
        assert [anomalie["code"] for anomalie in doublon.anomalies] == ["DOUBLON_FACTURE"]
