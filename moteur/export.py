"""Export d'une facture validée vers la comptabilité.

Une facture d'achat devient une écriture au journal des achats :

    compte de charge (6...)        débit   = total HT
    TVA déductible (44566)         débit   = total TVA
    fournisseur (401)              crédit  = total TTC

L'écriture est équilibrée (total des débits = total des crédits) : le moteur le vérifie
avant tout envoi. Elle est écrite dans un fichier CSV importable, et envoyée au logiciel
du client si une adresse est configurée (EXPORT_WEBHOOK_URL).

Les comptes sont des réglages par défaut. Chez un vrai client, le compte de charge dépend
du fournisseur et de la nature de la dépense : c'est un paramétrage à faire avec le comptable.
"""

import csv
import io
from dataclasses import asdict, dataclass
from decimal import Decimal

import httpx

from moteur import config
from moteur.modeles import Facture

JOURNAL = "HA"  # journal des achats
COMPTE_TVA_DEDUCTIBLE = "445660"
COMPTE_FOURNISSEURS = "401000"


class ErreurExport(Exception):
    """L'écriture est incomplète ou déséquilibrée, ou le logiciel tiers a refusé l'envoi."""


class ErreurEnvoi(ErreurExport):
    """Le logiciel de comptabilité est injoignable ou a refusé l'écriture."""


@dataclass(frozen=True)
class LigneEcriture:
    journal: str
    date: str
    piece: str
    compte: str
    compte_auxiliaire: str
    libelle: str
    debit: Decimal
    credit: Decimal
    echeance: str


def compte_auxiliaire(facture: Facture) -> str:
    """Compte du fournisseur dans la comptabilité, construit à partir de son SIREN."""
    return f"F{facture.fournisseur_siret[:9]}" if facture.fournisseur_siret else "FDIVERS"


def ecriture(facture: Facture) -> list[LigneEcriture]:
    manquants = [champ for champ in ("numero_facture", "date_facture", "total_ht", "total_tva", "total_ttc") if getattr(facture, champ) is None]
    if manquants:
        raise ErreurExport(f"Écriture impossible, information manquante : {', '.join(manquants)}.")
    commun = {
        "journal": JOURNAL,
        "date": facture.date_facture.isoformat(),
        "piece": facture.numero_facture,
        "echeance": facture.date_echeance.isoformat() if facture.date_echeance else "",
    }
    libelle = f"{facture.fournisseur_nom or 'Fournisseur'} fact. {facture.numero_facture}"[:60]
    zero = Decimal("0.00")
    lignes = [
        LigneEcriture(**commun, compte=config.lire("EXPORT_COMPTE_CHARGE", "606000"), compte_auxiliaire="", libelle=libelle, debit=facture.total_ht, credit=zero),
        LigneEcriture(**commun, compte=COMPTE_TVA_DEDUCTIBLE, compte_auxiliaire="", libelle=libelle, debit=facture.total_tva, credit=zero),
        LigneEcriture(**commun, compte=COMPTE_FOURNISSEURS, compte_auxiliaire=compte_auxiliaire(facture), libelle=libelle, debit=zero, credit=facture.total_ttc),
    ]
    debits = sum((ligne.debit for ligne in lignes), zero)
    credits = sum((ligne.credit for ligne in lignes), zero)
    if debits != credits:
        raise ErreurExport(f"Écriture déséquilibrée : {debits} au débit, {credits} au crédit.")
    return [ligne for ligne in lignes if ligne.debit or ligne.credit]


def en_csv(lignes: list[LigneEcriture]) -> str:
    """CSV à la française : point-virgule, virgule décimale, ouvrable dans Excel."""
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
    ecrivain.writerow(["Journal", "Date", "Piece", "Compte", "CompteAuxiliaire", "Libelle", "Debit", "Credit", "Echeance"])
    for ligne in lignes:
        ecrivain.writerow(
            [ligne.journal, ligne.date, ligne.piece, ligne.compte, ligne.compte_auxiliaire, ligne.libelle,
             f"{ligne.debit:.2f}".replace(".", ","), f"{ligne.credit:.2f}".replace(".", ","), ligne.echeance]
        )
    return "﻿" + tampon.getvalue()


def en_json(lignes: list[LigneEcriture]) -> list[dict]:
    return [{**asdict(ligne), "debit": f"{ligne.debit:.2f}", "credit": f"{ligne.credit:.2f}"} for ligne in lignes]


def envoyer_au_logiciel(facture_id: str, lignes: list[LigneEcriture], client: httpx.Client | None = None) -> dict | None:
    """Envoie l'écriture au logiciel du client, si une adresse est configurée.

    La clé d'idempotence est l'identifiant de la facture : si l'envoi est rejoué
    après une coupure, le logiciel peut reconnaître l'écriture et ne pas la doubler.
    """
    adresse = config.lire("EXPORT_WEBHOOK_URL", "")
    if not adresse:
        return None
    client = client or httpx.Client(timeout=10)
    try:
        reponse = client.post(adresse, json={"facture_id": facture_id, "ecriture": en_json(lignes)}, headers={"Idempotency-Key": facture_id})
    except httpx.HTTPError as erreur:
        raise ErreurEnvoi(f"Le logiciel de comptabilité est injoignable : {type(erreur).__name__}.") from erreur
    if reponse.status_code >= 300:
        raise ErreurEnvoi(f"Le logiciel de comptabilité a refusé l'écriture (code {reponse.status_code}).")
    return {"adresse": adresse, "statut": reponse.status_code}


def nom_fichier(facture: Facture, facture_id: str) -> str:
    """Toujours le même nom pour une facture donnée : un nouvel essai réécrit le fichier au lieu d'en créer un second."""
    numero = "".join(caractere if caractere.isalnum() or caractere in "-_" else "_" for caractere in facture.numero_facture or "sans-numero")
    return f"{numero}_{facture_id[:8]}.csv"
