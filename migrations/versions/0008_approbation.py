"""Workflow d'approbation : règles versionnées, circuit de chaque facture, approbations.

Révision : 0008
Précédente : 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("factures", sa.Column("circuit", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_table(
        "regles_approbation",
        sa.Column("version", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("regles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("publie_par", sa.String(length=100), nullable=False),
        sa.Column("publie_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("version"),
    )
    op.create_table(
        "approbations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("facture_id", sa.Uuid(), nullable=False),
        sa.Column("niveau", sa.String(length=40), nullable=False),
        sa.Column("personne", sa.String(length=100), nullable=False),
        sa.Column("empreinte_donnees", sa.String(length=64), nullable=False),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.ForeignKeyConstraint(["facture_id"], ["factures.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("facture_id", "niveau", name="uq_approbations_facture_niveau"),
    )
    op.create_index(op.f("ix_approbations_facture_id"), "approbations", ["facture_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_approbations_facture_id"), table_name="approbations")
    op.drop_table("approbations")
    op.drop_table("regles_approbation")
    op.drop_column("factures", "circuit")
