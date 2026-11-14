"""Schéma initial : les factures et le journal de leurs événements.

Révision : 0001
Précédente : aucune

Reproduit exactement les tables créées avant l'arrivée des migrations.
Une base créée à cette époque se marque simplement avec : alembic stamp 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "factures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("empreinte", sa.String(length=64), nullable=False),
        sa.Column("nom_fichier", sa.String(length=255), nullable=False),
        sa.Column("etat", sa.String(length=20), nullable=False),
        sa.Column("donnees", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("anomalies", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fournisseur_siret", sa.String(length=14), nullable=True),
        sa.Column("numero_facture", sa.String(length=100), nullable=True),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("modifie_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("empreinte"),
    )
    op.create_index(op.f("ix_factures_etat"), "factures", ["etat"], unique=False)
    op.create_index("ix_factures_fournisseur_numero", "factures", ["fournisseur_siret", "numero_facture"], unique=False)
    op.create_table(
        "evenements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("facture_id", sa.Uuid(), nullable=False),
        sa.Column("rang", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("etat", sa.String(length=20), nullable=False),
        sa.Column("auteur", sa.String(length=100), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cree_le", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["facture_id"], ["factures.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_evenements_facture_id"), "evenements", ["facture_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_evenements_facture_id"), table_name="evenements")
    op.drop_table("evenements")
    op.drop_index("ix_factures_fournisseur_numero", table_name="factures")
    op.drop_index(op.f("ix_factures_etat"), table_name="factures")
    op.drop_table("factures")
