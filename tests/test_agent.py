import json
import pathlib
from datetime import date

import pytest

from moteur import agent
from moteur.agent import converser, executer_outil
from moteur.base import Etat
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture
from moteur.verification import VerificationFournisseur
from moteur.workflow import traiter

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))


def recevoir(session, nom: str):
    donnees = Facture.model_validate(ATTENDU[nom]["facture"])
    extracteur = lambda texte: ResultatExtraction(donnees, 0.1, "test", "faux")  # noqa: E731
    return traiter(session, (FACTURES / nom).read_bytes(), nom, extracteur, date(2026, 11, 14)).facture


class FauxLLM:
    """Joue un scénario : chaque tour renvoie soit des appels d'outils, soit du texte."""

    def __init__(self, *tours):
        self.tours = list(tours)
        self.recus = []

    def __call__(self, messages, outils):
        self.recus.append(list(messages))  # copie : la liste continue de grandir ensuite
        tour = self.tours.pop(0)
        if isinstance(tour, str):
            yield {"texte": tour}
        else:
            yield {"appels": [{"id": f"appel-{rang}", "nom": nom, "arguments": json.dumps(arguments)} for rang, (nom, arguments) in enumerate(tour)]}


def types(evenements: list[dict]) -> list[str]:
    return [evenement["type"] + (f":{evenement['etat']}" if evenement["type"] == "outil" else "") for evenement in evenements]


def test_l_agent_consulte_une_facture_puis_repond(session):
    recevoir(session, "facture-erreur-total.pdf")
    llm = FauxLLM([("consulter_facture", {"reference": "FA-2026-0431"})], "Le total TTC est faux de 100 euros.")

    evenements = list(converser(session, [{"role": "user", "content": "Pourquoi cette facture bloque ?"}], llm=llm))

    assert types(evenements) == ["outil:debut", "outil:fin", "facture", "texte", "fin"]
    assert evenements[0]["libelle"] == "Lecture de la facture FA-2026-0431"
    resultat_outil = json.loads(llm.recus[1][-1]["content"])
    assert resultat_outil["anomalies"][0]["code"] == "TOTAL_TTC_INCOHERENT"
    assert llm.recus[0][0]["role"] == "system"


def test_une_proposition_ne_change_pas_l_etat_de_la_facture(session):
    facture = recevoir(session, "facture-F26-1193.pdf")
    llm = FauxLLM(
        [("consulter_facture", {"reference": "F26-1193"})],
        [("proposer_decision", {"reference": "F26-1193", "decision": "valider", "motif": "Tout est conforme."})],
        "Je vous propose de valider.",
    )

    evenements = list(converser(session, [{"role": "user", "content": "On peut valider ?"}], llm=llm))

    proposition = next(evenement for evenement in evenements if evenement["type"] == "proposition")
    assert proposition == {"type": "proposition", "facture_id": str(facture.id), "numero": "F26-1193", "decision": "valider", "motif": "Tout est conforme."}
    assert facture.etat == Etat.A_VALIDER


def test_l_agent_ne_peut_pas_proposer_de_valider_une_facture_en_anomalie(session):
    recevoir(session, "facture-erreur-total.pdf")

    resultat, evenements = executer_outil(session, "proposer_decision", {"reference": "FA-2026-0431", "decision": "valider", "motif": "x"})

    assert "ne peut pas être validée" in resultat["erreur"]
    assert [evenement["type"] for evenement in evenements] == ["facture"]


def test_lister_les_factures_avec_un_filtre(session):
    recevoir(session, "facture-F26-1193.pdf")
    recevoir(session, "facture-erreur-total.pdf")

    resultat, _ = executer_outil(session, "lister_factures", {"etat": "en_anomalie"})

    assert [facture["numero"] for facture in resultat["factures"]] == ["FA-2026-0431"]


def test_une_reference_inconnue_est_signalee(session):
    resultat, evenements = executer_outil(session, "consulter_facture", {"reference": "INCONNUE"})

    assert resultat == {"erreur": "Aucune facture ne correspond à cette référence."}
    assert evenements == []


