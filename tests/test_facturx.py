import io
import json
import pathlib
from datetime import date
from decimal import Decimal

import pytest
from pypdf import PdfReader, PdfWriter

from moteur.base import Etat
from moteur.extraction_llm import ResultatExtraction
from moteur.facturx import FacturXInvalide, lire_facturx, lire_xml, xml_joint
from moteur.modeles import Facture
from moteur.workflow import traiter

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
FACTURX = "facture-facturx-FX-2026-0057.pdf"
PDF_FACTURX = (FACTURES / FACTURX).read_bytes()
XML = xml_joint(PDF_FACTURX)


class LLMEspion:
    def __init__(self, nom: str = "facture-F26-1193.pdf"):
        self.facture = Facture.model_validate(ATTENDU[nom]["facture"])
        self.appels = 0

    def __call__(self, texte: str) -> ResultatExtraction:
        self.appels += 1
        return ResultatExtraction(self.facture, 0.1, "test", "faux")


def pdf_avec_xml(xml: bytes, nom: str = "factur-x.xml") -> bytes:
    """Un PDF ordinaire auquel on joint un XML donné."""
    ecrivain = PdfWriter(clone_from=PdfReader(io.BytesIO((FACTURES / "facture-F26-1193.pdf").read_bytes())))
    ecrivain.add_attachment(nom, xml)
    tampon = io.BytesIO()
    ecrivain.write(tampon)
    return tampon.getvalue()


# ───────── Lecture ─────────


def test_le_xml_d_une_facture_facturx_est_trouve():
    assert XML is not None
    assert b"CrossIndustryInvoice" in XML


def test_une_facture_facturx_est_lue_exactement():
    assert lire_facturx(PDF_FACTURX) == Facture.model_validate(ATTENDU[FACTURX]["facture"])


def test_une_facture_ordinaire_n_est_pas_un_facturx():
    assert lire_facturx((FACTURES / "facture-F26-1193.pdf").read_bytes()) is None


def test_un_autre_fichier_joint_est_ignore():
    assert lire_facturx(pdf_avec_xml(XML, "conditions-generales.xml")) is None


def test_le_nom_du_xml_joint_est_reconnu_sans_tenir_compte_des_majuscules():
    assert lire_facturx(pdf_avec_xml(XML, "Factur-X.xml")).numero_facture == "FX-2026-0057"


def test_seul_le_siret_est_retenu_comme_identifiant():
    xml = XML.replace(b'schemeID="0009">73815042400039', b'schemeID="0002">738150424')

    assert lire_xml(xml).fournisseur_siret is None


def test_une_facture_a_plusieurs_taux_n_a_pas_de_taux_unique():
    taxe = b"<ram:ApplicableTradeTax>\n        <ram:CalculatedAmount>"
    second = (b"<ram:ApplicableTradeTax><ram:CalculatedAmount>1.00</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode>"
              b"<ram:BasisAmount>10.00</ram:BasisAmount><ram:CategoryCode>S</ram:CategoryCode>"
              b"<ram:RateApplicablePercent>10</ram:RateApplicablePercent></ram:ApplicableTradeTax>\n      ")
    xml = XML.replace(taxe, second + taxe, 1)

    assert lire_xml(xml).taux_tva is None


@pytest.mark.parametrize(
    ("remplacer", "par"),
    [
        (b"<ram:GrandTotalAmount>427.20<", b"<ram:GrandTotalAmount>quatre cents<"),
        (b">20261112<", b">12/11/2026<"),
        (b"rsm:CrossIndustryInvoice", b"rsm:AutreChose"),
        (b"<ram:LineTotalAmount>258.00</ram:LineTotalAmount>", b""),
    ],
)
def test_un_xml_abime_est_refuse(remplacer, par):
    assert remplacer in XML

    with pytest.raises(FacturXInvalide):
        lire_xml(XML.replace(remplacer, par))


def test_un_xml_piege_est_refuse():
    piege = b"""<?xml version="1.0"?>
<!DOCTYPE bombe [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100">&c;</rsm:CrossIndustryInvoice>"""

    with pytest.raises(FacturXInvalide):
        lire_xml(piege)


def test_un_fichier_externe_ne_peut_pas_etre_lu_par_le_xml():
    piege = b"""<?xml version="1.0"?>
<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100">&secret;</rsm:CrossIndustryInvoice>"""

    with pytest.raises(FacturXInvalide):
        lire_xml(piege)


# ───────── Dans le workflow ─────────


def test_une_facture_facturx_est_traitee_sans_appeler_l_ia(session):
    llm = LLMEspion()

    facture = traiter(session, PDF_FACTURX, FACTURX, llm, date(2026, 11, 14)).facture

    assert llm.appels == 0
    assert facture.etat == Etat.A_VALIDER
    assert facture.numero_facture == "FX-2026-0057"
    assert facture.donnees["total_ttc"] == "427.20"
    assert facture.evenements[1].detail["source"] == "factur-x"
    assert "modele" not in facture.evenements[1].detail


def test_un_facturx_abime_se_rabat_sur_l_ia(session):
    llm = LLMEspion()
    abime = pdf_avec_xml(XML.replace(b"<ram:GrandTotalAmount>427.20<", b"<ram:GrandTotalAmount>???<"))

    facture = traiter(session, abime, "abime.pdf", llm, date(2026, 11, 14)).facture

    assert llm.appels == 1
    assert [evenement.type for evenement in facture.evenements] == ["RECEPTION", "FACTURX_ILLISIBLE", "EXTRACTION", "CONTROLE"]
    assert facture.evenements[2].detail["source"] == "ia"
    assert facture.donnees["total_ttc"] == str(Decimal("478.08"))
