"""File des tâches de lecture, prises par le travailleur.

Révision : 0003
Précédente : 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "taches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("facture_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=20), server_default="lecture", nullable=False),
        sa.Column("etat", sa.String(length=20), server_default="en_attente", nullable=False),
        sa.Column("tentatives", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prochain_essai_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("derniere_erreur", sa.Text(), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("modifie_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["facture_id"], ["factures.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_taches_facture_id"), "taches", ["facture_id"], unique=False)
    op.create_index("ix_taches_a_faire", "taches", ["prochain_essai_le"], unique=False, postgresql_where=sa.text("etat = 'en_attente'"))
    op.create_index("uq_taches_une_en_attente", "taches", ["facture_id"], unique=True, postgresql_where=sa.text("etat = 'en_attente'"))


def downgrade() -> None:
    op.drop_index("uq_taches_une_en_attente", table_name="taches", postgresql_where=sa.text("etat = 'en_attente'"))
    op.drop_index("ix_taches_a_faire", table_name="taches", postgresql_where=sa.text("etat = 'en_attente'"))
    op.drop_index(op.f("ix_taches_facture_id"), table_name="taches")
    op.drop_table("taches")
