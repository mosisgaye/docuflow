"""Ajoute au HubSpot connecté les fournisseurs de l'entreprise de démonstration et leurs contacts.

    uv run python -m outils.hubspot_remplir

Les mêmes fournisseurs que dans Odoo (outils/odoo_remplir.py) : fiche entreprise et contact
comptable, reliés entre eux. Relançable : une entreprise ou un contact déjà présent n'est pas recréé.

Cet outil ÉCRIT dans HubSpot, à la demande explicite de la personne qui a connecté le compte.
Il passe par l'outil d'écriture officiel du serveur MCP de HubSpot (manage_crm_objects), appelé
par ce script et jamais par l'assistant : l'assistant n'a accès qu'aux outils de lecture.

Base légale RGPD des contacts (exigée par les comptes HubSpot européens) : « exécution d'un
contrat », puisque ce sont les contacts comptables de fournisseurs avec qui l'on a un contrat.

Volontairement : pas de site web sur les fiches (HubSpot « enrichirait » nos sociétés fictives
avec les données de vraies entreprises), et aucun contact inventé pour MD Plomberie, fournisseur réel.
"""

import json
import logging

from sqlalchemy.orm import Session

from moteur.base import creer_moteur
from moteur.connecteurs import Passerelle
from outils.odoo_remplir import donnees

BASE_LEGALE = "Performance of a contract"  # valeur HubSpot de « exécution d'un contrat »


def appeler(connexion, outil: str, arguments: dict) -> dict:
    resultat = connexion.appeler(outil, arguments)
    texte = "\n".join(getattr(morceau, "text", "") for morceau in resultat.content)
    if resultat.is_error:
        raise SystemExit(f"HubSpot a refusé ({outil}) : {texte[:400]}")
    try:
        return json.loads(texte)
    except ValueError:
        return {"texte": texte}


def creer(connexion, objets: list[dict]) -> None:
    """Crée des objets et vérifie CHAQUE résultat : HubSpot peut répondre sans erreur globale
    alors qu'un objet a échoué (règle de validation du compte, par exemple)."""
    reponse = appeler(connexion, "manage_crm_objects", {
        "confirmationStatus": "CONFIRMED",  # demandé explicitement par la personne qui a connecté le compte
        "createRequest": {"objects": objets},
    })
    resultats = (reponse.get("createResults") or {}).get("results", [])
    echecs = [r["error"] for r in resultats if r.get("error")]
    if echecs or not resultats:
        raise SystemExit("HubSpot n'a pas tout créé : " + ("; ".join(echecs) or json.dumps(reponse, ensure_ascii=False)[:300]))


def chercher(connexion, type_objet: str, texte: str, proprietes: list[str]) -> list[dict]:
    reponse = appeler(connexion, "search_crm_objects", {"objectType": type_objet, "query": texte, "properties": proprietes, "limit": 10})
    return reponse.get("results") or reponse.get("objects") or []


def identifiant(objet: dict) -> int:
    return int(objet.get("id") or objet.get("objectId"))


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    moteur = creer_moteur()
    passerelle = Passerelle(lambda: Session(moteur))
    try:
        connexion = passerelle._connexion("hubspot")
        fournisseurs = donnees(False)["fournisseurs"]

        # 1. Les entreprises qui manquent.
        manquantes = [f for f in fournisseurs if not any(o.get("properties", {}).get("name") == f["nom"] for o in chercher(connexion, "COMPANY", f["nom"], ["name"]))]
        if manquantes:
            creer(connexion, [
                    {
                        "objectType": "COMPANY",
                        "properties": {
                            "name": f["nom"], "address": f["rue"], "zip": f["code_postal"], "city": f["ville"], "country": "France",
                            "description": f"Fournisseur de Transports Lemaire SAS. SIRET {f['siret']}." + (f" TVA {f['tva']}." if f["tva"] else " Franchise en base de TVA."),
                        },
                    }
                    for f in manquantes
            ])
        for f in fournisseurs:
            print(f"entreprise {'créée ' if f in manquantes else 'existante'} : {f['nom']}")

        # 2. Les contacts comptables, reliés à leur entreprise.
        for f in fournisseurs:
            if not f["contact"]:
                continue
            entreprise = next(o for o in chercher(connexion, "COMPANY", f["nom"], ["name"]) if o.get("properties", {}).get("name") == f["nom"])
            if any(o.get("properties", {}).get("email") == f["contact"]["email"] for o in chercher(connexion, "CONTACT", f["contact"]["email"], ["email"])):
                print(f"contact existant : {f['contact']['nom']}")
                continue
            prenom, _, nom = f["contact"]["nom"].partition(" ")
            creer(connexion, [{
                "objectType": "CONTACT",
                "properties": {
                    "firstname": prenom, "lastname": nom, "email": f["contact"]["email"], "jobtitle": "Comptabilité fournisseurs",
                    "company": f["nom"], "hs_legal_basis": BASE_LEGALE,
                },
                "associations": [{"targetObjectId": identifiant(entreprise), "targetObjectType": "COMPANY"}],
            }])
            print(f"contact créé : {f['contact']['nom']} ({f['nom']})")
    finally:
        passerelle.fermer()


if __name__ == "__main__":
    main()
