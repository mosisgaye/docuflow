# Exécuté DANS Odoo (odoo shell), par outils/odoo_remplir.py qui définit DONNEES avant ce texte.
# Remplit l'entreprise de démonstration. Relançable : ce qui existe déjà n'est pas recréé.
# Les lignes « >> » sont le compte rendu ; la ligne « CLE_API: » est lue par l'outil et jamais affichée.

from datetime import datetime, timedelta


def compte_rendu(*morceaux):
    print(">>", *morceaux)


societe = env.company
pays_fr = env.ref("base.fr")
taxes = {
    "service": env["account.tax"].search([("type_tax_use", "=", "purchase"), ("name", "=", "20% S"), ("company_id", "=", societe.id)], limit=1),
    "consu": env["account.tax"].search([("type_tax_use", "=", "purchase"), ("name", "=", "20% G"), ("company_id", "=", societe.id)], limit=1),
}


def partenaire(valeurs):
    """Cherche la société par son SIRET, sinon la crée.

    Le SIRET est rangé dans les identifiants additionnels d'Odoo, sur lesquels on ne peut pas
    chercher en base : on compare donc en Python, ce qui suffit pour quelques dizaines de fiches.
    """
    # On cherche parmi toutes les fiches principales (sans parent), pas seulement les « sociétés » :
    # dans Odoo 20, la case société est calculée et reste décochée sans numéro de TVA
    # (entreprise en franchise de TVA comme MD Plomberie, clients saisis sans TVA).
    Partenaire = env["res.partner"].with_context(active_test=False)
    trouve = Partenaire.search([("parent_id", "=", False)], order="id").filtered(lambda fiche: fiche.l10n_fr_siret == valeurs["l10n_fr_siret"])[:1]
    if trouve:
        return trouve, False
    return Partenaire.create(valeurs), True


# ───────── Fournisseurs ─────────
fournisseurs = {}
for f in DONNEES["fournisseurs"]:
    valeurs = {
        "name": f["nom"], "is_company": True, "supplier_rank": 1,
        "street": f["rue"], "zip": f["code_postal"], "city": f["ville"], "country_id": pays_fr.id,
        "l10n_fr_siret": f["siret"], "vat": f["tva"] or False, "email": f.get("email") or False,
        "comment": f.get("note") or False,
    }
    fiche, cree = partenaire(valeurs)
    if f.get("iban") and not fiche.bank_ids:
        env["res.partner.bank"].create({"partner_id": fiche.id, "account_number": f["iban"], "holder_name": f["nom"], "allow_out_payment": True})
    if f.get("contact") and not fiche.child_ids:
        env["res.partner"].create({"parent_id": fiche.id, "type": "invoice", "name": f["contact"]["nom"], "email": f["contact"]["email"], "function": "Comptabilité fournisseurs"})
    fournisseurs[f["siret"]] = fiche
    compte_rendu("fournisseur", "créé " if cree else "existant", fiche.name)

# ───────── Produits achetés ─────────
produits = {}
for p in DONNEES["produits"]:
    produit = env["product.product"].with_context(active_test=False).search([("default_code", "=", p["code"])], limit=1)
    if not produit:
        produit = env["product.product"].create({
            "name": p["nom"], "default_code": p["code"], "type": p["type"], "purchase_ok": True, "sale_ok": False,
            "standard_price": p["prix"], "supplier_taxes_id": [(6, 0, [] if p["sans_tva"] else taxes[p["type"]].ids)],
        })
    produits[p["code"]] = produit
compte_rendu("produits", len(produits))

