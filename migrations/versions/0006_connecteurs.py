"""Les connecteurs branchés et le journal de leurs appels.

Révision : 0006
Précédente : 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "connecteurs",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("actif", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("outils_autorises", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("branche_par", sa.String(length=100), nullable=False),
        sa.Column("branche_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "appels_connecteurs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("connecteur", sa.String(length=40), nullable=False),
        sa.Column("outil", sa.String(length=100), nullable=False),
        sa.Column("arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("statut", sa.String(length=20), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("duree_ms", sa.Integer(), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_appels_connecteurs_connecteur"), "appels_connecteurs", ["connecteur"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_appels_connecteurs_connecteur"), table_name="appels_connecteurs")
    op.drop_table("appels_connecteurs")
    op.drop_table("connecteurs")
