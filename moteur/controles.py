"""Contrôles métier d'une facture, sans IA.

Le LLM propose des données ; ces règles décident si elles sont cohérentes.
Chaque règle est une petite fonction qui renvoie la liste des anomalies trouvées.
Une règle ne modifie jamais la facture.

Limite connue : le modèle porte un seul taux de TVA par facture.
Une facture à plusieurs taux sera signalée comme incohérente.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from moteur.modeles import Facture

CENTIME = Decimal("0.01")
# Taux de TVA en vigueur en France métropolitaine.
TAUX_TVA_FRANCE = {Decimal("20"), Decimal("10"), Decimal("5.5"), Decimal("2.1"), Decimal("0")}
CHAMPS_OBLIGATOIRES = [
    "numero_facture",
    "date_facture",
    "fournisseur_nom",
    "fournisseur_siret",
    "client_nom",
    "total_ht",
    "total_tva",
    "total_ttc",
]


class Gravite(StrEnum):
    BLOQUANTE = "bloquante"  # la facture ne peut pas être validée telle quelle
    AVERTISSEMENT = "avertissement"  # à regarder, sans empêcher la validation


@dataclass(frozen=True)
class Anomalie:
    code: str
    gravite: Gravite
    message: str
    champ: str | None = None


def _arrondi(montant: Decimal) -> Decimal:
    return montant.quantize(CENTIME, rounding=ROUND_HALF_UP)


def _ecart(a: Decimal, b: Decimal) -> bool:
    """Vrai si les deux montants diffèrent de plus d'un centime."""
    return abs(a - b) > CENTIME


def _euros(montant: Decimal) -> str:
    return f"{_arrondi(montant):.2f}".replace(".", ",") + " €"


def cle_de_luhn_valide(chiffres: str) -> bool:
    """Algorithme de Luhn, utilisé pour les numéros SIREN et SIRET."""
    total = 0
    for rang, caractere in enumerate(reversed(chiffres)):
        chiffre = int(caractere)
        if rang % 2 == 1:
            chiffre *= 2
            if chiffre > 9:
                chiffre -= 9
        total += chiffre
    return total % 10 == 0


SIREN_LA_POSTE = "356000000"


def iban_normalise(iban: str) -> str:
    return "".join(iban.split()).upper()


def iban_valide(iban: str) -> bool:
    """Structure et clé de contrôle d'un IBAN (norme ISO 13616 : le reste de la division par 97 vaut 1)."""
    iban = iban_normalise(iban)
    if not (15 <= len(iban) <= 34 and iban[:2].isalpha() and iban[2:4].isdigit() and iban.isalnum()):
        return False
    if iban.startswith("FR") and len(iban) != 27:
        return False
    return int("".join(str(int(caractere, 36)) for caractere in iban[4:] + iban[:4])) % 97 == 1


def siret_correct(siret: str) -> bool:
    """14 chiffres, clé du SIRET ET clé du SIREN (ses 9 premiers chiffres) justes.

    Exception officielle : les établissements de La Poste partagent un même SIREN et leur
    SIRET suit une autre règle (somme des chiffres divisible par 5).
    """
    if len(siret) != 14 or not siret.isdigit():
        return False
    if siret.startswith(SIREN_LA_POSTE):
        return sum(int(chiffre) for chiffre in siret) % 5 == 0
    return cle_de_luhn_valide(siret) and cle_de_luhn_valide(siret[:9])


def cle_tva_attendue(siren: str) -> str:
    """Clé à deux chiffres d'un numéro de TVA français, calculée à partir du SIREN."""
    return f"{(12 + 3 * (int(siren) % 97)) % 97:02d}"


def champs_obligatoires(facture: Facture) -> list[Anomalie]:
    return [
        Anomalie("CHAMP_MANQUANT", Gravite.BLOQUANTE, f"Information obligatoire absente : {champ}.", champ)
        for champ in CHAMPS_OBLIGATOIRES
        if getattr(facture, champ) in (None, "")
    ]


def lignes(facture: Facture) -> list[Anomalie]:
    if not facture.lignes:
        return [Anomalie("AUCUNE_LIGNE", Gravite.BLOQUANTE, "La facture ne contient aucune ligne.", "lignes")]
    anomalies = []
    for rang, ligne in enumerate(facture.lignes, start=1):
        calcule = _arrondi(ligne.quantite * ligne.prix_unitaire_ht)
        if _ecart(calcule, ligne.montant_ht):
            anomalies.append(
                Anomalie(
                    "LIGNE_INCOHERENTE",
                    Gravite.BLOQUANTE,
                    f"Ligne {rang} : {ligne.quantite} × {_euros(ligne.prix_unitaire_ht)} font {_euros(calcule)}, "
                    f"la facture indique {_euros(ligne.montant_ht)}.",
                    "lignes",
                )
            )
    return anomalies


def totaux(facture: Facture) -> list[Anomalie]:
    anomalies = []
    if facture.lignes and facture.total_ht is not None:
        somme = sum((ligne.montant_ht for ligne in facture.lignes), Decimal("0"))
        if _ecart(somme, facture.total_ht):
            anomalies.append(
                Anomalie(
                    "TOTAL_HT_INCOHERENT",
                    Gravite.BLOQUANTE,
                    f"La somme des lignes fait {_euros(somme)}, le total HT indique {_euros(facture.total_ht)}.",
                    "total_ht",
                )
            )
    if None not in (facture.total_ht, facture.total_tva, facture.total_ttc):
        attendu = facture.total_ht + facture.total_tva
        if _ecart(attendu, facture.total_ttc):
            anomalies.append(
                Anomalie(
                    "TOTAL_TTC_INCOHERENT",
                    Gravite.BLOQUANTE,
                    f"HT + TVA font {_euros(attendu)}, le total TTC indique {_euros(facture.total_ttc)}.",
                    "total_ttc",
                )
            )
    return anomalies


