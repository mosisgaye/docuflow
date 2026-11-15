"""Les mails reçus à l'adresse de dépôt des factures.

Révision : 0005
Précédente : 0004

Une ligne par mail, repéré par son Message-ID : le même mail reçu deux fois
n'est traité qu'une fois. La colonne pieces garde ce qu'on a fait de chaque
pièce jointe (facture créée, déjà reçue, ou ignorée avec la raison).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mails_recus",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.String(length=998), nullable=False),
        sa.Column("expediteur", sa.String(length=320), nullable=False),
        sa.Column("objet", sa.Text(), server_default="", nullable=False),
        sa.Column("statut", sa.String(length=20), nullable=False),
        sa.Column("pieces", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("recu_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
    )


def downgrade() -> None:
    op.drop_table("mails_recus")
