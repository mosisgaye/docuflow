"""Connecteur Odoo : fournisseur retrouvé, facture fournisseur créée une seule fois, pannes."""

import base64
import json
import pathlib
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from moteur.api import creer_application
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture
from moteur.odoo import ErreurOdoo, Odoo
from moteur.workflow import exporter, traiter, valider

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
GARAGE = "facture-F26-1193.pdf"
FRANCHISE = "facture-md-plomberie-2026-118.pdf"
AUJOURD_HUI = date(2026, 11, 14)


def donnees(nom: str) -> Facture:
    return Facture.model_validate(ATTENDU[nom]["facture"])


class FauxOdoo:
    """Répond comme l'API JSON-2 d'Odoo 20, pour les quelques méthodes utilisées par DocuFlow."""

    def __init__(self):
        self.partenaires = [
            {"id": 36, "name": "Garage Central Bertin", "l10n_fr_siret": "52987431500029", "vat": "FR52529874315", "bank_ids": [7]},
            {"id": 40, "name": "DIOP Mouhamadou (MD Plomberie)", "l10n_fr_siret": "90856344800012", "vat": False, "bank_ids": []},
        ]
        self.taxes = [{"id": 1, "name": "20% G", "amount": 20.0}, {"id": 21, "name": "20% S", "amount": 20.0}]
        # Le compte bancaire connu du garage (le même que sur ses vraies factures).
        self.comptes = {36: ["FR76 1820 6004 0065 0001 2398 765"]}
        # Le bon de commande du garage : les plaquettes avaient été commandées à 85,00 €.
        self.commandes = [{"id": 15, "name": "P00015", "partner_id": 36, "amount_total": 462.0}]
        self.lignes_commandes = [
            {"id": 101, "order_id": [15, "P00015"], "name": "Vidange et filtre à huile", "product_qty": 1.0, "price_unit": 145.0},
            {"id": 102, "order_id": [15, "P00015"], "name": "Plaquettes de frein avant", "product_qty": 1.0, "price_unit": 85.0},
            {"id": 103, "order_id": [15, "P00015"], "name": "Main d'oeuvre (heures)", "product_qty": 2.5, "price_unit": 62.0},
        ]
        self.factures, self.pieces, self.appels = [], [], []
        self.panne: int | None = None  # code HTTP à renvoyer
        self.panne_sur: str | None = None  # « modèle.méthode » à faire échouer, sinon tout

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        _, _, modele, methode = requete.url.path.strip("/").split("/")
        cible = f"{modele}.{methode}"
        self.appels.append(cible)
        if requete.headers.get("Authorization") != "bearer cle-de-test":
            return httpx.Response(401, json={"message": "Invalid apikey"})
        if self.panne and self.panne_sur in (None, cible):
            return httpx.Response(self.panne, json={"message": "panne simulée"})
        corps = json.loads(requete.content or b"{}")
        return httpx.Response(200, json=self.repondre(cible, corps))

    def repondre(self, cible: str, corps: dict):
        if cible == "res.partner.search_read":
            return self.partenaires
        if cible == "res.partner.bank.search_read":
            return [{"account_number": numero} for numero in self.comptes.get(corps["domain"][0][2], [])]
        if cible == "account.tax.search_read":
            return [taxe for taxe in self.taxes if taxe["amount"] == corps["domain"][1][2]]
        if cible == "purchase.order.search_read":
            fournisseur = corps["domain"][0][2]
            return [commande for commande in self.commandes if commande["partner_id"] == fournisseur]
        if cible == "purchase.order.line.search_read":
            commandes = corps["domain"][0][2]
            return [ligne for ligne in self.lignes_commandes if ligne["order_id"][0] in commandes]
        if cible == "account.move.search_read":
            filtres = {champ: valeur for champ, _, valeur in corps["domain"]}
            return [f for f in self.factures if f["partner_id"] == filtres["partner_id"] and f["ref"] == filtres["ref"]]
        if cible == "account.move.create":
            valeurs = corps["vals_list"][0]
            total = 0.0
            for _, _, ligne in valeurs["invoice_line_ids"]:
                taux = 20.0 if ligne["tax_ids"][0][2] else 0.0
                total += round(ligne["quantity"] * ligne["price_unit"] * (1 + taux / 100), 2)
            facture = {"id": len(self.factures) + 1, "name": False, "state": "draft", "amount_total": round(total, 2), **valeurs}
            self.factures.append(facture)
            return [facture["id"]]
        if cible == "account.move.read":
            return [f for f in self.factures if f["id"] in corps["ids"]]
        if cible == "ir.attachment.search_count":
            filtres = {champ: valeur for champ, _, valeur in corps["domain"]}
            return sum(1 for p in self.pieces if p["res_id"] == filtres["res_id"] and p["name"] == filtres["name"])
        if cible == "ir.attachment.create":
            self.pieces.append(corps["vals_list"][0])
            return [len(self.pieces)]
        raise AssertionError(f"appel inattendu : {cible}")