# ───────── Bons de commande ─────────
for bc in DONNEES["bons_de_commande"]:
    origine = f"DEMO {bc['facture']}"
    existante = env["purchase.order"].search([("origin", "=", origine)], limit=1)
    if existante:
        # Remet la TVA attendue si elle a changé (correction d'une version précédente du remplissage).
        for ligne, attendue in zip(existante.order_line.sorted("id"), bc["lignes"]):
            taxes_attendues = env["account.tax"] if attendue["sans_tva"] else taxes[attendue["type"]]
            if ligne.tax_ids != taxes_attendues:
                ligne.tax_ids = [(6, 0, taxes_attendues.ids)]
                ligne.product_id.supplier_taxes_id = [(6, 0, taxes_attendues.ids)]
        compte_rendu("bon de commande existant pour", bc["facture"], f"{existante.amount_total:.2f} TTC")
        continue
    commande = env["purchase.order"].create({
        "partner_id": fournisseurs[bc["siret"]].id,
        "origin": origine,
        "date_order": bc["date"],
        "order_line": [
            (0, 0, {
                "product_id": produits[ligne["code"]].id, "name": ligne["designation"],
                "product_qty": float(ligne["quantite"]), "price_unit": float(ligne["prix"]),
                "tax_ids": [(6, 0, [] if ligne["sans_tva"] else taxes[ligne["type"]].ids)], "date_planned": bc["date"],
            })
            for ligne in bc["lignes"]
        ],
    })
    commande.button_confirm()
    compte_rendu("bon de commande", commande.name, "pour", bc["facture"], f"{commande.amount_untaxed:.2f} HT", bc.get("note", ""))

# ───────── Clients et opportunités (côté CRM) ─────────
for c in DONNEES["clients"]:
    fiche, cree = partenaire({
        "name": c["nom"], "is_company": True, "customer_rank": 1, "street": c["rue"], "zip": c["code_postal"],
        "city": c["ville"], "country_id": pays_fr.id, "l10n_fr_siret": c["siret"], "email": c["email"],
    })
    if not fiche.child_ids:
        env["res.partner"].create({"parent_id": fiche.id, "name": c["contact"], "email": c["email"], "function": c["fonction"]})
    if not env["crm.lead"].search([("name", "=", c["opportunite"]["nom"])], limit=1):
        env["crm.lead"].create({
            "name": c["opportunite"]["nom"], "type": "opportunity", "partner_id": fiche.id,
            "expected_revenue": c["opportunite"]["montant"], "probability": c["opportunite"]["probabilite"],
        })
    compte_rendu("client", "créé " if cree else "existant", fiche.name)

# ───────── Utilisateur technique de DocuFlow ─────────
# DocuFlow ne se connecte jamais avec le compte administrateur : il a son propre utilisateur,
# limité à la facturation, aux achats et aux contacts, et sa propre clé d'API.
Utilisateurs = env["res.users"].with_context(active_test=False, no_reset_password=True)
docuflow = Utilisateurs.search([("login", "=", "docuflow")], limit=1)
if not docuflow:
    docuflow = Utilisateurs.create({
        "name": "DocuFlow (intégration)", "login": "docuflow", "email": False,
        "group_ids": [(6, 0, [env.ref(x).id for x in ("base.group_user", "account.group_account_invoice", "purchase.group_purchase_user", "base.group_partner_manager")])],
    })
    compte_rendu("utilisateur technique créé : docuflow")
if DONNEES["nouvelle_cle"]:
    Cles = env["res.users.apikeys"].with_user(docuflow).sudo()
    Cles.search([("user_id", "=", docuflow.id), ("name", "=", "DocuFlow")]).unlink()
    # Créée au nom de docuflow, en mode administrateur (sudo) : un utilisateur ordinaire est limité
    # par Odoo à une durée courte, ce qui obligerait à renouveler la clé à la main.
    # Portée « rpc » : c'est celle qu'exige l'API JSON-2 d'Odoo 20 (une clé sans portée est refusée).
    cle = env["res.users.apikeys"].with_user(docuflow).sudo()._generate("rpc", "DocuFlow", datetime.now() + timedelta(days=365))
    print("CLE_API:" + cle)
    compte_rendu("clé d'API créée pour docuflow (valable un an)")

env.cr.commit()
compte_rendu("terminé")
