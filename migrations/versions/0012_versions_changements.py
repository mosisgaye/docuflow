"""Chaque version publiée garde la liste lisible de ce qu'elle a changé : la trace des publications.

Révision : 0012
Précédente : 0011
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Les versions publiées avant l'éditeur gardent NULL : on ne sait pas ce qu'elles ont changé.
    op.add_column("regles_approbation", sa.Column("changements", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("regles_approbation", "changements")