@pytest.fixture
def faux():
    return FauxOdoo()


@pytest.fixture
def odoo(faux):
    return Odoo("http://odoo.test", "demo", "cle-de-test", httpx.Client(transport=httpx.MockTransport(faux)))


# ───────── Fournisseurs ─────────


def test_le_fournisseur_est_retrouve_par_son_siret(odoo):
    fournisseur = odoo.trouver_fournisseur("52987431500029")

    assert (fournisseur.id, fournisseur.nom, fournisseur.nb_comptes_bancaires) == (36, "Garage Central Bertin", 1)
    assert fournisseur.ibans == ("FR7618206004006500012398765",)  # sans espace, pour comparer


def test_a_defaut_de_siret_le_numero_de_tva_suffit(odoo):
    assert odoo.trouver_fournisseur("52987431500028", "FR52529874315").id == 36  # SIRET mal lu, TVA juste


def test_un_fournisseur_absent_d_odoo(odoo):
    assert odoo.trouver_fournisseur("81234567600017") is None
    assert odoo.trouver_fournisseur(None, None) is None


def test_la_cle_n_apparait_jamais(odoo):
    assert "cle-de-test" not in repr(odoo)


# ───────── Factures fournisseurs ─────────


def test_la_facture_fournisseur_est_creee_avec_ses_lignes_et_son_pdf(odoo, faux):
    compte_rendu = odoo.envoyer_facture(donnees(GARAGE), b"%PDF-1.7 contenu", GARAGE)

    facture = faux.factures[0]
    assert (facture["move_type"], facture["partner_id"], facture["ref"], facture["invoice_date"]) == ("in_invoice", 36, "F26-1193", "2026-11-10")
    assert [ligne[2]["tax_ids"] for ligne in facture["invoice_line_ids"]] == [[[6, 0, [21]]]] * 3  # TVA à 20 %, services
    # Chaque ligne est reliée à sa ligne de commande : le rapprochement natif d'Odoo.
    assert [ligne[2]["purchase_line_id"] for ligne in facture["invoice_line_ids"]] == [101, 102, 103]
    assert facture["invoice_origin"] == "P00015"
    assert base64.b64decode(faux.pieces[0]["raw"]) == b"%PDF-1.7 contenu"
    assert compte_rendu["total_odoo"] == "478.08"
    assert compte_rendu["ecart_total"] is None
    assert compte_rendu["deja_envoyee"] is False
    assert compte_rendu["adresse"] == "http://odoo.test/odoo/account.move/1"


def test_un_second_envoi_ne_cree_pas_de_doublon(odoo, faux):
    odoo.envoyer_facture(donnees(GARAGE), b"%PDF", GARAGE)

    compte_rendu = odoo.envoyer_facture(donnees(GARAGE), b"%PDF", GARAGE)

    assert compte_rendu["deja_envoyee"] is True
    assert len(faux.factures) == 1
    assert len(faux.pieces) == 1


def test_un_envoi_interrompu_avant_le_pdf_est_complete_au_nouvel_essai(odoo, faux):
    faux.panne, faux.panne_sur = 503, "ir.attachment.create"
    with pytest.raises(ErreurOdoo):
        odoo.envoyer_facture(donnees(GARAGE), b"%PDF", GARAGE)
    assert len(faux.factures) == 1 and faux.pieces == []

    faux.panne = None
    compte_rendu = odoo.envoyer_facture(donnees(GARAGE), b"%PDF", GARAGE)

    assert compte_rendu["deja_envoyee"] is True
    assert len(faux.factures) == 1
    assert len(faux.pieces) == 1


