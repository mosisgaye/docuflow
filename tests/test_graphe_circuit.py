"""Le circuit en graphe (comme n8n) : forme vérifiée, parcours d'une facture, et équivalence avec les règles."""

import pytest

from moteur.approbation import REGLES_DEMO, circuit, publier
from moteur.graphe_circuit import GrapheInvalide, depuis_regles, parcourir, verifier

DEBUT = {"id": "debut", "type": "debut", "x": 0, "y": 0}
FIN = {"id": "fin", "type": "fin", "x": 900, "y": 0}
SEUIL = {"lignes": [{"champ": "total_ttc", "comparaison": "superieur_a", "valeur": "1000"}], "combinaison": "une"}
IBAN = {"lignes": [{"champ": "anomalie", "comparaison": "une_de", "valeur": ["IBAN_DIFFERENT", "IBAN_NOUVEAU"]}], "combinaison": "une"}


def graphe(*noeuds, liens):
    return {"noeuds": [DEBUT, *noeuds, FIN], "liens": [{"de": de, "vers": vers, "sortie": sortie} for de, vers, sortie in liens]}


def lien(de, vers, sortie=None):
    return (de, vers, sortie)


# Début → Comptable → Montant > 1 000 ? oui → Directeur financier → Odoo ; non → Odoo
SIMPLE = graphe(
    {"id": "compta", "type": "approbation", "x": 200, "y": 0, "niveau": "comptable"},
    {"id": "seuil", "type": "condition", "x": 400, "y": 0, "nom": "Plus de 1 000 €", "si": SEUIL},
    {"id": "dfi", "type": "approbation", "x": 600, "y": 100, "nom": "Directeur financier", "niveau": "directeur_financier"},
    liens=[lien("debut", "compta"), lien("compta", "seuil"), lien("seuil", "dfi", "oui"), lien("seuil", "fin", "non"), lien("dfi", "fin")],
)


def niveaux(resultat: dict) -> list[str]:
    return [n["niveau"] for n in resultat["niveaux"]]


# ───────── Le parcours ─────────


@pytest.mark.parametrize(("total", "attendus", "sortie"), [("478.08", ["comptable"], "non"), ("3166.20", ["comptable", "directeur_financier"], "oui")])
def test_une_facture_suit_oui_ou_non(total, attendus, sortie):
    resultat = parcourir(verifier(SIMPLE), {"total_ttc": total}, [])

    assert niveaux(resultat) == attendus and resultat["bloque"] is None
    assert {"id": "seuil", "sortie": sortie} in resultat["chemin"]
    assert resultat["chemin"][-1] == {"id": "fin", "sortie": None}


def test_un_blocage_arrete_le_parcours():
    bloque = graphe(
        {"id": "iban", "type": "condition", "x": 200, "y": 0, "nom": "IBAN changé", "si": IBAN},
        {"id": "stop", "type": "blocage", "x": 400, "y": -100, "nom": "IBAN à vérifier", "message": "Appelez le fournisseur."},
        {"id": "compta", "type": "approbation", "x": 400, "y": 0, "niveau": "comptable"},
        liens=[lien("debut", "iban"), lien("iban", "stop", "oui"), lien("iban", "compta", "non"), lien("compta", "fin")],
    )

    resultat = parcourir(verifier(bloque), {"total_ttc": "100"}, [{"code": "IBAN_NOUVEAU"}])

    assert resultat["bloque"] == "IBAN à vérifier : Appelez le fournisseur."
    assert resultat["chemin"][-1] == {"id": "stop", "sortie": None}


def test_sans_approbation_sur_le_chemin_le_comptable_valide_quand_meme():
    direct = graphe(liens=[lien("debut", "fin")])

    assert niveaux(parcourir(verifier(direct), {}, [])) == ["comptable"]


def test_les_niveaux_restent_dans_l_ordre_meme_si_le_graphe_les_inverse():
    inverse = graphe(
        {"id": "dfi", "type": "approbation", "x": 200, "y": 0, "niveau": "directeur_financier"},
        {"id": "compta", "type": "approbation", "x": 400, "y": 0, "niveau": "comptable"},
        liens=[lien("debut", "dfi"), lien("dfi", "compta"), lien("compta", "fin")],
    )

    assert niveaux(parcourir(verifier(inverse), {}, [])) == ["comptable", "directeur_financier"]


# ───────── Ce qui est refusé ─────────


