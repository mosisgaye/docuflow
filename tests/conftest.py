"""Préparation commune des tests.

Les tests du workflow et de l'API tournent sur une vraie base PostgreSQL, dans
une base séparée (« factures_test »). Chaque test s'exécute dans une transaction
annulée à la fin : aucun test ne laisse de trace pour le suivant.
"""

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.orm import Session

from moteur import config
from moteur.base import Base

BASE_DE_TEST = "factures_test"


@pytest.fixture(scope="session")
def moteur_base():
    url = make_url(config.lire("DATABASE_URL"))
    with create_engine(url, isolation_level="AUTOCOMMIT").connect() as connexion:
        existe = connexion.scalar(text("select 1 from pg_database where datname = :nom"), {"nom": BASE_DE_TEST})
        if not existe:
            connexion.execute(text(f'create database "{BASE_DE_TEST}"'))
    moteur = create_engine(url.set(database=BASE_DE_TEST))
    Base.metadata.drop_all(moteur)
    Base.metadata.create_all(moteur)
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
