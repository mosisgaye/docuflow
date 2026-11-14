import json
from datetime import date
from decimal import Decimal

import httpx
import pytest

from moteur.extraction_llm import ErreurExtraction, extraire, valider

FACTURE_JSON = {
    "numero_facture": "F26-1193",
    "date_facture": "2026-11-10",
    "date_echeance": "2026-12-10",
    "fournisseur_nom": "Garage Central Bertin",
    "fournisseur_siret": "52987431000027",
    "fournisseur_tva": "FR73529874310",
    "client_nom": "Boulangerie Petit Jean",
    "lignes": [
        {"designation": "Main-d'œuvre (heures)", "quantite": 2.5, "prix_unitaire_ht": 62.0, "montant_ht": 155.0}
    ],
    "total_ht": 398.4,
    "taux_tva": 20,
    "total_tva": 79.68,
    "total_ttc": 478.08,
}


def corps_gemini(contenu: dict | str) -> dict:
    texte = contenu if isinstance(contenu, str) else json.dumps(contenu)
    return {"candidates": [{"content": {"parts": [{"text": texte}]}}]}


def corps_openai(contenu: dict | str) -> dict:
    texte = contenu if isinstance(contenu, str) else json.dumps(contenu)
    return {"choices": [{"message": {"content": texte}}]}


def client_qui_repond(reponse: httpx.Response, recues: list | None = None) -> httpx.Client:
    def repondre(requete: httpx.Request) -> httpx.Response:
        if recues is not None:
            recues.append(requete)
        return reponse

    return httpx.Client(transport=httpx.MockTransport(repondre))


@pytest.fixture
def configuration(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "cle-gemini")
    monkeypatch.setenv("OPENAI_API_KEY", "cle-openai")
    monkeypatch.setenv("LLM_MODELE", "modele-de-test")
    return monkeypatch


def test_une_reponse_valide_devient_une_facture():
    facture = valider(json.dumps(FACTURE_JSON))

    assert facture.numero_facture == "F26-1193"
    assert facture.date_facture == date(2026, 11, 10)
    assert facture.lignes[0].quantite == Decimal("2.5")


def test_les_montants_restent_exacts():
    facture = valider(json.dumps(FACTURE_JSON))

    assert facture.total_ht + facture.total_tva == facture.total_ttc
    assert facture.total_ttc == Decimal("478.08")


def test_les_montants_sont_toujours_a_deux_decimales():
    facture = valider(json.dumps({**FACTURE_JSON, "total_ht": 1600, "total_tva": 320.0, "total_ttc": 1920}))

    assert facture.model_dump(mode="json")["total_ttc"] == "1920.00"
    assert facture.model_dump(mode="json")["total_tva"] == "320.00"
    assert facture.model_dump(mode="json")["lignes"][0]["montant_ht"] == "155.00"


def test_une_information_absente_vaut_none():
    facture = valider(json.dumps({**FACTURE_JSON, "fournisseur_tva": None}))

    assert facture.fournisseur_tva is None


@pytest.mark.parametrize(
    "texte_json",
    [
        "ceci n'est pas du JSON",
        json.dumps({**FACTURE_JSON, "date_facture": "10/11/2026"}),
        json.dumps({**FACTURE_JSON, "champ_invente": "x"}),
        json.dumps({k: v for k, v in FACTURE_JSON.items() if k != "total_ttc"}),
    ],
)
def test_une_reponse_inexploitable_est_refusee(texte_json):
    with pytest.raises(ErreurExtraction):
        valider(texte_json)


def test_extraire_avec_gemini(configuration):
    configuration.setenv("LLM_FOURNISSEUR", "gemini")
    recues = []

    resultat = extraire("Facture n° F26-1193", client=client_qui_repond(httpx.Response(200, json=corps_gemini(FACTURE_JSON)), recues))

    assert resultat.facture.numero_facture == "F26-1193"
    assert (resultat.fournisseur, resultat.modele) == ("gemini", "modele-de-test")
    assert recues[0].headers["x-goog-api-key"] == "cle-gemini"
    assert "modele-de-test:generateContent" in str(recues[0].url)
    assert "Facture n° F26-1193" in json.loads(recues[0].content)["contents"][0]["parts"][0]["text"]


def test_extraire_avec_openai(configuration):
    configuration.setenv("LLM_FOURNISSEUR", "openai")
    recues = []

    resultat = extraire("Facture n° F26-1193", client=client_qui_repond(httpx.Response(200, json=corps_openai(FACTURE_JSON)), recues))

    envoye = json.loads(recues[0].content)
    assert resultat.facture.total_ttc == Decimal("478.08")
    assert (resultat.fournisseur, resultat.modele) == ("openai", "modele-de-test")
    assert recues[0].headers["authorization"] == "Bearer cle-openai"
    assert envoye["model"] == "modele-de-test"
    assert envoye["response_format"]["json_schema"]["strict"] is True
    assert "Facture n° F26-1193" in envoye["messages"][0]["content"]


def test_les_deux_fournisseurs_demandent_les_memes_champs():
    from moteur.extraction_llm import Gemini, OpenAI
    from moteur.modeles import Facture

    assert set(Gemini.schema()["properties"]) == set(OpenAI.schema()["properties"]) == set(Facture.model_fields)


