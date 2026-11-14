"""Les migrations construisent exactement le schéma décrit par les modèles."""

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

import pytest

from moteur.base import Base, SchemaPasAJour, configuration_alembic, verifier_schema
from tests.conftest import base_vierge


def test_les_migrations_correspondent_aux_modeles(moteur_base):
    """Échoue si un modèle a été modifié sans écrire la migration qui va avec."""
    with moteur_base.connect() as connexion:
        contexte = MigrationContext.configure(connexion, opts={"compare_type": True, "compare_server_default": True})
        ecarts = compare_metadata(contexte, Base.metadata)

    assert ecarts == []


def test_la_base_de_test_est_a_la_derniere_migration(moteur_base):
    verifier_schema(moteur_base)


def test_on_peut_tout_defaire_puis_tout_refaire():
    url = base_vierge("factures_test_migrations")
    reglages = configuration_alembic(url.render_as_string(hide_password=False))
    moteur = create_engine(url)
    try:
        command.upgrade(reglages, "head")
        command.downgrade(reglages, "base")
        assert set(inspect(moteur).get_table_names()) <= {"alembic_version"}

        command.upgrade(reglages, "head")
        assert {"factures", "evenements"} <= set(inspect(moteur).get_table_names())
    finally:
        moteur.dispose()


def test_le_moteur_refuse_une_base_en_retard():
    url = base_vierge("factures_test_migrations")
    moteur = create_engine(url)
    try:
        with pytest.raises(SchemaPasAJour, match="alembic upgrade head"):
            verifier_schema(moteur)
    finally:
        moteur.dispose()


def test_une_seule_tete_de_migration():
    """Deux migrations parallèles non fusionnées rendraient l'ordre ambigu."""
    assert len(ScriptDirectory.from_config(configuration_alembic()).get_heads()) == 1
