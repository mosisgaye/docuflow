"""Vérification d'un fournisseur auprès des services publics français.

Deux API ouvertes, sans clé :
- Recherche d'entreprises (État) : l'entreprise existe-t-elle, est-elle active ?
- BODACC (annonces légales)     : fait-elle l'objet d'une procédure collective ?

Trois règles :
1. on ne pose pas deux fois la même question (mémoire de 24 heures) ;
2. une panne chez eux ne nous arrête pas : on répond « indisponible » ;
3. le résultat informe la personne qui décide, il ne bloque rien tout seul.
"""

import time
from dataclasses import asdict, dataclass, field

import httpx

URL_ENTREPRISES = "https://recherche-entreprises.api.gouv.fr/search"
URL_BODACC = "https://bodacc-datadila.opendatasoft.com/api/explore/v2.1/catalog/datasets/annonces-commerciales/records"
DUREE_MEMOIRE_S = 24 * 3600
DELAI_S = 6.0

_memoire: dict[str, tuple[float, "VerificationFournisseur"]] = {}


@dataclass(frozen=True)
class VerificationFournisseur:
    siret: str
    statut: str  # "trouve", "inconnu" ou "indisponible"
    message: str
    nom: str | None = None
    actif: bool | None = None
    commune: str | None = None
    date_creation: str | None = None
    procedure_collective: bool | None = None
    annonces: list[dict] = field(default_factory=list)

    def en_dict(self) -> dict:
        return asdict(self)


def vider_memoire() -> None:
    _memoire.clear()


def _annonces_legales(client: httpx.Client, siren: str) -> tuple[bool | None, list[dict]]:
    """Renvoie (procédure collective ?, dernières annonces). None si le BODACC ne répond pas."""
    try:
        reponse = client.get(
            URL_BODACC,
            params={"where": f'registre like "{siren}"', "order_by": "dateparution desc", "limit": 20},
            timeout=DELAI_S,
        )
        reponse.raise_for_status()
        annonces = [
            {"date": annonce.get("dateparution"), "famille": annonce.get("familleavis_lib") or ""}
            for annonce in reponse.json().get("results", [])
        ]
    except (httpx.HTTPError, ValueError):
        return None, []
    procedure = any("collective" in annonce["famille"].lower() for annonce in annonces)
    return procedure, annonces[:5]


def verifier_fournisseur(siret: str, client: httpx.Client | None = None) -> VerificationFournisseur:
    siret = "".join(caractere for caractere in siret if caractere.isdigit())
    if len(siret) != 14:
        return VerificationFournisseur(siret, "inconnu", "Ce numéro n'a pas 14 chiffres : ce n'est pas un SIRET.")
    en_memoire = _memoire.get(siret)
    if en_memoire and time.monotonic() - en_memoire[0] < DUREE_MEMOIRE_S:
        return en_memoire[1]

    client = client or httpx.Client()
    try:
        reponse = client.get(URL_ENTREPRISES, params={"q": siret, "per_page": 1}, timeout=DELAI_S)
        reponse.raise_for_status()
        resultats = reponse.json().get("results", [])
    except (httpx.HTTPError, ValueError):
        # Règle 2 : pas de mise en mémoire d'une panne, on réessaiera la prochaine fois.
        return VerificationFournisseur(siret, "indisponible", "Le registre des entreprises ne répond pas. Vérification à refaire plus tard.")

    if not resultats:
        verification = VerificationFournisseur(siret, "inconnu", "Aucune entreprise ne porte ce SIRET dans le registre de l'État.")
    else:
        entreprise = resultats[0]
        etablissements = [*(entreprise.get("matching_etablissements") or []), entreprise.get("siege") or {}]
        etablissement = next((e for e in etablissements if e.get("siret") == siret), etablissements[0])
        actif = entreprise.get("etat_administratif") == "A" and etablissement.get("etat_administratif", "A") == "A"
        procedure, annonces = _annonces_legales(client, siret[:9])
        nom = entreprise.get("nom_complet") or entreprise.get("nom_raison_sociale")
        if not actif:
            message = f"{nom} est enregistrée mais n'est plus en activité."
        elif procedure:
            message = f"{nom} est active, mais une procédure collective figure dans ses annonces légales."
        elif procedure is None:
            message = f"{nom} est active. Les annonces légales n'ont pas pu être consultées."
        else:
            message = f"{nom} est active et aucune procédure collective n'apparaît dans ses annonces légales récentes."
        verification = VerificationFournisseur(
            siret=siret,
            statut="trouve",
            message=message,
            nom=nom,
            actif=actif,
            commune=etablissement.get("libelle_commune"),
            date_creation=entreprise.get("date_creation"),
            procedure_collective=procedure,
            annonces=annonces,
        )
    _memoire[siret] = (time.monotonic(), verification)
    return verification
