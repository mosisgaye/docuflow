"""Le circuit en graphe (comme n8n) : chaque version publiée et le brouillon gardent le graphe dessiné.

Révision : 0013
Précédente : 0012
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Les versions d'avant gardent NULL : elles se calculent par leurs règles, comme avant.
    op.add_column("regles_approbation", sa.Column("graphe", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("brouillon_circuit", sa.Column("graphe", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("brouillon_circuit", "graphe")
    op.drop_column("regles_approbation", "graphe")
