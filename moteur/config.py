"""Lecture de la configuration : variables d'environnement, puis fichier .env."""

import os
import pathlib

RACINE = pathlib.Path(__file__).resolve().parent.parent


def _lire_fichier_env() -> dict[str, str]:
    chemin = RACINE / ".env"
    if not chemin.exists():
        return {}
    valeurs = {}
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        if "=" in ligne and not ligne.lstrip().startswith("#"):
            cle, valeur = ligne.split("=", 1)
            valeurs[cle.strip()] = valeur.strip().strip("'\"")
    return valeurs


def lire(nom: str, defaut: str | None = None) -> str:
    """Renvoie une valeur de configuration, ou lève une erreur claire si elle manque."""
    # Une variable d'environnement présente, même vide, l'emporte sur le fichier .env :
    # c'est ce qui permet aux tests de couper un réglage (envoi de mails, connexions).
    valeur = (os.environ[nom] if nom in os.environ else _lire_fichier_env().get(nom)) or defaut
    if valeur is None:
        raise RuntimeError(f"Configuration manquante : {nom} (à définir dans .env)")
    return valeur


def dossier_fichiers() -> pathlib.Path:
    """Où sont gardés les PDF reçus : l'API les y écrit, le travailleur les y relit."""
    return pathlib.Path(lire("FICHIERS_DOSSIER", str(RACINE / "donnees" / "fichiers")))
