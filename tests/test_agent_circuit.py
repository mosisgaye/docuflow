"""Les compétences « circuit » de l'agent : modèles prêts à l'emploi, brouillon seulement, jamais de publication."""

import json

import pytest
from graphes_exemples import circuit_simple

from moteur import editeur_circuit, modeles_circuit
from moteur.agent import OUTILS, converser, executer_outil
from moteur.approbation import publier, version_en_vigueur
from moteur.graphe_circuit import parcourir, verifier


class FauxLLM:
    """Joue un scénario : chaque tour renvoie soit des appels d'outils, soit du texte."""

    def __init__(self, *tours):
        self.tours = list(tours)

    def __call__(self, messages, outils):
        tour = self.tours.pop(0)
        if isinstance(tour, str):
            yield {"texte": tour}
        else:
            yield {"appels": [{"id": f"appel-{rang}", "nom": nom, "arguments": json.dumps(arguments)} for rang, (nom, arguments) in enumerate(tour)]}


def niveaux(resultat: dict) -> list[str]:
    return [n["niveau"] for n in resultat["niveaux"]]


# ───────── Les modèles ─────────


@pytest.mark.parametrize("code", list(modeles_circuit.MODELES))
def test_chaque_modele_donne_un_circuit_complet(code):
    verifier(modeles_circuit.construire(code))


@pytest.mark.parametrize(
    ("total", "anomalies", "attendus", "bloque"),
    [
        ("500", [], ["comptable"], False),
        ("3000", [], ["comptable", "directeur_financier"], False),
        ("8000", [], ["comptable", "directeur_financier", "gerant"], False),
        ("500", ["ECART_COMMANDE"], ["comptable", "directeur_financier"], False),
        ("500", ["IBAN_NOUVEAU"], None, True),
        ("500", ["FOURNISSEUR_INCONNU"], None, True),
    ],
)
def test_le_modele_complet_fait_ce_qu_il_annonce(total, anomalies, attendus, bloque):
    graphe = verifier(modeles_circuit.construire("complet"))

    resultat = parcourir(graphe, {"total_ttc": total}, [{"code": code} for code in anomalies])

    assert bool(resultat["bloque"]) is bloque
    if attendus:
        assert niveaux(resultat) == attendus


def test_les_seuils_se_reglent_et_sont_verifies():
    graphe = verifier(modeles_circuit.construire("classique", 2500, "10 000"))

    assert niveaux(parcourir(graphe, {"total_ttc": "3000"}, [])) == ["comptable", "directeur_financier"]
    assert niveaux(parcourir(graphe, {"total_ttc": "2000"}, [])) == ["comptable"]
    for dfi, gerant in ((5000, 1000), ("mille", None), (-5, None)):
        with pytest.raises(modeles_circuit.ModeleInconnu):
            modeles_circuit.construire("classique", dfi, gerant)
    with pytest.raises(modeles_circuit.ModeleInconnu):
        modeles_circuit.construire("inexistant")


# ───────── Les outils de l'agent ─────────


def test_l_agent_connait_ses_quatre_competences_circuit():
    noms = {outil["function"]["name"] for outil in OUTILS}

    assert {"consulter_circuit", "lister_modeles_circuit", "creer_circuit_depuis_modele", "modifier_seuil"} <= noms


def test_creer_un_circuit_ecrit_le_brouillon_et_ne_publie_rien(session):
    publier(session, [], "Moussa", graphe=circuit_simple())

    resultat, evenements = executer_outil(session, "creer_circuit_depuis_modele", {"modele": "anti_fraude"}, auteur="Claire")

    assert resultat["enregistre"] is True and evenements[0]["type"] == "circuit"
    brouillon = editeur_circuit.lire(session)
    assert brouillon["modifie"] is True and brouillon["modifie_par"] == "Claire (via l’agent)"
    assert brouillon["a_completer"] is None
    assert version_en_vigueur(session).version == 1  # rien de publié


def test_un_brouillon_modifie_n_est_pas_remplace_sans_accord(session):
    editeur_circuit.enregistrer(session, circuit_simple(), None, "Claire")

    refus, _ = executer_outil(session, "creer_circuit_depuis_modele", {"modele": "classique"}, auteur="Paul")
    assert "Demande à la personne" in refus["erreur"]
    assert editeur_circuit.lire(session)["modifie_par"] == "Claire"

    accord, _ = executer_outil(session, "creer_circuit_depuis_modele", {"modele": "classique", "remplacer": True}, auteur="Paul")
    assert accord["enregistre"] is True and editeur_circuit.lire(session)["modifie_par"] == "Paul (via l’agent)"


def test_modifier_un_seuil(session):
    executer_outil(session, "creer_circuit_depuis_modele", {"modele": "classique"}, auteur="Claire")

    resultat, _ = executer_outil(session, "modifier_seuil", {"etape": "plus de 1 000", "montant": 2500}, auteur="Claire")

    assert resultat["enregistre"] is True
    graphe = verifier(editeur_circuit.lire(session)["graphe"])
    assert niveaux(parcourir(graphe, {"total_ttc": "2000"}, [])) == ["comptable"]  # 2 000 € < 2 500 €


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"etape": "inexistante", "montant": 100}, "Aucune condition de montant"),
        ({"etape": "plus de", "montant": 100}, "Plusieurs condition"),  # deux seuils correspondent
        ({"etape": "plus de 1 000", "montant": "mille"}, "n'est pas un montant"),
        ({"etape": "plus de 1 000", "montant": -1}, "pas un seuil possible"),
    ],
)
def test_un_seuil_mal_designe_est_refuse(session, arguments, message):
    executer_outil(session, "creer_circuit_depuis_modele", {"modele": "classique"}, auteur="Claire")

    resultat, _ = executer_outil(session, "modifier_seuil", arguments, auteur="Claire")

    assert message in resultat["erreur"]


def test_consulter_le_circuit_en_clair(session):
    publier(session, [], "Moussa", graphe=circuit_simple())

    vue, _ = executer_outil(session, "consulter_circuit", {})

    assert vue["version_en_service"] == 1 and vue["brouillon_modifie"] is False
    assert {"nom": "Plus de 1 000 €", "role": "si Montant TTC supérieur à 1 000 €"} in vue["etapes"]
    assert "Plus de 1 000 € (oui) → Directeur financier" in vue["liens"]


def test_par_la_conversation_l_agent_pose_un_modele_et_le_dit(session):
    llm = FauxLLM([("creer_circuit_depuis_modele", {"modele": "complet", "seuil_directeur_financier": 2000})], "C'est prêt dans le brouillon.")

    evenements = list(converser(session, [{"role": "user", "content": "Crée-moi un circuit complet"}], llm=llm, auteur="Moussa"))

    circuits = [e for e in evenements if e["type"] == "circuit"]
    assert circuits and "Complet pour une PME" in circuits[0]["message"]
    assert editeur_circuit.lire(session)["modifie_par"] == "Moussa (via l’agent)"
    assert evenements[-1] == {"type": "fin"}
