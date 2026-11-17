"""Comptes et connexion : les personnes qui utilisent Verifac, leurs rôles, et les demandes de connexion.

Révision : 0014
Précédente : 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comptes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nom", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("niveaux", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("actif", sa.Boolean(), nullable=False),
        sa.Column("version_session", sa.Integer(), nullable=False),
        sa.Column("cree_par", sa.String(length=100), nullable=False),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("derniere_connexion", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_comptes_email"),
    )
    op.create_table(
        "demandes_connexion",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("compte_id", sa.Uuid(), nullable=False),
        sa.Column("empreinte_jeton", sa.String(length=64), nullable=False),
        sa.Column("empreinte_code", sa.String(length=64), nullable=False),
        sa.Column("essais", sa.Integer(), nullable=False),
        sa.Column("expire_le", sa.DateTime(timezone=True), nullable=False),
        sa.Column("utilisee_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["compte_id"], ["comptes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empreinte_jeton", name="uq_demandes_connexion_jeton"),
    )
    op.create_index("ix_demandes_connexion_compte_id", "demandes_connexion", ["compte_id"])


def downgrade() -> None:
    op.drop_index("ix_demandes_connexion_compte_id", table_name="demandes_connexion")
    op.drop_table("demandes_connexion")
    op.drop_table("comptes")
