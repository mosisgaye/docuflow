"""Fabrique les factures PDF d'exemple et le fichier des réponses attendues.

Toutes les sociétés sont fictives. Les SIRET et numéros de TVA ont une clé de
contrôle valide, sauf dans les factures volontairement fausses.

Usage : uv run python -m outils.generer_factures
Nécessite Google Chrome (impression en PDF sans interface).
"""

import json
import pathlib
import subprocess
import tempfile
from decimal import ROUND_HALF_UP, Decimal

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
TAUX = Decimal("20")

STYLES = {
    "bleu": "body{font-family:Helvetica,Arial,sans-serif;color:#222} h1{color:#1d4e89} th{background:#1d4e89;color:#fff}",
    "classique": "body{font-family:Georgia,serif;color:#111} h1{letter-spacing:4px;border-bottom:3px solid #111} th{border-bottom:2px solid #111}",
    "rouge": "body{font-family:Verdana,sans-serif;color:#333;font-size:13px} h1{background:#b3261e;color:#fff;padding:8px} th{background:#eee}",
}

# Chaque facture : ce qui est imprimé, et les anomalies que les contrôles doivent trouver.
MODELES = [
    {
        "fichier": "facture-FA-2026-0412.pdf", "style": "bleu", "numero": "FA-2026-0412",
        "date": "2026-11-03", "echeance": "2026-12-03",
        "fournisseur": ("Atelier Numérique du Midi SARL", "14 rue des Tanneurs, 34000 Montpellier", "81234567600017", "FR19812345676"),
        "client": ("Transports Lemaire SAS", "Zone d'activité des Pins, 30900 Nîmes"),
        "lignes": [("Maintenance applicative (jours)", "5", "450.00"), ("Hébergement serveur, novembre 2026", "1", "120.00"), ("Licence logiciel de suivi", "3", "89.50")],
        "anomalies": [],
    },
    {
        "fichier": "facture-2026-11-087.pdf", "style": "classique", "numero": "2026-11-087",
        "date": "2026-11-07", "echeance": "2026-11-22",
        "fournisseur": ("Papeterie Durand & Fils", "8 avenue de la Gare, 69003 Lyon", "40322198900045", "FR28403221989"),
        "client": ("Cabinet Morel Expertise", "27 quai Saint-Antoine, 69002 Lyon"),
        "lignes": [("Ramettes papier A4 80 g", "40", "4.90"), ("Cartouches toner noir", "6", "62.00"), ("Classeurs à levier", "25", "3.20")],
        "anomalies": [],
    },
    {
        "fichier": "facture-F26-1193.pdf", "style": "rouge", "numero": "F26-1193",
        "date": "2026-11-10", "echeance": "2026-12-10",
        "fournisseur": ("Garage Central Bertin", "52 route de Paris, 45000 Orléans", "52987431500029", "FR52529874315"),
        "client": ("Boulangerie Petit Jean", "3 place du Marché, 45100 Orléans"),
        "lignes": [("Vidange et filtre à huile", "1", "145.00"), ("Plaquettes de frein avant", "1", "98.40"), ("Main-d'œuvre (heures)", "2.5", "62.00")],
        "anomalies": [],
    },
    {
        # Le total TTC imprimé est faux de 100 €.
        "fichier": "facture-erreur-total.pdf", "style": "bleu", "numero": "FA-2026-0431",
        "date": "2026-11-12", "echeance": "2026-12-12",
        "fournisseur": ("Atelier Numérique du Midi SARL", "14 rue des Tanneurs, 34000 Montpellier", "81234567600017", "FR19812345676"),
        "client": ("Transports Lemaire SAS", "Zone d'activité des Pins, 30900 Nîmes"),
        "lignes": [("Développement d'un module d'export", "2", "500.00"), ("Formation des utilisateurs (demi-journée)", "1", "250.00")],
        "ttc_imprime": "1600.00",
        "anomalies": ["TOTAL_TTC_INCOHERENT"],
    },
    {
        # Un chiffre du SIRET est faux : la clé de contrôle ne tombe plus juste.
        "fichier": "facture-erreur-siret.pdf", "style": "classique", "numero": "2026-11-093",
        "date": "2026-11-13", "echeance": "2026-11-28",
        "fournisseur": ("Papeterie Durand & Fils", "8 avenue de la Gare, 69003 Lyon", "40322198900054", "FR28403221989"),
        "client": ("Cabinet Morel Expertise", "27 quai Saint-Antoine, 69002 Lyon"),
        "lignes": [("Enveloppes C4 (boîte de 250)", "4", "18.50"), ("Stylos bille bleus (lot de 50)", "3", "12.00")],
        "anomalies": ["SIRET_INVALIDE"],
    },
    {
        # Facture électronique : le PDF contient le XML Factur-X (profil EN 16931).
        "fichier": "facture-facturx-FX-2026-0057.pdf", "style": "bleu", "numero": "FX-2026-0057",
        "date": "2026-11-12", "echeance": "2026-12-12",
        "fournisseur": ("Imprimerie Lumière SAS", "6 rue des Arts, 31000 Toulouse", "73815042400039", "FR66738150424"),
        "client": ("Transports Lemaire SAS", "Zone d'activité des Pins, 30900 Nîmes"),
        "lignes": [("Flyers A5 quadri (lot de 1000)", "3", "86.00"), ("Cartes de visite (boîte de 500)", "4", "24.50")],
        "anomalies": [],
        "facturx": True,
    },
    {
        # Fournisseur RÉEL, utilisé avec l'accord de son dirigeant, pour montrer une vérification
        # réussie auprès des registres de l'État. Facture de démonstration, marquée « Spécimen ».
        # Entrepreneur en franchise de TVA : pas de TVA, mention de l'article 293 B du CGI.
        "fichier": "facture-md-plomberie-2026-118.pdf", "style": "classique", "numero": "2026-118",
        "date": "2026-11-13", "echeance": "2026-11-28",
        "fournisseur": ("DIOP Mouhamadou (MD Plomberie)", "5 rue Maurice Berteaux, 75020 Paris", "90856344800012", None),
        "client": ("Cabinet Morel Expertise", "27 quai Saint-Antoine, 69002 Lyon"),
        "lignes": [("Remplacement chauffe-eau électrique 200 L", "1", "890.00"), ("Main-d'œuvre (heures)", "3", "55.00"), ("Déplacement", "1", "35.00")],
        "anomalies": [],
        "franchise_tva": True,
        "specimen": True,
    },
]


