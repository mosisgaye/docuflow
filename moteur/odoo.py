"""Connecteur Odoo : le logiciel de comptabilité et le CRM du client.

DocuFlow lui parle par l'API JSON-2 d'Odoo (POST /json/2/<modèle>/<méthode>), avec la clé
d'API d'un utilisateur technique aux droits limités. XML-RPC et JSON-RPC, dépréciés depuis
Odoo 19, ne sont pas utilisés.

Deux usages :
- à la lecture d'une facture : retrouver le fournisseur dans Odoo par son SIRET ;
- à l'envoi en comptabilité : créer la facture fournisseur dans Odoo, en brouillon, avec
  ses lignes, sa TVA et le PDF d'origine joint. Une facture déjà envoyée n'est jamais créée
  une seconde fois (même fournisseur, même numéro).

Activé quand la clé existe (ODOO_CLE_FICHIER, par défaut donnees/odoo-cle-api).
Réglages : ODOO_URL (http://127.0.0.1:8069), ODOO_BASE (demo).
"""

import base64
import pathlib
from dataclasses import dataclass
from decimal import Decimal

import httpx

from moteur import config
from moteur.export import ErreurEnvoi
from moteur.modeles import Facture

CODES_PASSAGERS = {408, 429, 500, 502, 503, 504}


class ErreurOdoo(ErreurEnvoi):
    """Odoo est injoignable ou a refusé la demande."""

    def __init__(self, message: str, passagere: bool = False):
        super().__init__(message)
        self.passagere = passagere


@dataclass(frozen=True)
class FournisseurOdoo:
    id: int
    nom: str
    siret: str | None
    tva: str | None
    nb_comptes_bancaires: int


