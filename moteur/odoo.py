"""Connecteur Odoo : le logiciel de comptabilité et le CRM du client.

DocuFlow lui parle par l'API JSON-2 d'Odoo (POST /json/2/<modèle>/<méthode>), avec la clé
d'API d'un utilisateur technique aux droits limités. XML-RPC et JSON-RPC, dépréciés depuis
Odoo 19, ne sont pas utilisés.

Trois usages :
- à la lecture d'une facture : retrouver le fournisseur dans Odoo par son SIRET ;
- à la lecture aussi : la comparer, ligne par ligne, au bon de commande ouvert chez ce
  fournisseur (quantités et prix), ou signaler un achat sans commande ;
- à l'envoi en comptabilité : créer la facture fournisseur dans Odoo, en brouillon, avec
  ses lignes, sa TVA et le PDF d'origine joint. Une facture déjà envoyée n'est jamais créée
  une seconde fois (même fournisseur, même numéro).

Activé quand la clé existe (ODOO_CLE_FICHIER, par défaut donnees/odoo-cle-api).
Réglages : ODOO_URL (http://127.0.0.1:8069), ODOO_BASE (demo).
"""

import base64
import pathlib
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from decimal import Decimal

import httpx

from moteur import config
from moteur.export import ErreurEnvoi
from moteur.modeles import Facture

CODES_PASSAGERS = {408, 429, 500, 502, 503, 504}
RESSEMBLANCE_MIN = 0.85  # deux désignations au-delà de ce score sont la même ligne (« Main d'œuvre » ≈ « Main-d'œuvre »)
CENTIME = Decimal("0.01")


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
    ibans: tuple[str, ...] = ()  # les IBAN connus dans Odoo pour ce fournisseur, sans espace


@dataclass(frozen=True)
class Rapprochement:
    """Comparaison d'une facture avec le bon de commande du fournisseur."""

    statut: str  # "conforme", "ecart" ou "sans_commande"
    commande: str | None = None  # numéro du bon de commande retenu (P00015…)
    commande_id: int | None = None
    ecarts: list[str] = field(default_factory=list)
    lignes: dict[int, int] = field(default_factory=dict)  # rang de la ligne facturée → ligne de commande Odoo


def _normaliser(texte: str) -> str:
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", sans_accents.lower()).strip()


def _euros(montant: Decimal) -> str:
    return f"{montant.quantize(CENTIME):.2f}".replace(".", ",") + " €"