def test_un_fournisseur_en_franchise_n_a_pas_de_tva(odoo, faux):
    compte_rendu = odoo.envoyer_facture(donnees(FRANCHISE), None, FRANCHISE)

    assert [ligne[2]["tax_ids"] for ligne in faux.factures[0]["invoice_line_ids"]] == [[[6, 0, []]]] * 3
    assert compte_rendu["total_odoo"] == "1090.00"
    assert "account.tax.search_read" not in faux.appels


def test_un_ecart_de_total_avec_odoo_est_signale(odoo, faux):
    facture = donnees(GARAGE).model_copy(update={"total_ttc": donnees(GARAGE).total_ttc + 1})

    assert odoo.envoyer_facture(facture, None, GARAGE)["ecart_total"] == "-1.00"


def test_un_fournisseur_inconnu_empeche_l_envoi(odoo):
    with pytest.raises(ErreurOdoo, match="n'existe pas dans Odoo"):
        odoo.envoyer_facture(donnees("facture-FA-2026-0412.pdf"), None, "x.pdf")


# ───────── Pannes ─────────


@pytest.mark.parametrize(("code", "passagere"), [(503, True), (429, True), (403, False), (400, False)])
def test_une_panne_d_odoo_dit_si_elle_est_passagere(odoo, faux, code, passagere):
    faux.panne = code

    with pytest.raises(ErreurOdoo) as erreur:
        odoo.trouver_fournisseur("52987431500029")

    assert erreur.value.passagere is passagere


def test_une_cle_refusee_est_expliquee(faux):
    odoo = Odoo("http://odoo.test", "demo", "mauvaise-cle", httpx.Client(transport=httpx.MockTransport(faux)))

    with pytest.raises(ErreurOdoo, match="refuse la clé"):
        odoo.trouver_fournisseur("52987431500029")


def test_odoo_injoignable(faux):
    def coupe(requete):
        raise httpx.ConnectError("refusé")

    odoo = Odoo("http://odoo.test", "demo", "cle-de-test", httpx.Client(transport=httpx.MockTransport(coupe)))

    with pytest.raises(ErreurOdoo) as erreur:
        odoo.trouver_fournisseur("52987431500029")
    assert erreur.value.passagere is True


# ───────── Dans le circuit de DocuFlow ─────────


def extracteur(nom: str):
    return lambda texte: ResultatExtraction(donnees(nom), 0.1, "test", "faux")


def test_a_la_lecture_le_fournisseur_reconnu_est_note_au_journal(session, odoo):
    facture = traiter(session, (FACTURES / GARAGE).read_bytes(), GARAGE, extracteur(GARAGE), AUJOURD_HUI, odoo=odoo).facture

    assert [e.type for e in facture.evenements] == ["RECEPTION", "EXTRACTION", "FOURNISSEUR_ODOO", "COMMANDE_ODOO", "CONTROLE"]
    assert facture.evenements[2].detail == {
        "trouve": True, "id": 36, "nom": "Garage Central Bertin", "adresse": "http://odoo.test/odoo/res.partner/36", "iban": "conforme",
    }
    assert facture.evenements[3].detail["commande"] == "P00015"
    assert facture.evenements[3].detail["adresse"] == "http://odoo.test/odoo/purchase.order/15"
    # L'écart de prix est un avertissement : la personne le voit, la facture reste validable.
    assert [(a["code"], a["gravite"]) for a in facture.anomalies] == [("ECART_COMMANDE", "avertissement")]
    assert "commandé à 85,00 €, facturé à 98,40 €" in facture.anomalies[0]["message"]
    assert facture.etat == "a_valider"


def test_un_fournisseur_inconnu_d_odoo_donne_un_avertissement(session, odoo):
    nom = "facture-FA-2026-0412.pdf"
    facture = traiter(session, (FACTURES / nom).read_bytes(), nom, extracteur(nom), AUJOURD_HUI, odoo=odoo).facture

    assert [(a["code"], a["gravite"]) for a in facture.anomalies] == [("FOURNISSEUR_INCONNU", "avertissement")]
    assert facture.etat == "a_valider"  # un avertissement n'empêche pas la validation


