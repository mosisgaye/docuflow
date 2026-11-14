"""Chaque événement du journal porte son heure réelle.

Révision : 0004
Précédente : 0003

now() renvoie l'heure de début de la transaction : tous les événements d'une même
lecture recevaient la même heure, même si la lecture avait duré plusieurs secondes.
clock_timestamp() renvoie l'heure exacte de l'enregistrement.
Les événements déjà enregistrés gardent leur heure.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("evenements", "cree_le", server_default=sa.text("clock_timestamp()"))


def downgrade() -> None:
    op.alter_column("evenements", "cree_le", server_default=sa.text("now()"))
