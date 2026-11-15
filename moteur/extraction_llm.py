"""Extraction des données d'une facture par un LLM, à partir de son texte.

Le LLM lit et propose. Il ne décide de rien : sa réponse est validée
par le modèle Facture, puis par les contrôles métier.

Le fournisseur de LLM est interchangeable : chaque fournisseur est une petite
classe qui sait construire sa requête et lire sa réponse. Le reste du moteur
ne connaît que la fonction extraire().

Une panne passagère (réseau, 429, 503…) est retentée sur place, au plus
3 appels en tout, avec une attente croissante. Si elle persiste, l'erreur
est marquée « passagère » : la file de tâches reprogrammera la lecture plus tard.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from moteur import config
from moteur.consignes import VersionConsigne
from moteur.nouvel_essai import ATTENTE_MAX_SUR_PLACE_S, TENTATIVES, delai_avant_essai, delai_demande, est_passager
from moteur.modeles import Facture

CONSIGNE = """Tu extrais les données d'une facture française à partir de son texte.

Règles :
- N'utilise que le texte fourni. Si une information est absente, mets null.
- Les dates du document sont au format français JJ/MM/AAAA : 03/11/2026 est le 3 novembre 2026.
  Renvoie-les au format AAAA-MM-JJ.
- Les montants sont des nombres avec un point décimal, sans symbole de monnaie ni espace.
- fournisseur_siret : 14 chiffres, sans espace. fournisseur_tva : sans espace.
- fournisseur_iban : l'IBAN du compte où payer le fournisseur, en majuscules et sans espace. null s'il n'est pas écrit.
- taux_tva : en pourcentage (20 pour 20 %).
- Si la facture indique que la TVA n'est pas applicable (franchise en base, article 293 B du CGI), mets taux_tva à 0 et total_tva à 0, et total_ttc égal au total HT.
- Le fournisseur est l'entreprise qui émet la facture, le client celle qui la reçoit.

