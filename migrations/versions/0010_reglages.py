"""Réglages : l'équipe qui approuve, et le texte des mails reçus sans facture.

Révision : 0010
Précédente : 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mails_recus", sa.Column("texte", sa.Text(), nullable=True))
    op.create_table(
        "membres_equipe",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nom", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("niveau", sa.String(length=40), nullable=False),
        sa.Column("cree_par", sa.String(length=100), nullable=False),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", "niveau", name="uq_membres_equipe_email_niveau"),
    )


def downgrade() -> None:
    op.drop_table("membres_equipe")
    op.drop_column("mails_recus", "texte")