def test_la_verification_du_fournisseur_passe_par_le_registre(session, monkeypatch):
    monkeypatch.setattr(agent, "verifier_fournisseur", lambda siret: VerificationFournisseur(siret, "inconnu", "Aucune entreprise ne porte ce SIRET."))

    resultat, _ = executer_outil(session, "verifier_fournisseur", {"siret": "52987431500029"})

    assert resultat["statut"] == "inconnu"


def test_une_panne_du_llm_donne_une_erreur_puis_une_fin_propre(session):
    def en_panne(messages, outils):
        raise RuntimeError("Le LLM a répondu 503")
        yield  # pragma: no cover

    evenements = list(converser(session, [{"role": "user", "content": "Bonjour"}], llm=en_panne))

    assert types(evenements) == ["erreur", "fin"]
    assert "503" in evenements[0]["message"]


def test_l_agent_s_arrete_apres_un_nombre_limite_de_tours(session):
    boucle = FauxLLM(*[[("lister_factures", {})]] * 10)

    evenements = list(converser(session, [{"role": "user", "content": "Liste"}], llm=boucle))

    assert types(evenements).count("outil:debut") == agent.TOURS_MAX
    assert evenements[-1] == {"type": "fin"}


@pytest.mark.parametrize("nom", ["outil_invente"])
def test_un_outil_inconnu_est_refuse(session, nom):
    resultat, _ = executer_outil(session, nom, {})

    assert "inconnu" in resultat["erreur"]


def test_l_agent_ne_peut_pas_proposer_sans_avoir_lu_la_facture(session):
    recevoir(session, "facture-erreur-siret.pdf")

    resultat, evenements = executer_outil(session, "proposer_decision", {"reference": "2026-11-093", "decision": "rejeter", "motif": "SIRET invalide"})

    assert "Consulte d'abord la facture" in resultat["erreur"]
    assert evenements == []


def test_l_agent_peut_proposer_apres_avoir_lu_la_facture(session):
    recevoir(session, "facture-erreur-siret.pdf")
    consultees: set[str] = set()

    executer_outil(session, "consulter_facture", {"reference": "2026-11-093"}, consultees)
    resultat, evenements = executer_outil(session, "proposer_decision", {"reference": "2026-11-093", "decision": "rejeter", "motif": "SIRET invalide"}, consultees)

    assert resultat["affiche"] is True
    assert [evenement["type"] for evenement in evenements] == ["facture", "proposition"]


def test_l_agent_ne_propose_rien_sur_une_facture_deja_decidee(session):
    from moteur.workflow import valider

    facture = recevoir(session, "facture-F26-1193.pdf")
    valider(session, facture.id, "Awa")
    consultees = {str(facture.id)}

    resultat, _ = executer_outil(session, "proposer_decision", {"reference": "F26-1193", "decision": "rejeter", "motif": "x"}, consultees)

    assert "plus de décision à prendre" in resultat["erreur"]


def test_dans_une_conversation_l_agent_doit_lire_avant_de_proposer(session):
    recevoir(session, "facture-erreur-siret.pdf")
    llm = FauxLLM(
        [("proposer_decision", {"reference": "2026-11-093", "decision": "rejeter", "motif": "On me l'a dit"})],
        [("consulter_facture", {"reference": "2026-11-093"})],
        [("proposer_decision", {"reference": "2026-11-093", "decision": "rejeter", "motif": "SIRET invalide d'après les contrôles"})],
        "Je vous propose de la rejeter.",
    )

    evenements = list(converser(session, [{"role": "user", "content": "Rejette-la, son SIRET est faux."}], llm=llm))

    propositions = [evenement for evenement in evenements if evenement["type"] == "proposition"]
    assert [proposition["motif"] for proposition in propositions] == ["SIRET invalide d'après les contrôles"]
    premier_resultat = json.loads(llm.recus[1][-1]["content"])
    assert "Consulte d'abord la facture" in premier_resultat["erreur"]