Texte de la facture :
---------------
{texte}
---------------"""

# Les champs demandés au LLM, décrits une seule fois pour tous les fournisseurs.
CHAMPS_TEXTE = [
    "numero_facture",
    "date_facture",
    "date_echeance",
    "fournisseur_nom",
    "fournisseur_siret",
    "fournisseur_tva",
    "fournisseur_iban",
    "client_nom",
]
CHAMPS_NOMBRE = ["total_ht", "taux_tva", "total_tva", "total_ttc"]
CHAMPS_LIGNE_NOMBRE = ["quantite", "prix_unitaire_ht", "montant_ht"]


class ErreurExtraction(Exception):
    """Le LLM n'a pas répondu, ou sa réponse n'est pas une facture valide.

    passagere      : vrai si retenter plus tard peut réussir (panne, quota momentané) ;
    attendre_avant : délai minimal demandé par le service avant de retenter, en secondes.
    """

    def __init__(self, message: str, passagere: bool = False, attendre_avant: float | None = None):
        super().__init__(message)
        self.passagere = passagere
        self.attendre_avant = attendre_avant


@dataclass(frozen=True)
class ResultatExtraction:
    facture: Facture
    duree_s: float
    fournisseur: str
    modele: str
    consigne: VersionConsigne | None = None  # la consigne exacte qui a produit ces données
    tentatives: int = 1  # nombre d'appels qu'il a fallu


def valider(texte_json: str) -> Facture:
    """Transforme le JSON renvoyé par le LLM en Facture validée."""
    try:
        # parse_float=str : les montants passent en Decimal sans erreur d'arrondi.
        return Facture.model_validate(json.loads(texte_json, parse_float=str))
    except (TypeError, ValueError) as erreur:
        raise ErreurExtraction(f"Réponse du LLM inexploitable : {erreur}") from erreur


class Gemini:
    nom = "gemini"
    modele_par_defaut = "gemini-3.5-flash-lite"
    variable_cle = "GEMINI_API_KEY"

    @staticmethod
    def schema() -> dict:
        ligne = {
            "type": "OBJECT",
            "properties": {
                "designation": {"type": "STRING"},
                **{champ: {"type": "NUMBER"} for champ in CHAMPS_LIGNE_NOMBRE},
            },
            "required": ["designation", *CHAMPS_LIGNE_NOMBRE],
        }
        return {
            "type": "OBJECT",
            "properties": {
                **{champ: {"type": "STRING", "nullable": True} for champ in CHAMPS_TEXTE},
                "lignes": {"type": "ARRAY", "items": ligne},
                **{champ: {"type": "NUMBER", "nullable": True} for champ in CHAMPS_NOMBRE},
            },
            "required": [*CHAMPS_TEXTE, "lignes", *CHAMPS_NOMBRE],
        }

    def requete(self, modele: str, cle: str, consigne: str) -> tuple[str, dict, dict]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modele}:generateContent"
        charge = {
            "contents": [{"parts": [{"text": consigne}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": self.schema()},
        }
        return url, {"x-goog-api-key": cle}, charge

    @staticmethod
    def texte_reponse(corps: dict) -> str:
        return corps["candidates"][0]["content"]["parts"][0]["text"]


class OpenAI:
    nom = "openai"
    modele_par_defaut = "gpt-5.4-mini"
    variable_cle = "OPENAI_API_KEY"

    @staticmethod
    def schema() -> dict:
        ligne = {
            "type": "object",
            "properties": {
                "designation": {"type": "string"},
                **{champ: {"type": "number"} for champ in CHAMPS_LIGNE_NOMBRE},
            },
            "required": ["designation", *CHAMPS_LIGNE_NOMBRE],
            "additionalProperties": False,
        }
        return {
            "type": "object",
            "properties": {
                **{champ: {"type": ["string", "null"]} for champ in CHAMPS_TEXTE},
                "lignes": {"type": "array", "items": ligne},
                **{champ: {"type": ["number", "null"]} for champ in CHAMPS_NOMBRE},
            },
            "required": [*CHAMPS_TEXTE, "lignes", *CHAMPS_NOMBRE],
            "additionalProperties": False,
        }

    def requete(self, modele: str, cle: str, consigne: str) -> tuple[str, dict, dict]:
        charge = {
            "model": modele,
            "messages": [{"role": "user", "content": consigne}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "facture", "strict": True, "schema": self.schema()},
            },
        }
        return "https://api.openai.com/v1/chat/completions", {"Authorization": f"Bearer {cle}"}, charge

    @staticmethod
    def texte_reponse(corps: dict) -> str:
        return corps["choices"][0]["message"]["content"]


FOURNISSEURS = {fournisseur.nom: fournisseur for fournisseur in (Gemini, OpenAI)}


def version_consigne(fournisseur) -> VersionConsigne:
    """La consigne d'extraction telle qu'envoyée à ce fournisseur : texte et format de réponse."""
    return VersionConsigne(usage="extraction", texte=CONSIGNE, schema=fournisseur.schema())


def _appeler(client: httpx.Client, url: str, charge: dict, entetes: dict, attendre: Callable[[float], None]) -> tuple[httpx.Response, int]:
    """Appelle le LLM et retente les pannes passagères. Renvoie (réponse 200, nombre d'appels)."""
    for numero in range(1, TENTATIVES + 1):
        try:
            reponse = client.post(url, json=charge, headers=entetes)
        except httpx.TransportError as erreur:  # réseau coupé, délai dépassé…
            probleme, demande = f"Le LLM est injoignable : {type(erreur).__name__}", None
        else:
            if reponse.status_code == 200:
                return reponse, numero
            if not est_passager(reponse.status_code):
                # Clé refusée, demande mal formée… : retenter échouerait pareil.
                raise ErreurExtraction(f"Le LLM a répondu {reponse.status_code}")
            probleme, demande = f"Le LLM a répondu {reponse.status_code}", delai_demande(reponse)

        if numero == TENTATIVES or (demande is not None and demande > ATTENTE_MAX_SUR_PLACE_S):
            # Rien ne sert d'attendre ici : la file de tâches reprogrammera la lecture.
            raise ErreurExtraction(f"{probleme} (après {numero} appel{'s' if numero > 1 else ''})", passagere=True, attendre_avant=demande)
        attendre(max(demande or 0.0, delai_avant_essai(numero + 1)))
    raise AssertionError("inatteignable")


def extraire(texte: str, client: httpx.Client | None = None, attendre: Callable[[float], None] = time.sleep) -> ResultatExtraction:
    """Envoie le texte de la facture au LLM configuré et renvoie la facture extraite."""
    nom = config.lire("LLM_FOURNISSEUR", "openai")
    if nom not in FOURNISSEURS:
        raise ErreurExtraction(f"Fournisseur de LLM inconnu : {nom}")
    fournisseur = FOURNISSEURS[nom]()
    modele = config.lire("LLM_MODELE", fournisseur.modele_par_defaut)
    url, entetes, charge = fournisseur.requete(modele, config.lire(fournisseur.variable_cle), CONSIGNE.format(texte=texte))

    client = client or httpx.Client(timeout=60)
    debut = time.monotonic()
    reponse, appels = _appeler(client, url, charge, entetes, attendre)
    duree = time.monotonic() - debut
    try:
        texte_json = fournisseur.texte_reponse(reponse.json())
    except (KeyError, IndexError, TypeError, ValueError) as erreur:
        raise ErreurExtraction(f"Réponse du LLM inexploitable : {erreur!r}") from erreur
    return ResultatExtraction(
        facture=valider(texte_json), duree_s=duree, fournisseur=nom, modele=modele, consigne=version_consigne(fournisseur), tentatives=appels
    )