def test_un_fournisseur_inconnu_est_refuse(configuration):
    configuration.setenv("LLM_FOURNISSEUR", "inconnu")

    with pytest.raises(ErreurExtraction, match="inconnu"):
        extraire("texte", client=client_qui_repond(httpx.Response(200)))


@pytest.mark.parametrize("statut", [429, 500, 503])
def test_une_erreur_du_llm_est_signalee(configuration, statut):
    configuration.setenv("LLM_FOURNISSEUR", "openai")

    with pytest.raises(ErreurExtraction, match=str(statut)):
        extraire("texte", client=client_qui_repond(httpx.Response(statut)), attendre=lambda secondes: None)


@pytest.mark.parametrize("corps", [{}, {"choices": []}, {"choices": [{"message": {}}]}])
def test_une_reponse_sans_contenu_est_refusee(configuration, corps):
    configuration.setenv("LLM_FOURNISSEUR", "openai")

    with pytest.raises(ErreurExtraction):
        extraire("texte", client=client_qui_repond(httpx.Response(200, json=corps)))


# ───────── Nouveaux essais ─────────


class ServiceSimule:
    """Répond dans l'ordre les réponses prévues ; une exception simule une coupure réseau."""

    def __init__(self, *reponses):
        self.reponses = list(reponses)
        self.appels = 0

    def client(self) -> httpx.Client:
        def repondre(requete: httpx.Request) -> httpx.Response:
            self.appels += 1
            reponse = self.reponses.pop(0)
            if isinstance(reponse, Exception):
                raise reponse
            return reponse

        return httpx.Client(transport=httpx.MockTransport(repondre))


def bonne_reponse() -> httpx.Response:
    return httpx.Response(200, json=corps_openai(FACTURE_JSON))


@pytest.fixture
def openai(configuration):
    configuration.setenv("LLM_FOURNISSEUR", "openai")


@pytest.fixture
def attentes():
    """Remplace l'attente réelle : on note les durées au lieu de dormir."""
    return []


def test_une_panne_passagere_est_retentee_jusqu_au_succes(openai, attentes):
    service = ServiceSimule(httpx.Response(503), httpx.Response(503), bonne_reponse())

    resultat = extraire("texte", client=service.client(), attendre=attentes.append)

    assert resultat.facture.numero_facture == "F26-1193"
    assert resultat.tentatives == 3
    assert service.appels == 3
    assert len(attentes) == 2
    assert 0.8 <= attentes[0] <= 1.2 and 1.6 <= attentes[1] <= 2.4  # attente croissante


def test_une_coupure_reseau_est_retentee(openai, attentes):
    service = ServiceSimule(httpx.ConnectError("coupure"), bonne_reponse())

    resultat = extraire("texte", client=service.client(), attendre=attentes.append)

    assert resultat.tentatives == 2


def test_le_delai_demande_par_le_service_est_respecte(openai, attentes):
    service = ServiceSimule(httpx.Response(429, headers={"Retry-After": "7"}), bonne_reponse())

    extraire("texte", client=service.client(), attendre=attentes.append)

    assert attentes == [7.0]


def test_un_delai_trop_long_n_est_pas_attendu_sur_place(openai, attentes):
    service = ServiceSimule(httpx.Response(429, headers={"Retry-After": "3600"}), bonne_reponse())

    with pytest.raises(ErreurExtraction) as erreur:
        extraire("texte", client=service.client(), attendre=attentes.append)

    assert service.appels == 1
    assert attentes == []
    assert erreur.value.passagere is True
    assert erreur.value.attendre_avant == 3600.0


def test_apres_trois_echecs_l_erreur_est_passagere(openai, attentes):
    service = ServiceSimule(httpx.Response(503), httpx.Response(502), httpx.Response(503))

    with pytest.raises(ErreurExtraction, match="après 3 appels") as erreur:
        extraire("texte", client=service.client(), attendre=attentes.append)

    assert erreur.value.passagere is True
    assert service.appels == 3


@pytest.mark.parametrize("statut", [400, 401, 403, 404, 422])
def test_une_erreur_definitive_n_est_jamais_retentee(openai, attentes, statut):
    service = ServiceSimule(httpx.Response(statut), bonne_reponse())

    with pytest.raises(ErreurExtraction) as erreur:
        extraire("texte", client=service.client(), attendre=attentes.append)

    assert service.appels == 1
    assert attentes == []
    assert erreur.value.passagere is False


def test_une_reponse_hors_format_n_est_pas_retentee(openai, attentes):
    service = ServiceSimule(httpx.Response(200, json={"choices": [{"message": {"content": "pas du JSON"}}]}), bonne_reponse())

    with pytest.raises(ErreurExtraction) as erreur:
        extraire("texte", client=service.client(), attendre=attentes.append)

    assert service.appels == 1
    assert erreur.value.passagere is False


def test_un_delai_donne_sous_forme_de_date_est_compris():
    from datetime import datetime, timezone

    from moteur.nouvel_essai import delai_demande

    maintenant = datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)
    reponse = httpx.Response(503, headers={"Retry-After": "Sat, 14 Nov 2026 10:00:30 GMT"})

    assert delai_demande(reponse, maintenant) == 30.0
    assert delai_demande(httpx.Response(503, headers={"Retry-After": "n'importe quoi"})) is None
    assert delai_demande(httpx.Response(503)) is None
