"""Programme pilote : les demandes de place envoyées depuis le site vitrine.

Révision : 0017
Précédente : 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demandes_pilote",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nom", sa.String(length=100), nullable=False),
        sa.Column("entreprise", sa.String(length=150), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("volume", sa.String(length=40), nullable=False),
        sa.Column("logiciel", sa.String(length=60), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_demandes_pilote_cree_le", "demandes_pilote", ["cree_le"])


def downgrade() -> None:
    op.drop_index("ix_demandes_pilote_cree_le", table_name="demandes_pilote")
    op.drop_table("demandes_pilote")
