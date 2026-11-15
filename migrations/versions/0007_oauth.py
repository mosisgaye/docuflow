"""Connexion des connecteurs par compte (OAuth) : demandes en cours et jetons chiffrés.

Révision : 0007
Précédente : 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demandes_oauth",
        sa.Column("etat", sa.String(length=64), nullable=False),
        sa.Column("connecteur", sa.String(length=40), nullable=False),
        sa.Column("verificateur", sa.Text(), nullable=False),
        sa.Column("auteur", sa.String(length=100), nullable=False),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("etat"),
    )
    op.create_table(
        "jetons_connecteurs",
        sa.Column("connecteur", sa.String(length=40), nullable=False),
        sa.Column("acces", sa.Text(), nullable=False),
        sa.Column("renouvellement", sa.Text(), nullable=True),
        sa.Column("expire_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("modifie_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("connecteur"),
    )


def downgrade() -> None:
    op.drop_table("jetons_connecteurs")
    op.drop_table("demandes_oauth")
