"""Préparation commune des tests.

Les tests du workflow et de l'API tournent sur une vraie base PostgreSQL, dans
une base séparée (« factures_test »). Elle est construite par les migrations,
exactement comme une base de production : les migrations sont testées à chaque
lancement. Chaque test s'exécute dans une transaction annulée à la fin : aucun
test ne laisse de trace pour le suivant.
"""

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session

from alembic import command

from moteur import config
from moteur.base import configuration_alembic

BASE_DE_TEST = "factures_test"


def base_vierge(nom: str):
    """Crée la base si besoin, la vide entièrement, et renvoie son adresse."""
    url = make_url(config.lire("DATABASE_URL"))
    serveur = create_engine(url, isolation_level="AUTOCOMMIT")
    with serveur.connect() as connexion:
        existe = connexion.scalar(text("select 1 from pg_database where datname = :nom"), {"nom": nom})
        if not existe:
            connexion.execute(text(f'create database "{nom}"'))
    serveur.dispose()
    cible = url.set(database=nom)
    moteur = create_engine(cible, isolation_level="AUTOCOMMIT")
    with moteur.connect() as connexion:
        connexion.execute(text("drop schema public cascade"))
        connexion.execute(text("create schema public"))
    moteur.dispose()
    return cible


@pytest.fixture(scope="session")
def moteur_base():
    url = base_vierge(BASE_DE_TEST)
    command.upgrade(configuration_alembic(url.render_as_string(hide_password=False)), "head")
    moteur = create_engine(url)
    yield moteur
    moteur.dispose()


@pytest.fixture
def connexion(moteur_base):
    """Une connexion dont tout le travail est annulé à la fin du test."""
    with moteur_base.connect() as connexion:
        transaction = connexion.begin()
        yield connexion
        transaction.rollback()


@pytest.fixture
def session(connexion):
    with Session(bind=connexion, join_transaction_mode="create_savepoint") as session:
        yield session


@pytest.fixture(autouse=True)
def sans_odoo(monkeypatch, tmp_path_factory):
    """Aucun test ne parle au vrai Odoo, à Resend ni à HubSpot : les réglages réels sont coupés.

    Les tests du connecteur fournissent leur propre faux Odoo (tests/test_odoo.py).
    """
    monkeypatch.setenv("ODOO_CLE_FICHIER", str(tmp_path_factory.getbasetemp() / "pas-de-cle-odoo"))
    # Aucun test n'envoie de vrai mail ni ne se connecte à un vrai compte, même si .env contient les réglages.
    for nom in ("RESEND_API_KEY", "APPROBATION_SECRET", "APPROBATION_DESTINATAIRE", "HUBSPOT_CLIENT_ID", "HUBSPOT_CLIENT_SECRET", "CONNECTEURS_CLE_CHIFFREMENT"):
        monkeypatch.setenv(nom, "")
