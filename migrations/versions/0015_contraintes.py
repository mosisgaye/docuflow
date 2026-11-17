"""Contraintes de cohérence : rang unique dans le journal d'une facture, valeurs permises des états, rôles et niveaux.

Révision : 0015
Précédente : 0014

Les valeurs sont recopiées ici, et non importées du code : une migration décrit la base
telle qu'elle était à cette date, elle ne doit pas changer si le code change ensuite.
Avant d'appliquer, vérifier qu'aucune ligne existante ne sort de ces listes (sinon la migration échoue,
sans rien modifier).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ETATS_FACTURE = ("recue", "extraite", "a_valider", "en_approbation", "en_anomalie", "validee", "rejetee", "exportee", "echec")
ETATS_TACHE = ("en_attente", "terminee", "abandonnee")
ROLES = ("administrateur", "membre", "approbateur", "lecture", "operateur")
NIVEAUX = ("comptable", "directeur_financier", "gerant")

VERIFICATIONS = (
    ("ck_factures_etat", "factures", "etat", ETATS_FACTURE),
    ("ck_evenements_etat", "evenements", "etat", ETATS_FACTURE),
    ("ck_taches_etat", "taches", "etat", ETATS_TACHE),
    ("ck_comptes_role", "comptes", "role", ROLES),
    ("ck_approbations_niveau", "approbations", "niveau", NIVEAUX),
    ("ck_membres_equipe_niveau", "membres_equipe", "niveau", NIVEAUX),
)


def upgrade() -> None:
    op.create_unique_constraint("uq_evenements_facture_rang", "evenements", ["facture_id", "rang"])
    for nom, table, colonne, valeurs in VERIFICATIONS:
        op.create_check_constraint(nom, table, f"{colonne} IN ({', '.join(repr(v) for v in valeurs)})")


def downgrade() -> None:
    for nom, table, _, _ in reversed(VERIFICATIONS):
        op.drop_constraint(nom, table, type_="check")
    op.drop_constraint("uq_evenements_facture_rang", "evenements", type_="unique")
