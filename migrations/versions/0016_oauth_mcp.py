"""Connecteur Claude : clients OAuth enregistrés, codes d'autorisation et jetons du serveur MCP de Verifac.

Révision : 0016
Précédente : 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("infos", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("client_id"),
    )
    op.create_table(
        "oauth_codes",
        sa.Column("empreinte", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("compte_id", sa.Uuid(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("code_challenge", sa.String(length=128), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("redirect_explicite", sa.Boolean(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expire_le", sa.DateTime(timezone=True), nullable=False),
        sa.Column("utilise_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["oauth_clients.client_id"]),
        sa.ForeignKeyConstraint(["compte_id"], ["comptes.id"]),
        sa.PrimaryKeyConstraint("empreinte"),
    )
    op.create_index("ix_oauth_codes_client_id", "oauth_codes", ["client_id"])
    op.create_index("ix_oauth_codes_compte_id", "oauth_codes", ["compte_id"])
    op.create_table(
        "oauth_jetons",
        sa.Column("empreinte", sa.String(length=64), nullable=False),
        sa.Column("sorte", sa.String(length=20), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("compte_id", sa.Uuid(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("expire_le", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoque_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("sorte IN ('acces', 'renouvellement')", name="ck_oauth_jetons_sorte"),
        sa.ForeignKeyConstraint(["client_id"], ["oauth_clients.client_id"]),
        sa.ForeignKeyConstraint(["compte_id"], ["comptes.id"]),
        sa.PrimaryKeyConstraint("empreinte"),
    )
    op.create_index("ix_oauth_jetons_client_id", "oauth_jetons", ["client_id"])
    op.create_index("ix_oauth_jetons_compte_id", "oauth_jetons", ["compte_id"])


def downgrade() -> None:
    op.drop_table("oauth_jetons")
    op.drop_table("oauth_codes")
    op.drop_table("oauth_clients")