def test_odoo_en_panne_n_empeche_pas_la_lecture(session, odoo, faux):
    faux.panne = 503

    facture = traiter(session, (FACTURES / GARAGE).read_bytes(), GARAGE, extracteur(GARAGE), AUJOURD_HUI, odoo=odoo).facture

    assert facture.etat == "a_valider"
    assert facture.anomalies == []
    assert "ODOO_INDISPONIBLE" in [e.type for e in facture.evenements]


def test_l_export_cree_la_facture_dans_odoo(session, odoo, faux, tmp_path):
    contenu = (FACTURES / GARAGE).read_bytes()
    facture = traiter(session, contenu, GARAGE, extracteur(GARAGE), AUJOURD_HUI, odoo=odoo).facture
    valider(session, facture.id, "Moussa")
    (tmp_path / f"{facture.empreinte}.pdf").write_bytes(contenu)

    exporter(session, facture.id, "Moussa", tmp_path / "exports", odoo=odoo, dossier_fichiers=tmp_path)

    assert facture.etat == "exportee"
    envoi = facture.evenements[-1].detail["logiciel"]
    assert (envoi["logiciel"], envoi["id"], envoi["total_odoo"]) == ("odoo", 1, "478.08")
    assert base64.b64decode(faux.pieces[0]["raw"]) == contenu  # le PDF d'origine, intact


def test_si_odoo_refuse_la_facture_reste_validee(session, odoo, faux, tmp_path):
    facture = traiter(session, (FACTURES / GARAGE).read_bytes(), GARAGE, extracteur(GARAGE), AUJOURD_HUI, odoo=odoo).facture
    valider(session, facture.id, "Moussa")
    faux.panne = 503

    with pytest.raises(ErreurOdoo):
        exporter(session, facture.id, "Moussa", tmp_path, odoo=odoo, dossier_fichiers=tmp_path)

    assert facture.etat == "validee"
    assert facture.evenements[-1].type == "EXPORT_ECHOUE"