def _quantite(valeur: Decimal) -> str:
    return f"{valeur.normalize():f}".replace(".", ",")


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
        ibans: tuple[str, ...] = ()
        if trouve.get("bank_ids"):
            comptes = self.appeler("res.partner.bank", "search_read", domain=[["partner_id", "=", trouve["id"]]], fields=["account_number"])
            ibans = tuple("".join((compte.get("account_number") or "").split()).upper() for compte in comptes if compte.get("account_number"))
        return FournisseurOdoo(
            trouve["id"], trouve["name"], trouve.get("l10n_fr_siret") or None, trouve.get("vat") or None, len(trouve.get("bank_ids") or []), ibans
        )

    # ───────── Bons de commande ─────────

    def rapprocher(self, fournisseur_id: int, donnees: Facture) -> Rapprochement:
        """Trouve le bon de commande qui correspond le mieux à la facture, puis la compare ligne par ligne.

        On retient la commande confirmée du fournisseur dont le plus de lignes ressemblent aux lignes
        facturées (à égalité, la plus proche en montant). Une ligne facturée sans équivalent, une
        quantité ou un prix différents sont des écarts. Une facture partielle (lignes commandées non
        facturées) n'en est pas un.
        """
        commandes = self.appeler(
            "purchase.order", "search_read",
            domain=[["partner_id", "=", fournisseur_id], ["state", "in", ["purchase", "done"]]],
            fields=["name", "amount_total"],
        )
        if not commandes:
            return Rapprochement("sans_commande")
        lignes_commandes = self.appeler(
            "purchase.order.line", "search_read",
            domain=[["order_id", "in", [commande["id"] for commande in commandes]], ["display_type", "=", False]],
            fields=["order_id", "name", "product_qty", "price_unit"],
        )
        meilleur = None
        for commande in commandes:
            siennes = [ligne for ligne in lignes_commandes if ligne["order_id"][0] == commande["id"]]
            paires = self._apparier(donnees, siennes)
            ecart_montant = abs(Decimal(str(commande["amount_total"])) - (donnees.total_ttc or Decimal("0")))
            cle = (len(paires), -ecart_montant)
            if paires and (meilleur is None or cle > meilleur[0]):
                meilleur = (cle, commande, siennes, paires)
        if meilleur is None:
            return Rapprochement("sans_commande")
        _, commande, siennes, paires = meilleur
        par_id = {ligne["id"]: ligne for ligne in siennes}
        ecarts = []
        for rang, ligne in enumerate(donnees.lignes):
            if rang not in paires:
                ecarts.append(f"« {ligne.designation} » ne figure pas sur la commande")
                continue
            commandee = par_id[paires[rang]]
            prix_commande = Decimal(str(commandee["price_unit"])).quantize(CENTIME)
            quantite_commande = Decimal(str(commandee["product_qty"]))
            if ligne.prix_unitaire_ht is not None and ligne.prix_unitaire_ht.quantize(CENTIME) != prix_commande:
                ecarts.append(f"{ligne.designation} : commandé à {_euros(prix_commande)}, facturé à {_euros(ligne.prix_unitaire_ht)}")
            if ligne.quantite is not None and ligne.quantite != quantite_commande:
                ecarts.append(f"{ligne.designation} : {_quantite(quantite_commande)} commandé(s), {_quantite(ligne.quantite)} facturé(s)")
        return Rapprochement("ecart" if ecarts else "conforme", commande["name"], commande["id"], ecarts, paires)

    @staticmethod
    def _apparier(donnees: Facture, lignes_commande: list[dict]) -> dict[int, int]:
        """Associe chaque ligne facturée à la ligne de commande la plus ressemblante (chacune une seule fois)."""
        candidats = sorted(
            (
                (SequenceMatcher(None, _normaliser(ligne.designation), _normaliser(commandee["name"])).ratio(), rang, commandee["id"])
                for rang, ligne in enumerate(donnees.lignes)
                for commandee in lignes_commande
            ),
            reverse=True,
        )
        paires, prises = {}, set()
        for score, rang, identifiant in candidats:
            if score < RESSEMBLANCE_MIN:
                break
            if rang not in paires and identifiant not in prises:
                paires[rang] = identifiant
                prises.add(identifiant)
        return paires

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
        rapprochement = self.rapprocher(fournisseur.id, donnees)
        lignes = []
        for rang, ligne in enumerate(donnees.lignes):
            valeurs_ligne = {"name": ligne.designation, "quantity": float(ligne.quantite), "price_unit": float(ligne.prix_unitaire_ht), "tax_ids": [[6, 0, taxes]]}
            if rang in rapprochement.lignes:
                # Ligne reliée à sa ligne de commande : c'est le rapprochement natif d'Odoo
                # (quantités facturées mises à jour, alertes d'Odoo en cas d'écart).
                valeurs_ligne["purchase_line_id"] = rapprochement.lignes[rang]
            lignes.append([0, 0, valeurs_ligne])
        valeurs = {
            "move_type": "in_invoice",
            "partner_id": fournisseur.id,
            "ref": donnees.numero_facture,
            "invoice_date": donnees.date_facture.isoformat() if donnees.date_facture else False,
            "invoice_line_ids": lignes,
        }
        if rapprochement.commande:
            valeurs["invoice_origin"] = rapprochement.commande
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
