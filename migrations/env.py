"""Exécution des migrations par Alembic.

La base visée est celle de DATABASE_URL, sauf si l'appelant en fournit une autre
(les tests le font pour travailler sur leur propre base).
"""

from alembic import context
from sqlalchemy import create_engine

from moteur import config
from moteur.base import Base

reglages = context.config
url = reglages.get_main_option("sqlalchemy.url") or config.lire("DATABASE_URL")


def migrer_hors_ligne() -> None:
    """Produit le SQL sans se connecter (alembic upgrade head --sql)."""
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def migrer_en_ligne() -> None:
    connexion_fournie = reglages.attributes.get("connexion")
    if connexion_fournie is not None:
        context.configure(connection=connexion_fournie, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    moteur = create_engine(url)
    with moteur.connect() as connexion:
        context.configure(connection=connexion, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
    moteur.dispose()


if context.is_offline_mode():
    migrer_hors_ligne()
else:
    migrer_en_ligne()