class Odoo:
    def __init__(self, url: str, base: str, cle: str, client: httpx.Client | None = None):
        self.url = url.rstrip("/")
        self.base = base
        self._cle = cle
        self._client = client or httpx.Client(timeout=15)

    def __repr__(self) -> str:  # la clé n'apparaît jamais dans un journal
        return f"Odoo({self.url!r}, base={self.base!r})"

    def appeler(self, modele: str, methode: str, **arguments):
        try:
            reponse = self._client.post(
                f"{self.url}/json/2/{modele}/{methode}",
                json=arguments,
                headers={"Authorization": f"bearer {self._cle}", "X-Odoo-Database": self.base},
            )
        except httpx.HTTPError as erreur:
            raise ErreurOdoo(f"Odoo est injoignable ({type(erreur).__name__}).", passagere=True) from erreur
        if reponse.status_code == 401:
            raise ErreurOdoo("Odoo refuse la clé d'API de DocuFlow (clé expirée ou révoquée).")
        if reponse.status_code >= 400:
            try:
                message = reponse.json().get("message", "")
            except ValueError:
                message = ""
            raise ErreurOdoo(f"Odoo a refusé la demande {modele}.{methode} (code {reponse.status_code}) : {message[:200]}", passagere=reponse.status_code in CODES_PASSAGERS)
        return reponse.json()

    def adresse_fiche(self, modele: str, identifiant: int) -> str:
        return f"{self.url}/odoo/{modele}/{identifiant}"

    # ───────── Fournisseurs ─────────

    def trouver_fournisseur(self, siret: str | None, tva: str | None = None) -> FournisseurOdoo | None:
        """Le fournisseur dont le SIRET (ou à défaut le numéro de TVA) correspond.

        Odoo range le SIRET dans des identifiants sur lesquels on ne peut pas filtrer :
        on lit les fiches principales et on compare ici. Suffisant jusqu'à quelques milliers
        de fournisseurs ; au-delà, il faudrait un index côté Odoo.
        """
        if not siret and not tva:
            return None
        fiches = self.appeler(
            "res.partner", "search_read",
            domain=[["parent_id", "=", False]],
            fields=["name", "l10n_fr_siret", "vat", "bank_ids"],
        )
        trouve = next((fiche for fiche in fiches if siret and fiche.get("l10n_fr_siret") == siret), None)
        trouve = trouve or next((fiche for fiche in fiches if tva and fiche.get("vat") == tva), None)
        if trouve is None:
            return None
        return FournisseurOdoo(trouve["id"], trouve["name"], trouve.get("l10n_fr_siret") or None, trouve.get("vat") or None, len(trouve.get("bank_ids") or []))

    # ───────── Factures fournisseurs ─────────

    def _taxe_achat(self, taux: Decimal | None) -> list[int]:
        """La taxe d'achat française au taux de la facture. Services (« S ») de préférence.

        Le choix entre biens et services relève du paramétrage comptable du client.
        """
        if not taux:
            return []
        taxes = self.appeler(
            "account.tax", "search_read",
            domain=[["type_tax_use", "=", "purchase"], ["amount", "=", float(taux)], ["amount_type", "=", "percent"], ["price_include", "=", False]],
            fields=["name"],
        )
        valeur = f"{taux.normalize():f}"
        for nom in (f"{valeur}% S", f"{valeur}% G"):
            for taxe in taxes:
                if taxe["name"] == nom:
                    return [taxe["id"]]
        raise ErreurOdoo(f"Aucune taxe d'achat à {valeur} % dans Odoo.")

    def envoyer_facture(self, donnees: Facture, pdf: bytes | None, nom_pdf: str) -> dict:
        """Crée la facture fournisseur en brouillon dans Odoo. Sans effet si elle y est déjà."""
        fournisseur = self.trouver_fournisseur(donnees.fournisseur_siret, donnees.fournisseur_tva)
        if fournisseur is None:
            raise ErreurOdoo(f"Le fournisseur « {donnees.fournisseur_nom} » (SIRET {donnees.fournisseur_siret}) n'existe pas dans Odoo : créez-le d'abord.")
        existantes = self.appeler(
            "account.move", "search_read",
            domain=[["move_type", "=", "in_invoice"], ["partner_id", "=", fournisseur.id], ["ref", "=", donnees.numero_facture], ["state", "!=", "cancel"]],
            fields=["name", "state", "amount_total"],
        )
        if existantes:
            # Un envoi précédent a pu s'interrompre après la création : on complète ce qui manque.
            self._joindre_pdf(existantes[0]["id"], pdf, nom_pdf)
            return self._compte_rendu(existantes[0], fournisseur, donnees, deja_envoyee=True)

        taxes = self._taxe_achat(donnees.taux_tva)
        valeurs = {
            "move_type": "in_invoice",
            "partner_id": fournisseur.id,
            "ref": donnees.numero_facture,
            "invoice_date": donnees.date_facture.isoformat() if donnees.date_facture else False,
            "invoice_line_ids": [
                [0, 0, {"name": ligne.designation, "quantity": float(ligne.quantite), "price_unit": float(ligne.prix_unitaire_ht), "tax_ids": [[6, 0, taxes]]}]
                for ligne in donnees.lignes
            ],
        }
        if donnees.date_echeance:
            valeurs["invoice_date_due"] = donnees.date_echeance.isoformat()
        identifiant = self.appeler("account.move", "create", vals_list=[valeurs])[0]
        self._joindre_pdf(identifiant, pdf, nom_pdf)
        creee = self.appeler("account.move", "read", ids=[identifiant], fields=["name", "state", "amount_total"])[0]
        return self._compte_rendu(creee, fournisseur, donnees, deja_envoyee=False)

    def _joindre_pdf(self, identifiant: int, pdf: bytes | None, nom_pdf: str) -> None:
        """Joint le PDF d'origine à la facture Odoo, s'il n'y est pas déjà."""
        if not pdf:
            return
        deja = self.appeler("ir.attachment", "search_count", domain=[["res_model", "=", "account.move"], ["res_id", "=", identifiant], ["name", "=", nom_pdf]])
        if deja:
            return
        # Odoo 20 : le contenu passe par « raw » (le champ « datas » n'existe plus), en base64.
        # Pas de type imposé : Odoo le déduit du nom et du contenu.
        self.appeler(
            "ir.attachment", "create",
            vals_list=[{"name": nom_pdf, "raw": base64.b64encode(pdf).decode(), "res_model": "account.move", "res_id": identifiant}],
        )

    def _compte_rendu(self, facture_odoo: dict, fournisseur: FournisseurOdoo, donnees: Facture, deja_envoyee: bool) -> dict:
        total_odoo = Decimal(str(facture_odoo["amount_total"])).quantize(Decimal("0.01"))
        return {
            "logiciel": "odoo",
            "id": facture_odoo["id"],
            "numero": facture_odoo["name"] or None,  # une facture brouillon n'a pas encore de numéro
            "etat": facture_odoo["state"],
            "fournisseur_id": fournisseur.id,
            "total_odoo": f"{total_odoo:.2f}",
            # Odoo recalcule la TVA ligne par ligne : on signale tout écart avec le total lu sur la facture.
            "ecart_total": f"{total_odoo - donnees.total_ttc:.2f}" if donnees.total_ttc is not None and total_odoo != donnees.total_ttc else None,
            "deja_envoyee": deja_envoyee,
            "adresse": self.adresse_fiche("account.move", facture_odoo["id"]),
        }


def depuis_configuration() -> Odoo | None:
    """Le connecteur Odoo, si sa clé d'API est présente. Sinon None : DocuFlow fonctionne sans Odoo."""
    fichier = pathlib.Path(config.lire("ODOO_CLE_FICHIER", str(config.RACINE / "donnees" / "odoo-cle-api")))
    if not fichier.exists():
        return None
    return Odoo(config.lire("ODOO_URL", "http://127.0.0.1:8069"), config.lire("ODOO_BASE", "demo"), fichier.read_text(encoding="utf-8").strip())