def test_par_l_api_un_refus_d_odoo_repond_502(connexion, odoo, faux, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    client = TestClient(creer_application(fabrique_session=fabrique, extracteur=extracteur(GARAGE), dossier_fichiers=tmp_path, traiter_tout_de_suite=True, odoo=odoo))
    facture = client.post("/factures", files={"fichier": (GARAGE, (FACTURES / GARAGE).read_bytes(), "application/pdf")}).json()
    client.post(f"/factures/{facture['id']}/validation", json={"auteur": "Moussa"})
    faux.panne = 503

    reponse = client.post(f"/factures/{facture['id']}/export", json={"auteur": "Moussa"})

    assert reponse.status_code == 502
    assert "Odoo" in reponse.json()["detail"]


# ───────── Bons de commande ─────────


def test_une_facture_conforme_a_sa_commande(odoo, faux):
    faux.lignes_commandes[1]["price_unit"] = 98.40

    rapprochement = odoo.rapprocher(36, donnees(GARAGE))

    assert (rapprochement.statut, rapprochement.commande, rapprochement.ecarts) == ("conforme", "P00015", [])
    # « Main d'oeuvre » sur la commande, « Main-d'œuvre » sur la facture : c'est la même ligne.
    assert rapprochement.lignes == {0: 101, 1: 102, 2: 103}


def test_chaque_ecart_est_explique(odoo, faux):
    faux.lignes_commandes[0]["product_qty"] = 2.0
    faux.lignes_commandes.pop()  # la main-d'œuvre n'était pas commandée

    rapprochement = odoo.rapprocher(36, donnees(GARAGE))

    assert rapprochement.statut == "ecart"
    assert rapprochement.ecarts == [
        "Vidange et filtre à huile : 2 commandé(s), 1 facturé(s)",
        "Plaquettes de frein avant : commandé à 85,00 €, facturé à 98,40 €",
        "« Main-d'œuvre (heures) » ne figure pas sur la commande",
    ]


def test_un_achat_sans_commande(odoo, faux):
    faux.commandes = []

    assert odoo.rapprocher(36, donnees(GARAGE)).statut == "sans_commande"


def test_la_commande_retenue_est_celle_qui_ressemble_le_plus_a_la_facture(odoo, faux):
    faux.commandes.append({"id": 16, "name": "P00016", "partner_id": 36, "amount_total": 478.08})
    faux.lignes_commandes.append({"id": 201, "order_id": [16, "P00016"], "name": "Pneus hiver", "product_qty": 4.0, "price_unit": 119.52})

    assert odoo.rapprocher(36, donnees(GARAGE)).commande == "P00015"  # même montant, mais rien de commun


def test_un_achat_sans_commande_donne_un_avertissement_a_la_lecture(session, odoo, faux):
    faux.commandes = []

    facture = traiter(session, (FACTURES / GARAGE).read_bytes(), GARAGE, extracteur(GARAGE), AUJOURD_HUI, odoo=odoo).facture

    assert [(a["code"], a["gravite"]) for a in facture.anomalies] == [("SANS_COMMANDE", "avertissement")]
    assert facture.etat == "a_valider"


# ───────── IBAN : la fraude au changement de coordonnées bancaires ─────────

FRAUDE = "facture-iban-modifie.pdf"  # le garage, mais un autre IBAN : « suite à un changement de banque »


def test_la_facture_frauduleuse_est_signalee(session, odoo):
    facture = traiter(session, (FACTURES / FRAUDE).read_bytes(), FRAUDE, extracteur(FRAUDE), AUJOURD_HUI, odoo=odoo).facture

    codes = {a["code"]: a for a in facture.anomalies}
    assert codes["IBAN_DIFFERENT"]["gravite"] == "avertissement"
    message = codes["IBAN_DIFFERENT"]["message"]
    assert "…9894" in message and "…8765" in message  # l'IBAN reçu et celui connu, masqués
    assert "FR7616958" not in message  # jamais l'IBAN en entier
    assert "jamais à celui écrit sur la facture" in message
    assert next(e for e in facture.evenements if e.type == "FOURNISSEUR_ODOO").detail["iban"] == "different"


def test_avec_les_regles_la_fraude_exige_le_directeur_financier(session, odoo):
    from moteur.approbation import REGLES_DEMO, publier

    publier(session, REGLES_DEMO, "Moussa")
    facture = traiter(session, (FACTURES / FRAUDE).read_bytes(), FRAUDE, extracteur(FRAUDE), AUJOURD_HUI, odoo=odoo).facture

    niveaux = {n["niveau"]: n["raisons"] for n in facture.circuit["niveaux"]}
    assert "IBAN différent de celui connu, ou jamais vu" in niveaux["directeur_financier"]


def test_le_bon_iban_ne_dit_rien(session, odoo):
    facture = traiter(session, (FACTURES / GARAGE).read_bytes(), GARAGE, extracteur(GARAGE), AUJOURD_HUI, odoo=odoo).facture

    assert "IBAN_DIFFERENT" not in {a["code"] for a in facture.anomalies}


def test_un_fournisseur_sans_iban_connu_demande_une_verification(session, odoo, faux):
    faux.comptes = {}

    facture = traiter(session, (FACTURES / GARAGE).read_bytes(), GARAGE, extracteur(GARAGE), AUJOURD_HUI, odoo=odoo).facture

    assert ("IBAN_NOUVEAU", "avertissement") in {(a["code"], a["gravite"]) for a in facture.anomalies}


def test_une_facture_sans_iban_ne_declenche_rien(session, odoo):
    sans = donnees(GARAGE).model_copy(update={"fournisseur_iban": None})

    facture = traiter(session, (FACTURES / GARAGE).read_bytes(), GARAGE, lambda texte: ResultatExtraction(sans, 0.1, "test", "faux"), AUJOURD_HUI, odoo=odoo).facture

    assert not {"IBAN_DIFFERENT", "IBAN_NOUVEAU"} & {a["code"] for a in facture.anomalies}
    assert next(e for e in facture.evenements if e.type == "FOURNISSEUR_ODOO").detail["iban"] == "absent"
