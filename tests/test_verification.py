import httpx
import pytest

from moteur.verification import verifier_fournisseur, vider_memoire

SIRET = "35600000000048"


@pytest.fixture(autouse=True)
def memoire_vide():
    vider_memoire()


def faux_services(entreprises: httpx.Response, bodacc: httpx.Response | None = None, appels: list | None = None) -> httpx.Client:
    def repondre(requete: httpx.Request) -> httpx.Response:
        if appels is not None:
            appels.append(requete.url.host)
        if "recherche-entreprises" in requete.url.host:
            return entreprises
        return bodacc or httpx.Response(200, json={"results": []})

    return httpx.Client(transport=httpx.MockTransport(repondre))


def entreprise(etat: str = "A") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "results": [
                {
                    "nom_complet": "LA POSTE",
                    "etat_administratif": etat,
                    "date_creation": "1991-01-01",
                    "siege": {"siret": SIRET, "etat_administratif": etat, "libelle_commune": "PARIS"},
                }
            ]
        },
    )


def annonces(*familles: str) -> httpx.Response:
    return httpx.Response(200, json={"results": [{"dateparution": "2026-11-02", "familleavis_lib": famille} for famille in familles]})


def test_une_entreprise_active_sans_procedure():
    resultat = verifier_fournisseur(SIRET, faux_services(entreprise(), annonces("Modifications diverses")))

    assert (resultat.statut, resultat.nom, resultat.actif, resultat.commune) == ("trouve", "LA POSTE", True, "PARIS")
    assert resultat.procedure_collective is False
    assert "aucune procédure collective" in resultat.message


def test_une_procedure_collective_est_signalee():
    resultat = verifier_fournisseur(SIRET, faux_services(entreprise(), annonces("Modifications diverses", "Procédures collectives")))

    assert resultat.procedure_collective is True
    assert "procédure collective" in resultat.message


def test_une_entreprise_fermee_est_signalee():
    resultat = verifier_fournisseur(SIRET, faux_services(entreprise("C")))

    assert resultat.actif is False
    assert "plus en activité" in resultat.message


def test_un_siret_absent_du_registre():
    resultat = verifier_fournisseur(SIRET, faux_services(httpx.Response(200, json={"results": []})))

    assert resultat.statut == "inconnu"


def test_un_numero_trop_court_n_interroge_personne():
    appels = []

    resultat = verifier_fournisseur("12345", faux_services(entreprise(), appels=appels))

    assert resultat.statut == "inconnu"
    assert appels == []


@pytest.mark.parametrize("panne", [httpx.Response(503), httpx.Response(200, text="pas du json")])
def test_une_panne_du_registre_ne_bloque_pas(panne):
    resultat = verifier_fournisseur(SIRET, faux_services(panne))

    assert resultat.statut == "indisponible"


def test_une_panne_du_bodacc_laisse_la_reponse_du_registre():
    resultat = verifier_fournisseur(SIRET, faux_services(entreprise(), httpx.Response(500)))

    assert resultat.statut == "trouve"
    assert resultat.procedure_collective is None
    assert "n'ont pas pu être consultées" in resultat.message


def test_la_meme_question_n_est_posee_qu_une_fois():
    appels = []
    client = faux_services(entreprise(), annonces(), appels)

    verifier_fournisseur(SIRET, client)
    verifier_fournisseur("356 000 000 00048", client)

    assert len(appels) == 2  # un appel au registre et un au BODACC, pas quatre


def test_une_panne_n_est_pas_gardee_en_memoire():
    verifier_fournisseur(SIRET, faux_services(httpx.Response(503)))

    resultat = verifier_fournisseur(SIRET, faux_services(entreprise(), annonces()))

    assert resultat.statut == "trouve"
