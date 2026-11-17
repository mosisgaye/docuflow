"""Migration 0015 : la base refuse un rang en double dans le journal et les valeurs hors liste.

Le test de concurrence utilise de vraies transactions parallèles, validées en base ;
les tables sont vidées à la fin.
"""

import threading
import time
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from moteur import base, comptes
from moteur.base import Etat, Evenement, FactureEnBase
from moteur.workflow import _journaliser


def nouvelle_facture(etat: str = Etat.A_VALIDER.value) -> FactureEnBase:
    return FactureEnBase(empreinte=uuid.uuid4().hex, nom_fichier="essai.pdf", etat=etat, anomalies=[])


@pytest.fixture
def base_propre(moteur_base):
    yield moteur_base
    with moteur_base.begin() as connexion:
        connexion.execute(text("truncate approbations, taches, evenements, factures"))


def test_deux_ecritures_simultanees_dans_le_journal_ont_des_rangs_differents(base_propre):
    with Session(base_propre) as session:
        facture = nouvelle_facture()
        session.add(facture)
        _journaliser(session, facture, "RECEPTION", "moteur")
        session.commit()
        facture_id = facture.id

    depart = threading.Barrier(2)
    erreurs: list[str] = []

    def ecrire(auteur: str) -> None:
        try:
            with Session(base_propre) as session:
                facture = session.get(FactureEnBase, facture_id)
                facture.evenements  # la liste est chargée avant que l'autre écrive : elle sera en retard
                depart.wait()
                _journaliser(session, facture, "NOTE", auteur)
                time.sleep(0.3)  # la transaction reste ouverte : l'autre doit attendre le verrou
                session.commit()
        except Exception as erreur:  # noqa: BLE001 - on veut voir toute erreur
            erreurs.append(repr(erreur))

    fils = [threading.Thread(target=ecrire, args=(nom,)) for nom in ("travailleur", "approbateur")]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=30)

    assert erreurs == []
    with Session(base_propre) as session:
        rangs = session.scalars(select(Evenement.rang).where(Evenement.facture_id == facture_id).order_by(Evenement.rang)).all()
    assert rangs == [1, 2, 3]


def test_la_base_refuse_un_rang_en_double(session):
    facture = nouvelle_facture()
    session.add(facture)
    session.flush()
    session.add(Evenement(facture=facture, rang=1, type="RECEPTION", etat=facture.etat, auteur="moteur", detail={}))
    session.flush()
    session.add(Evenement(facture=facture, rang=1, type="NOTE", etat=facture.etat, auteur="moteur", detail={}))
    with pytest.raises(IntegrityError, match="uq_evenements_facture_rang"):
        session.flush()


@pytest.mark.parametrize(
    ("objet", "contrainte"),
    [
        (lambda: nouvelle_facture(etat="inventee"), "ck_factures_etat"),
        (lambda: comptes.Compte(nom="X", email=f"{uuid.uuid4().hex}@exemple.test", role="super_admin", niveaux=[], cree_par="test"), "ck_comptes_role"),
        (lambda: base.MembreEquipe(nom="X", email="x@exemple.test", niveau="president", cree_par="test"), "ck_membres_equipe_niveau"),
    ],
)
def test_la_base_refuse_une_valeur_hors_liste(session, objet, contrainte):
    session.add(objet())
    with pytest.raises(IntegrityError, match=contrainte):
        session.flush()


def test_les_listes_de_la_base_suivent_celles_du_code():
    assert base.ROLES_EN_BASE == comptes.ROLES
    assert base.NIVEAUX_EN_BASE == comptes.NIVEAUX
