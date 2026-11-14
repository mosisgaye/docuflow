"""Lecture directe d'une facture électronique Factur-X, sans IA.

Une facture Factur-X est un PDF lisible par un humain, qui contient en pièce jointe
un fichier XML au format européen CII (norme EN 16931). Quand ce XML est présent,
les données sont exactes par construction : on les lit, on n'a pas besoin de l'IA.

C'est le format de la réforme française de la facturation électronique (2026-2027).
Le XML vient d'un fichier reçu de l'extérieur : il est lu avec defusedxml, qui refuse
les XML piégés (entités externes, expansions en chaîne).
"""

import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import Element

from defusedxml import ElementTree
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from moteur.modeles import Facture, Ligne

# Version du lecteur, notée au journal à chaque lecture. À changer si la correspondance
# entre le XML et les champs de la facture change.
LECTEUR = "facturx-cii-1"

# Noms usuels du XML joint : Factur-X (France), ZUGFeRD (Allemagne), XRechnung.
NOMS_XML = {"factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml"}

ESPACES = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}

# Codes ISO 6523 de l'identifiant légal du vendeur.
SIRET = "0009"
SIREN = "0002"


class FacturXInvalide(Exception):
    """Le PDF contient un XML Factur-X, mais il est illisible ou incomplet."""


def xml_joint(contenu: bytes) -> bytes | None:
    """Renvoie le XML Factur-X joint au PDF, ou None s'il n'y en a pas."""
    try:
        pieces = PdfReader(io.BytesIO(contenu)).attachments
    except (PyPdfError, KeyError, ValueError):
        return None
    for nom, versions in pieces.items():
        if nom.lower() in NOMS_XML and versions:
            return versions[0]
    return None


def _texte(noeud: Element, chemin: str) -> str | None:
    trouve = noeud.find(chemin, ESPACES)
    return trouve.text.strip() if trouve is not None and trouve.text else None


def _montant(noeud: Element, chemin: str) -> Decimal | None:
    valeur = _texte(noeud, chemin)
    if valeur is None:
        return None
    try:
        return Decimal(valeur)
    except InvalidOperation as erreur:
        raise FacturXInvalide(f"Montant illisible dans {chemin} : {valeur!r}") from erreur


def _date(noeud: Element, chemin: str) -> date | None:
    valeur = _texte(noeud, chemin)
    if valeur is None:
        return None
    try:
        return datetime.strptime(valeur, "%Y%m%d").date()  # format 102 de la norme
    except ValueError as erreur:
        raise FacturXInvalide(f"Date illisible dans {chemin} : {valeur!r}") from erreur


def lire_xml(xml: bytes) -> Facture:
    """Transforme le XML CII en Facture."""
    try:
        racine = ElementTree.fromstring(xml)
    except Exception as erreur:  # noqa: BLE001 - defusedxml lève plusieurs types d'erreurs
        raise FacturXInvalide(f"XML illisible : {type(erreur).__name__}") from erreur
    if racine.tag != f"{{{ESPACES['rsm']}}}CrossIndustryInvoice":
        raise FacturXInvalide("Ce XML n'est pas une facture au format CII.")

    document = "rsm:ExchangedDocument"
    transaction = "rsm:SupplyChainTradeTransaction"
    vendeur = f"{transaction}/ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty"
    reglement = f"{transaction}/ram:ApplicableHeaderTradeSettlement"
    totaux = f"{reglement}/ram:SpecifiedTradeSettlementHeaderMonetarySummation"

    siret = None
    identifiant = racine.find(f"{vendeur}/ram:SpecifiedLegalOrganization/ram:ID", ESPACES)
    if identifiant is not None and identifiant.get("schemeID") == SIRET:
        siret = (identifiant.text or "").strip() or None
    numero_tva = None
    for enregistrement in racine.findall(f"{vendeur}/ram:SpecifiedTaxRegistration/ram:ID", ESPACES):
        if enregistrement.get("schemeID") == "VA":
            numero_tva = (enregistrement.text or "").strip() or None

    taux = {_montant(taxe, "ram:RateApplicablePercent") for taxe in racine.findall(f"{reglement}/ram:ApplicableTradeTax", ESPACES)}
    taux.discard(None)

    lignes = []
    for article in racine.findall(f"{transaction}/ram:IncludedSupplyChainTradeLineItem", ESPACES):
        quantite = _montant(article, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity")
        prix = _montant(article, "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount")
        montant = _montant(article, "ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount")
        designation = _texte(article, "ram:SpecifiedTradeProduct/ram:Name")
        if None in (quantite, prix, montant, designation):
            raise FacturXInvalide("Une ligne de la facture est incomplète.")
        lignes.append(Ligne(designation=designation, quantite=quantite, prix_unitaire_ht=prix, montant_ht=montant))

    return Facture(
        numero_facture=_texte(racine, f"{document}/ram:ID"),
        date_facture=_date(racine, f"{document}/ram:IssueDateTime/udt:DateTimeString"),
        date_echeance=_date(racine, f"{reglement}/ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString"),
        fournisseur_nom=_texte(racine, f"{vendeur}/ram:Name"),
        fournisseur_siret=siret,
        fournisseur_tva=numero_tva,
        client_nom=_texte(racine, f"{transaction}/ram:ApplicableHeaderTradeAgreement/ram:BuyerTradeParty/ram:Name"),
        lignes=lignes,
        total_ht=_montant(racine, f"{totaux}/ram:TaxBasisTotalAmount"),
        # Une facture à plusieurs taux n'a pas de taux unique : on laisse vide.
        taux_tva=taux.pop() if len(taux) == 1 else None,
        total_tva=_montant(racine, f"{totaux}/ram:TaxTotalAmount"),
        total_ttc=_montant(racine, f"{totaux}/ram:GrandTotalAmount"),
    )


def lire_facturx(contenu: bytes) -> Facture | None:
    """Renvoie la facture si le PDF est un Factur-X, None sinon. Lève FacturXInvalide si le XML est mauvais."""
    xml = xml_joint(contenu)
    return None if xml is None else lire_xml(xml)