def arrondi(montant: Decimal) -> Decimal:
    return montant.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def euros(montant: Decimal) -> str:
    entier, _, centimes = f"{arrondi(montant):.2f}".partition(".")
    groupes = []
    while entier:
        groupes.insert(0, entier[-3:])
        entier = entier[:-3]
    return f"{' '.join(groupes)},{centimes} €"


def date_fr(iso: str) -> str:
    annee, mois, jour = iso.split("-")
    return f"{jour}/{mois}/{annee}"


def calculer(modele: dict) -> dict:
    """Renvoie les données de la facture telles qu'elles sont imprimées."""
    lignes = []
    for designation, quantite, prix in modele["lignes"]:
        montant = arrondi(Decimal(quantite) * Decimal(prix))
        lignes.append({"designation": designation, "quantite": quantite, "prix_unitaire_ht": prix, "montant_ht": str(montant)})
    total_ht = sum((Decimal(ligne["montant_ht"]) for ligne in lignes), Decimal("0"))
    taux = Decimal("0") if modele.get("franchise_tva") else TAUX
    total_tva = arrondi(total_ht * taux / 100)
    nom, _, siret, tva = modele["fournisseur"]
    return {
        "numero_facture": modele["numero"],
        "date_facture": modele["date"],
        "date_echeance": modele["echeance"],
        "fournisseur_nom": nom,
        "fournisseur_siret": siret,
        "fournisseur_tva": tva,
        "client_nom": modele["client"][0],
        "lignes": lignes,
        "total_ht": str(total_ht),
        "taux_tva": str(taux),
        "total_tva": str(total_tva),
        "total_ttc": modele.get("ttc_imprime", str(total_ht + total_tva)),
    }


