"""API publique : clés d'accès, abonnements aux événements, livraisons.

Révision : 0009
Précédente : 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cles_api",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("nom", sa.String(length=100), nullable=False),
        sa.Column("prefixe", sa.String(length=16), nullable=False),
        sa.Column("empreinte", sa.String(length=64), nullable=False),
        sa.Column("droits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("creee_par", sa.String(length=100), nullable=False),
        sa.Column("creee_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("utilisee_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoquee_le", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prefixe"),
    )
    op.create_table(
        "abonnements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("evenements", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("actif", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("cree_par", sa.String(length=100), nullable=False),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "livraisons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("abonnement_id", sa.Uuid(), nullable=False),
        sa.Column("evenement", sa.String(length=40), nullable=False),
        sa.Column("charge", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("etat", sa.String(length=20), server_default="en_attente", nullable=False),
        sa.Column("tentatives", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prochain_essai_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("derniere_reponse", sa.Text(), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.Column("livree_le", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["abonnement_id"], ["abonnements.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_livraisons_abonnement_id"), "livraisons", ["abonnement_id"], unique=False)
    op.create_index("ix_livraisons_a_faire", "livraisons", ["prochain_essai_le"], unique=False, postgresql_where=sa.text("etat = 'en_attente'"))


def downgrade() -> None:
    op.drop_index("ix_livraisons_a_faire", table_name="livraisons", postgresql_where=sa.text("etat = 'en_attente'"))
    op.drop_index(op.f("ix_livraisons_abonnement_id"), table_name="livraisons")
    op.drop_table("livraisons")
    op.drop_table("abonnements")
    op.drop_table("cles_api")