@pytest.mark.parametrize(
    ("brut", "message"),
    [
        ({"noeuds": [DEBUT], "liens": []}, ""),  # pas d'Odoo
        (graphe({"id": "fin", "type": "approbation", "x": 1, "y": 1, "niveau": "comptable"}, liens=[]), "identifiant"),
        (graphe({"id": "seuil", "type": "condition", "x": 1, "y": 1, "si": SEUIL}, liens=[lien("debut", "seuil"), lien("seuil", "fin", "oui")]), "sortie Oui et une sortie Non"),
        (graphe({"id": "compta", "type": "approbation", "x": 1, "y": 1, "niveau": "comptable"}, liens=[lien("debut", "fin"), lien("compta", "fin")]), "non reliée"),
        (graphe({"id": "a", "type": "approbation", "x": 1, "y": 1, "niveau": "comptable"}, {"id": "b", "type": "approbation", "x": 2, "y": 1, "niveau": "gerant"}, liens=[lien("debut", "a"), lien("a", "b"), lien("b", "a")]), "une seule sortie|tourne en rond"),
        (graphe({"id": "a", "type": "approbation", "x": 1, "y": 1, "niveau": "comptable"}, liens=[lien("debut", "a"), lien("a", "a")]), "elle-même"),
        (graphe({"id": "a", "type": "approbation", "x": 1, "y": 1, "niveau": "stagiaire"}, liens=[lien("debut", "a"), lien("a", "fin")]), ""),
        (graphe({"id": "a", "type": "blocage", "x": 1, "y": 1, "message": "  "}, liens=[lien("debut", "a")]), "message ne peut pas être vide"),
        (graphe({"id": "a", "type": "blocage", "x": 1, "y": 1, "message": "x"}, liens=[lien("debut", "a"), lien("a", "fin")]), "termine le circuit"),
        (graphe({"id": "a", "type": "approbation", "x": 1, "y": 1, "niveau": "comptable", "si": SEUIL}, liens=[lien("debut", "a"), lien("a", "fin")]), "ne s'emploie que"),
        (graphe({"id": "a", "type": "condition", "x": 1, "y": 1}, liens=[]), "demande « si »"),
        (graphe(liens=[lien("debut", "fin"), lien("debut", "fin")]), "deux liens sur la même sortie"),
        (graphe(liens=[lien("debut", "inconnue")]), "n'existe pas"),
        (graphe(liens=[lien("debut", "fin"), lien("fin", "debut")]), "revenir au Début|termine"),
        (graphe({"id": "A B", "type": "approbation", "x": 1, "y": 1, "niveau": "comptable"}, liens=[]), ""),
        ({**graphe(liens=[lien("debut", "fin")]), "script": "x"}, ""),
    ],
)
def test_un_graphe_mal_forme_est_refuse_avec_un_message(brut, message):
    with pytest.raises(GrapheInvalide, match=message or None):
        verifier(brut)


# ───────── Les anciennes règles, ouvertes en graphe ─────────

CAS = [
    (total, anomalies)
    for total in ("0", "478.08", "1000", "1000.01", "3166.20", "5000", "5000.01", "7200")
    for anomalies in ((), ("ECART_COMMANDE",), ("SANS_COMMANDE",), ("IBAN_DIFFERENT",), ("IBAN_NOUVEAU",), ("FOURNISSEUR_INCONNU",), ("IBAN_NOUVEAU", "ECART_COMMANDE"))
]


def test_les_regles_en_production_donnent_le_meme_circuit_en_graphe(session):
    version = publier(session, REGLES_DEMO, "Moussa")
    converti = verifier(depuis_regles(REGLES_DEMO))

    for total, codes in CAS:
        donnees, liste = {"total_ttc": total}, [{"code": code} for code in codes]
        regles, parcours = circuit(donnees, liste, version), parcourir(converti, donnees, liste)
        assert bool(regles["bloque"]) == bool(parcours["bloque"]), (total, codes)
        if not regles["bloque"]:  # une facture bloquée ne s'approuve pas : ses niveaux ne comptent pas
            assert niveaux(regles) == niveaux(parcours), (total, codes)
            assert [n["raisons"] for n in regles["niveaux"]] == [n["raisons"] for n in parcours["niveaux"]], (total, codes)


@pytest.mark.parametrize(
    "regles",
    [
        REGLES_DEMO[:1],
        [{"nom": "Tout bloquer", "si": {"toujours": True}, "bloque": "Circuit en pause."}],
        [{"nom": "Deux niveaux", "si": SEUIL, "exige": ["directeur_financier", "gerant"]}],
        [{"nom": "Toujours deux", "si": {"toujours": True}, "exige": ["comptable", "gerant"]}],
    ],
)
def test_toute_forme_de_regles_se_convertit_en_graphe_valide(regles):
    converti = verifier(depuis_regles(regles))

    assert converti.noeud("debut") and converti.noeud("fin")


# ───────── « Pourquoi ce circuit ? » : le chemin en clair, gardé avec la facture ─────────


def test_le_circuit_d_une_facture_garde_son_chemin_en_clair(session):
    version = publier(session, [], "Moussa", graphe=SIMPLE)

    calcule = circuit({"total_ttc": "3166.20"}, [], version)

    assert [(e["nom"], e["sortie"]) for e in calcule["etapes"]] == [
        ("Début", None),
        ("Comptable", None),
        ("Plus de 1 000 €", "oui"),
        ("Directeur financier", None),
        ("Odoo", None),
    ]
    assert calcule["etapes"][2]["condition"] == "Montant TTC supérieur à 1 000 €"
    assert calcule["etapes"][1]["niveau"] == "comptable"


def test_une_version_en_regles_n_a_pas_de_chemin_en_clair(session):
    version = publier(session, REGLES_DEMO, "Moussa")

    assert "etapes" not in circuit({"total_ttc": "100"}, [], version)
