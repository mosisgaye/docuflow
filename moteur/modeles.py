"""Forme des données d'une facture, une fois extraites.

Les montants sont des Decimal et non des float : en comptabilité,
0.1 + 0.2 doit faire exactement 0.3.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, field_validator


def _au_centime(montant: Decimal) -> Decimal:
    return montant.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# Un montant en euros, toujours à deux décimales : 1600 devient 1600.00.
# Le prix unitaire n'est pas arrondi, il peut porter plus de deux décimales.
Montant = Annotated[Decimal, AfterValidator(_au_centime)]


class Ligne(BaseModel):
    model_config = ConfigDict(extra="forbid")

    designation: str
    quantite: Decimal
    prix_unitaire_ht: Decimal
    montant_ht: Montant


class Facture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numero_facture: str | None
    date_facture: date | None
    date_echeance: date | None
    fournisseur_nom: str | None
    fournisseur_siret: str | None
    fournisseur_tva: str | None
    # Le compte où payer. Valeur par défaut : les factures lues avant l'ajout de ce champ restent valables.
    fournisseur_iban: str | None = None
    client_nom: str | None
    lignes: list[Ligne]
    total_ht: Montant | None
    taux_tva: Decimal | None
    total_tva: Montant | None
    total_ttc: Montant | None

    @field_validator("fournisseur_iban", "fournisseur_tva")
    @classmethod
    def _sans_espace(cls, valeur: str | None) -> str | None:
        """IBAN et numéro de TVA s'impriment souvent avec des espaces : on les range sans espace et en
        majuscules, quelle que soit la façon dont ils ont été lus (sur une image, l'IA garde parfois les espaces)."""
        return "".join(valeur.split()).upper() or None if valeur else None
