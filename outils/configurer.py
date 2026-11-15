"""Configure les services externes de DocuFlow en posant les questions une par une.

    uv run python -m outils.configurer

À lancer dans SON terminal : les secrets se tapent sans s'afficher et ne passent jamais par
une conversation. Les réglages sont écrits dans le fichier de configuration du projet (.env) :
une ligne existante est remplacée, les autres lignes ne bougent pas. Une réponse vide laisse
le réglage tel qu'il est.
"""

import getpass
import pathlib
import re
import secrets
import sys

from cryptography.fernet import Fernet

FICHIER = pathlib.Path(__file__).resolve().parent.parent / ".env"
ADRESSE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def lire() -> dict[str, str]:
    valeurs = {}
    for ligne in FICHIER.read_text(encoding="utf-8").splitlines() if FICHIER.exists() else []:
        if "=" in ligne and not ligne.lstrip().startswith("#"):
            cle, valeur = ligne.split("=", 1)
            valeurs[cle.strip()] = valeur.strip()
    return valeurs


def ecrire(reglages: dict[str, str]) -> None:
    """Remplace chaque réglage là où il est (en supprimant ses doublons), ou l'ajoute à la fin."""
    lignes = FICHIER.read_text(encoding="utf-8").splitlines() if FICHIER.exists() else []
    restants, sortie = dict(reglages), []
    for ligne in lignes:
        cle = ligne.split("=", 1)[0].strip() if "=" in ligne and not ligne.lstrip().startswith("#") else None
        if cle in reglages:
            if cle in restants:
                sortie.append(f"{cle}={restants.pop(cle)}")
            continue  # doublon plus bas : supprimé
        sortie.append(ligne)
    sortie += [f"{cle}={valeur}" for cle, valeur in restants.items()]
    FICHIER.write_text("\n".join(sortie) + "\n", encoding="utf-8")
    FICHIER.chmod(0o600)


def demander(question: str, secret: bool = False, adresse: bool = False) -> str:
    while True:
        reponse = (getpass.getpass(f"{question} (cachée) : ") if secret else input(f"{question} : ")).strip()
        if not reponse or not adresse or ADRESSE.match(reponse):
            return reponse
        print("  Ce n'est pas une adresse mail valable, recommencez (ou Entrée pour passer).")


def etat(valeurs: dict[str, str], nom: str) -> str:
    return "déjà réglé" if valeurs.get(nom) else "à régler"


def resend(valeurs: dict[str, str]) -> dict[str, str]:
    print("\n── Mails d'approbation (Resend) ──")
    print(f"Clé API Resend : {etat(valeurs, 'RESEND_API_KEY')}. Elle se trouve sur resend.com, menu API Keys.")
    nouveaux = {}
    if cle := demander("Clé API Resend (Entrée pour garder l'actuelle)", secret=True):
        nouveaux["RESEND_API_KEY"] = cle
    nouveaux["MAIL_EXPEDITEUR"] = valeurs.get("MAIL_EXPEDITEUR") or "DocuFlow <docuflow@moussagaye.com>"
    print("Pour voir la séparation des tâches, chaque niveau doit avoir une adresse différente.")
    print("Avec Gmail, une seule boîte suffit : prenom.nom+comptable@gmail.com et prenom.nom+daf@gmail.com arrivent au même endroit.")
    for niveau, libelle in (("COMPTABLE", "comptable"), ("DIRECTEUR_FINANCIER", "directeur financier"), ("GERANT", "gérant")):
        nom = f"APPROBATION_DESTINATAIRE_{niveau}"
        actuelle = valeurs.get(nom, "")
        if "ton.adresse" in actuelle:
            actuelle = ""  # l'exemple recopié tel quel ne compte pas
        if adresse := demander(f"Adresse du {libelle} ({actuelle or 'aucune'} ; Entrée pour garder)", adresse=True):
            nouveaux[nom] = adresse
        elif "ton.adresse" in valeurs.get(nom, ""):
            nouveaux[nom] = ""
    if not valeurs.get("APPROBATION_SECRET"):
        nouveaux["APPROBATION_SECRET"] = secrets.token_urlsafe(32)  # signe les liens des mails
    return nouveaux


def hubspot(valeurs: dict[str, str]) -> dict[str, str]:
    print("\n── HubSpot ──")
    print("Les deux valeurs viennent de HubSpot : https://app.hubspot.com/l/mcp-auth-apps/ , votre connecteur « DocuFlow ».")
    print("Adresse de retour à y déclarer : http://localhost:5180/api/oauth/retour")
    nouveaux = {}
    if identifiant := demander(f"Client ID ({etat(valeurs, 'HUBSPOT_CLIENT_ID')} ; Entrée pour passer)"):
        nouveaux["HUBSPOT_CLIENT_ID"] = identifiant
    if secret := demander(f"Client secret ({etat(valeurs, 'HUBSPOT_CLIENT_SECRET')} ; Entrée pour passer)", secret=True):
        nouveaux["HUBSPOT_CLIENT_SECRET"] = secret
    if not valeurs.get("CONNECTEURS_CLE_CHIFFREMENT"):
        nouveaux["CONNECTEURS_CLE_CHIFFREMENT"] = Fernet.generate_key().decode()  # chiffre les jetons en base
    return nouveaux


def main() -> None:
    if not sys.stdin.isatty():
        sys.exit("Lancez cet outil dans votre propre terminal : il pose des questions et cache les secrets.")
    valeurs = lire()
    print("Configuration de DocuFlow. Rien de ce que vous tapez ne s'affiche à l'écran pour les secrets.")
    choix = input("Que voulez-vous régler ? 1 = mails (Resend), 2 = HubSpot, 3 = les deux : ").strip()
    nouveaux = {}
    if choix in ("1", "3"):
        nouveaux |= resend(valeurs)
    if choix in ("2", "3"):
        nouveaux |= hubspot(valeurs)
    if not nouveaux:
        print("Rien à changer.")
        return
    ecrire(nouveaux)
    reglages = lire()
    print("\nC'est enregistré. État actuel (sans les valeurs) :")
    for nom in ("RESEND_API_KEY", "APPROBATION_DESTINATAIRE_COMPTABLE", "APPROBATION_DESTINATAIRE_DIRECTEUR_FINANCIER", "APPROBATION_SECRET", "HUBSPOT_CLIENT_ID", "HUBSPOT_CLIENT_SECRET", "CONNECTEURS_CLE_CHIFFREMENT"):
        print(f"  {nom:46} {'réglé' if reglages.get(nom) else 'vide'}")
    print("Dites à Claude que c'est fait : il vérifiera de son côté sans voir les valeurs.")


if __name__ == "__main__":
    main()