def html(modele: dict, donnees: dict) -> str:
    _, adresse, siret, tva = modele["fournisseur"]
    siret_affiche = f"{siret[:3]} {siret[3:6]} {siret[6:9]} {siret[9:]}"
    ligne_tva = f"<br>TVA {tva[:4]} {tva[4:]}" if tva else ""
    if modele.get("franchise_tva"):
        totaux = (f"<tr><td>Total HT</td><td class=r>{euros(Decimal(donnees['total_ht']))}</td></tr>"
                  "<tr><td colspan=2><i>TVA non applicable, art. 293 B du CGI</i></td></tr>"
                  f"<tr><td>Net à payer</td><td class=r>{euros(Decimal(donnees['total_ttc']))}</td></tr>")
    else:
        totaux = (f"<tr><td>Total HT</td><td class=r>{euros(Decimal(donnees['total_ht']))}</td></tr>"
                  f"<tr><td>TVA {TAUX} %</td><td class=r>{euros(Decimal(donnees['total_tva']))}</td></tr>"
                  f"<tr><td>Total TTC</td><td class=r>{euros(Decimal(donnees['total_ttc']))}</td></tr>")
    if modele.get("specimen"):
        pied = "SPÉCIMEN : facture de démonstration, aucune prestation réelle. Fournisseur réel cité avec son accord."
        filigrane = ("<div style='position:fixed;top:38%;left:0;right:0;text-align:center;transform:rotate(-24deg);"
                     "font:700 110px Helvetica,Arial,sans-serif;color:rgba(179,38,30,.13);letter-spacing:8px'>SPÉCIMEN</div>")
    else:
        pied = "Paiement par virement à 30 jours. Document d'exemple, données fictives."
        filigrane = ""
    rangees = "".join(
        f"<tr><td>{ligne['designation']}</td><td class=r>{ligne['quantite'].replace('.', ',')}</td>"
        f"<td class=r>{euros(Decimal(ligne['prix_unitaire_ht']))}</td><td class=r>{euros(Decimal(ligne['montant_ht']))}</td></tr>"
        for ligne in donnees["lignes"]
    )
    return f"""<!doctype html><html lang=fr><meta charset=utf-8><style>@page{{size:A4;margin:18mm}}{STYLES[modele['style']]}
table{{width:100%;border-collapse:collapse;margin-top:24px}} td,th{{padding:7px 9px;text-align:left;border-bottom:1px solid #ccc}} .r{{text-align:right}}
.cols{{display:flex;justify-content:space-between;margin-top:20px}} .tot{{width:45%;margin-left:55%}} .tot td{{border:0}} .tot tr:last-child td{{font-weight:bold;border-top:2px solid #333}}
.foot{{margin-top:40px;font-size:11px;color:#666}}</style>
<h1>FACTURE</h1>
<p><b>Facture n° {donnees['numero_facture']}</b><br>Date de facture : {date_fr(donnees['date_facture'])}<br>Date d'échéance : {date_fr(donnees['date_echeance'])}</p>
{filigrane}
<div class=cols><div><b>{donnees['fournisseur_nom']}</b><br>{adresse}<br>SIRET {siret_affiche}{ligne_tva}</div>
<div><i>Facturé à</i><br><b>{modele['client'][0]}</b><br>{modele['client'][1]}</div></div>
<table><tr><th>Désignation</th><th class=r>Quantité</th><th class=r>Prix unitaire HT</th><th class=r>Montant HT</th></tr>{rangees}</table>
<table class=tot>{totaux}</table>
<p class=foot>{pied}</p></html>"""


