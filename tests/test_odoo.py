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
        if cible == "account.tax.search_read":
            return [taxe for taxe in self.taxes if taxe["amount"] == corps["domain"][1][2]]
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

    assert [e.type for e in facture.evenements] == ["RECEPTION", "EXTRACTION", "FOURNISSEUR_ODOO", "CONTROLE"]
    assert facture.evenements[2].detail == {"trouve": True, "id": 36, "nom": "Garage Central Bertin", "adresse": "http://odoo.test/odoo/res.partner/36"}
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
