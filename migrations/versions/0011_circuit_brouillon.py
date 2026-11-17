"""Éditeur de circuit : le brouillon, et les relances réglables par niveau dans chaque version.

Révision : 0011
Précédente : 0010
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Les versions déjà publiées gardent NULL : les délais par défaut, comme avant.
    op.add_column("regles_approbation", sa.Column("relances", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_table(
        "brouillon_circuit",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("regles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("relances", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("modifie_par", sa.String(length=100), nullable=False),
        sa.Column("modifie_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_brouillon_circuit_unique"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("brouillon_circuit")
    op.drop_column("regles_approbation", "relances")