def cii_xml(modele: dict, donnees: dict) -> bytes:
    """XML de la facture au format CII, profil EN 16931, tel qu'attendu dans un Factur-X."""
    from xml.sax.saxutils import escape

    def jour(iso: str) -> str:
        return f'<udt:DateTimeString format="102">{iso.replace("-", "")}</udt:DateTimeString>'

    def adresse(texte: str) -> str:
        rue, _, ville = texte.rpartition(", ")
        code, _, commune = ville.partition(" ")
        return (f"<ram:PostalTradeAddress><ram:PostcodeCode>{code}</ram:PostcodeCode><ram:LineOne>{escape(rue)}</ram:LineOne>"
                f"<ram:CityName>{escape(commune)}</ram:CityName><ram:CountryID>FR</ram:CountryID></ram:PostalTradeAddress>")

    nom, adresse_vendeur, siret, tva = modele["fournisseur"]
    taxe = '<ram:TypeCode>VAT</ram:TypeCode><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>20</ram:RateApplicablePercent>'
    lignes = "".join(
        f"""<ram:IncludedSupplyChainTradeLineItem>
      <ram:AssociatedDocumentLineDocument><ram:LineID>{rang}</ram:LineID></ram:AssociatedDocumentLineDocument>
      <ram:SpecifiedTradeProduct><ram:Name>{escape(ligne["designation"])}</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount>{ligne["prix_unitaire_ht"]}</ram:ChargeAmount></ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">{ligne["quantite"]}</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
      <ram:SpecifiedLineTradeSettlement>
        <ram:ApplicableTradeTax>{taxe}</ram:ApplicableTradeTax>
        <ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>{ligne["montant_ht"]}</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation>
      </ram:SpecifiedLineTradeSettlement>
    </ram:IncludedSupplyChainTradeLineItem>"""
        for rang, ligne in enumerate(donnees["lignes"], start=1)
    )
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100" xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100" xmlns:qdt="urn:un:unece:uncefact:data:standard:QualifiedDataType:100">
  <rsm:ExchangedDocumentContext>
    <ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>urn:cen.eu:en16931:2017</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter>
  </rsm:ExchangedDocumentContext>
  <rsm:ExchangedDocument>
    <ram:ID>{donnees["numero_facture"]}</ram:ID>
    <ram:TypeCode>380</ram:TypeCode>
    <ram:IssueDateTime>{jour(donnees["date_facture"])}</ram:IssueDateTime>
  </rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    {lignes}
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty>
        <ram:Name>{escape(nom)}</ram:Name>
        <ram:SpecifiedLegalOrganization><ram:ID schemeID="0009">{siret}</ram:ID></ram:SpecifiedLegalOrganization>
        {adresse(adresse_vendeur)}
        <ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{tva}</ram:ID></ram:SpecifiedTaxRegistration>
      </ram:SellerTradeParty>
      <ram:BuyerTradeParty>
        <ram:Name>{escape(modele["client"][0])}</ram:Name>
        {adresse(modele["client"][1])}
      </ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeDelivery/>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:ApplicableTradeTax>
        <ram:CalculatedAmount>{donnees["total_tva"]}</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode>
        <ram:BasisAmount>{donnees["total_ht"]}</ram:BasisAmount><ram:CategoryCode>S</ram:CategoryCode><ram:RateApplicablePercent>20</ram:RateApplicablePercent>
      </ram:ApplicableTradeTax>
      <ram:SpecifiedTradePaymentTerms><ram:DueDateDateTime>{jour(donnees["date_echeance"])}</ram:DueDateDateTime></ram:SpecifiedTradePaymentTerms>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:LineTotalAmount>{donnees["total_ht"]}</ram:LineTotalAmount>
        <ram:TaxBasisTotalAmount>{donnees["total_ht"]}</ram:TaxBasisTotalAmount>
        <ram:TaxTotalAmount currencyID="EUR">{donnees["total_tva"]}</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>{donnees["total_ttc"]}</ram:GrandTotalAmount>
        <ram:DuePayableAmount>{donnees["total_ttc"]}</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""
    return xml.encode("utf-8")


def joindre_facturx(pdf: bytes, xml: bytes) -> bytes:
    """Joint le XML au PDF selon la norme Factur-X, après l'avoir vérifié contre le schéma officiel."""
    import facturx

    return facturx.generate_from_binary(pdf, xml, flavor="factur-x", level="en16931", check_xsd=True)


def main() -> None:
    attendu = {}
    with tempfile.TemporaryDirectory() as dossier:
        for modele in MODELES:
            donnees = calculer(modele)
            page = pathlib.Path(dossier) / "facture.html"
            page.write_text(html(modele, donnees), encoding="utf-8")
            subprocess.run(
                ["google-chrome", "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                 f"--print-to-pdf={FACTURES / modele['fichier']}", page.as_uri()],
                check=True, capture_output=True,
            )
            if modele.get("facturx"):
                chemin = FACTURES / modele["fichier"]
                chemin.write_bytes(joindre_facturx(chemin.read_bytes(), cii_xml(modele, donnees)))
            attendu[modele["fichier"]] = {"facture": donnees, "anomalies": modele["anomalies"]}
            print(f"{modele['fichier']:28} TTC imprimé {donnees['total_ttc']:>8} | anomalies attendues : {modele['anomalies'] or 'aucune'}")
    (FACTURES / "attendu.json").write_text(json.dumps(attendu, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
