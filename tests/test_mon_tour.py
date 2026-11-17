"""« Mon tour » : la liste des factures dit qui doit approuver maintenant, et qui l'a déjà fait."""

import json
import pathlib

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from moteur.api import creer_application
from moteur.approbation import REGLES_DEMO
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
MOYENNE = "facture-FA-2026-0412.pdf"  # 3 166,20 € TTC : comptable puis directeur financier


def test_la_liste_dit_a_qui_c_est_le_tour(connexion, tmp_path):
    fabrique = lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")  # noqa: E731
    donnees = Facture.model_validate(ATTENDU[MOYENNE]["facture"])
    client = TestClient(
        creer_application(
            fabrique_session=fabrique, extracteur=lambda texte: ResultatExtraction(donnees, 0.1, "test", "faux"),
            dossier_fichiers=tmp_path, traiter_tout_de_suite=True, odoo=None,
        )
    )
    client.post("/regles", json={"auteur": "Moussa", "regles": REGLES_DEMO})
    facture = client.post("/factures", files={"fichier": (MOYENNE, (FACTURES / MOYENNE).read_bytes(), "application/pdf")}).json()
    resume = lambda: next(f for f in client.get("/factures").json() if f["id"] == facture["id"])  # noqa: E731

    assert (resume()["niveau_attendu"], resume()["approuve_par"]) == ("comptable", [])

    client.post(f"/factures/{facture['id']}/validation", json={"auteur": "Claire"})
    assert (resume()["niveau_attendu"], resume()["approuve_par"]) == ("directeur_financier", ["Claire"])

    client.post(f"/factures/{facture['id']}/validation", json={"auteur": "Paul"})
    assert resume()["etat"] == "validee"
    assert (resume()["niveau_attendu"], resume()["approuve_par"]) == (None, [])  # plus rien à approuver