def tva(facture: Facture) -> list[Anomalie]:
    if facture.taux_tva is None:
        return []
    anomalies = []
    if facture.taux_tva not in TAUX_TVA_FRANCE:
        anomalies.append(
            Anomalie(
                "TAUX_TVA_INCONNU",
                Gravite.AVERTISSEMENT,
                f"Le taux de TVA de {facture.taux_tva} % n'est pas un taux français courant.",
                "taux_tva",
            )
        )
    if None not in (facture.total_ht, facture.total_tva):
        attendue = _arrondi(facture.total_ht * facture.taux_tva / 100)
        if _ecart(attendue, facture.total_tva):
            anomalies.append(
                Anomalie(
                    "TVA_INCOHERENTE",
                    Gravite.BLOQUANTE,
                    f"{facture.taux_tva} % de {_euros(facture.total_ht)} font {_euros(attendue)}, "
                    f"la facture indique {_euros(facture.total_tva)} de TVA.",
                    "total_tva",
                )
            )
    return anomalies


def identifiants(facture: Facture) -> list[Anomalie]:
    anomalies = []
    siret = facture.fournisseur_siret
    siret_valide = bool(siret) and siret_correct(siret)
    if siret and not siret_valide:
        anomalies.append(
            Anomalie(
                "SIRET_INVALIDE",
                Gravite.BLOQUANTE,
                f"Le SIRET {siret} est invalide : il faut 14 chiffres et une clé de contrôle correcte.",
                "fournisseur_siret",
            )
        )
    numero_tva = facture.fournisseur_tva
    if numero_tva and numero_tva.startswith("FR"):
        cle, siren = numero_tva[2:4], numero_tva[4:]
        if len(numero_tva) != 13 or not siren.isdigit() or not cle.isdigit() or cle != cle_tva_attendue(siren):
            anomalies.append(
                Anomalie(
                    "TVA_INTRACOM_INVALIDE",
                    Gravite.BLOQUANTE,
                    f"Le numéro de TVA {numero_tva} est invalide : format ou clé de contrôle incorrects.",
                    "fournisseur_tva",
                )
            )
        elif siret_valide and siren != siret[:9]:
            anomalies.append(
                Anomalie(
                    "TVA_SIRET_DIFFERENTS",
                    Gravite.BLOQUANTE,
                    f"Le numéro de TVA {numero_tva} ne correspond pas au SIRET {siret}.",
                    "fournisseur_tva",
                )
            )
    if facture.fournisseur_iban and not iban_valide(facture.fournisseur_iban):
        anomalies.append(
            Anomalie(
                "IBAN_INVALIDE",
                Gravite.BLOQUANTE,
                f"L'IBAN lu ({facture.fournisseur_iban}) est invalide : sa clé de contrôle ne tombe pas juste. "
                "Erreur de lecture ou faux IBAN : comparez avec la facture, et ne payez pas sur ce compte avant d'avoir vérifié.",
                "fournisseur_iban",
            )
        )
    return anomalies


def dates(facture: Facture, aujourd_hui: date) -> list[Anomalie]:
    anomalies = []
    if facture.date_facture and facture.date_facture > aujourd_hui:
        anomalies.append(
            Anomalie(
                "DATE_FUTURE",
                Gravite.AVERTISSEMENT,
                f"La date de facture ({facture.date_facture:%d/%m/%Y}) est dans le futur.",
                "date_facture",
            )
        )
    if facture.date_facture and facture.date_echeance and facture.date_echeance < facture.date_facture:
        anomalies.append(
            Anomalie(
                "ECHEANCE_AVANT_FACTURE",
                Gravite.BLOQUANTE,
                f"L'échéance ({facture.date_echeance:%d/%m/%Y}) est antérieure à la date de facture "
                f"({facture.date_facture:%d/%m/%Y}).",
                "date_echeance",
            )
        )
    return anomalies


def controler(facture: Facture, aujourd_hui: date | None = None) -> list[Anomalie]:
    """Passe tous les contrôles et renvoie les anomalies, bloquantes en premier."""
    aujourd_hui = aujourd_hui or date.today()
    anomalies = [
        *champs_obligatoires(facture),
        *lignes(facture),
        *totaux(facture),
        *tva(facture),
        *identifiants(facture),
        *dates(facture, aujourd_hui),
    ]
    return sorted(anomalies, key=lambda anomalie: anomalie.gravite != Gravite.BLOQUANTE)


def est_validable(anomalies: list[Anomalie]) -> bool:
    return not any(anomalie.gravite == Gravite.BLOQUANTE for anomalie in anomalies)


# Les avertissements qui signalent un risque de fraude au changement de coordonnées bancaires.
# La facture reste approuvable (un fournisseur change vraiment de banque), mais elle passe en tête
# des listes et son approbation exige de confirmer que le fournisseur a été appelé.
CODES_RISQUE = frozenset({"IBAN_DIFFERENT", "IBAN_NOUVEAU"})


def a_risque(anomalies: list[dict]) -> bool:
    """Vrai si une anomalie enregistrée (telle que rangée en base) signale un risque de fraude."""
    return any(anomalie.get("code") in CODES_RISQUE for anomalie in anomalies or [])
