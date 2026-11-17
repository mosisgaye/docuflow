"""API publique avec clés, événements sortants signés, relances des approbateurs."""

import json
import pathlib
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from moteur import evenements_sortants, notifications, relances
from moteur.api import creer_application
from moteur.approbation import REGLES_DEMO, publier
from moteur.base import Livraison
from moteur.extraction_llm import ResultatExtraction
from moteur.modeles import Facture

FACTURES = pathlib.Path(__file__).resolve().parent.parent / "factures"
ATTENDU = json.loads((FACTURES / "attendu.json").read_text(encoding="utf-8"))
MOYENNE = "facture-FA-2026-0412.pdf"  # comptable puis directeur financier


@pytest.fixture(autouse=True)
def reglages(monkeypatch):
    monkeypatch.setenv("CONNECTEURS_CLE_CHIFFREMENT", Fernet.generate_key().decode())
    monkeypatch.setenv("APPROBATION_SECRET", "secret-de-test")
    monkeypatch.setenv("APPROBATION_DESTINATAIRE_COMPTABLE", "claire@exemple.fr")
    monkeypatch.setenv("APPROBATION_DESTINATAIRE_DIRECTEUR_FINANCIER", "paul@exemple.fr")


@pytest.fixture
def fabrique(connexion):
    return lambda: Session(bind=connexion, join_transaction_mode="create_savepoint")


@pytest.fixture
def boite():
    mails = []

    def envoyer(message):
        mails.append(message)
        return {"id": f"mail-{len(mails)}"}

    envoyer.mails = mails
    return envoyer


@pytest.fixture
def client(fabrique, tmp_path, boite):
    with fabrique() as session:
        publier(session, REGLES_DEMO, "Moussa")
        session.commit()
    donnees = Facture.model_validate(ATTENDU[MOYENNE]["facture"])
    return TestClient(
        creer_application(
            fabrique_session=fabrique, extracteur=lambda texte: ResultatExtraction(donnees, 0.1, "test", "faux"),
            dossier_fichiers=tmp_path, traiter_tout_de_suite=True, odoo=None, envoyeur_mail=boite,
        )
    )


def pdf() -> bytes:
    return (FACTURES / MOYENNE).read_bytes()


def nouvelle_cle(client, droits) -> str:
    reponse = client.post("/cles-api", json={"nom": "Logiciel de paie", "droits": droits, "auteur": "Moussa"})
    assert reponse.status_code == 201
    return reponse.json()["cle"]


# ───────── Les clés ─────────


def test_une_cle_valable_lit_les_factures(client):
    client.post("/factures", files={"fichier": (MOYENNE, pdf(), "application/pdf")})
    cle = nouvelle_cle(client, ["factures:lire"])

    liste = client.get("/v1/factures", headers={"Authorization": f"Bearer {cle}"})
    facture = liste.json()["factures"][0]
    detail = client.get(f"/v1/factures/{facture['id']}", headers={"Authorization": f"Bearer {cle}"}).json()

    assert liste.status_code == 200
    assert (facture["numero"], facture["etat"], facture["total_ttc"]) == ("FA-2026-0412", "a_valider", "3166.20")
    assert detail["journal"][0]["type"] == "RECEPTION"
    vue = client.get("/cles-api").json()["cles"][0]
    assert vue["utilisee_le"] is not None
    assert cle not in json.dumps(vue)  # la clé complète n'est jamais remontrée


def test_sans_cle_ou_avec_une_fausse_cle_c_est_401(client):
    cle = nouvelle_cle(client, ["factures:lire"])
    fausse = cle[:-4] + "XXXX"  # bon préfixe, mauvais secret

    assert client.get("/v1/factures").status_code == 401
    assert client.get("/v1/factures", headers={"Authorization": f"Bearer {fausse}"}).status_code == 401
    assert client.get("/v1/factures", headers={"Authorization": "Bearer dfk_inconnu_abc"}).status_code == 401
    assert client.get("/v1/factures", headers={"Authorization": f"Bearer {cle}"}).status_code == 200  # le cas légitime passe


def test_une_cle_sans_le_droit_de_deposer_est_refusee(client):
    lecture = nouvelle_cle(client, ["factures:lire"])
    depot = nouvelle_cle(client, ["factures:deposer"])

    refuse = client.post("/v1/factures", files={"fichier": (MOYENNE, pdf(), "application/pdf")}, headers={"Authorization": f"Bearer {lecture}"})
    accepte = client.post("/v1/factures", files={"fichier": (MOYENNE, pdf(), "application/pdf")}, headers={"Authorization": f"Bearer {depot}"})

    assert refuse.status_code == 403
    assert accepte.status_code == 202
    assert accepte.json()["etat"] == "recue"  # lue ensuite par le travailleur
    assert client.get("/v1/factures", headers={"Authorization": f"Bearer {depot}"}).status_code == 403
    reception = client.get(f"/factures/{accepte.json()['id']}").json()["evenements"][0]["detail"]
    assert reception["source"] == "api" and reception["cle_nom"] == "Logiciel de paie"


def test_une_cle_revoquee_ne_marche_plus(client):
    cle = nouvelle_cle(client, ["factures:lire"])
    identifiant = client.get("/cles-api").json()["cles"][0]["id"]

    client.delete(f"/cles-api/{identifiant}")

    assert client.get("/v1/factures", headers={"Authorization": f"Bearer {cle}"}).status_code == 401


def test_un_droit_inconnu_est_refuse(client):
    reponse = client.post("/cles-api", json={"nom": "x", "droits": ["factures:supprimer"], "auteur": "Moussa"})

    assert reponse.status_code == 422


# ───────── Les événements sortants ─────────


@pytest.mark.parametrize(
    "url",
    ["http://exemple.fr/crochet", "https://10.0.0.4/crochet", "https://192.168.1.10/crochet", "https://169.254.169.254/latest", "ftp://exemple.fr/x"],
)
def test_les_adresses_dangereuses_sont_refusees(client, url):
    reponse = client.post("/abonnements", json={"url": url, "evenements": ["facture.validee"], "auteur": "Moussa"})

    assert reponse.status_code == 422


def test_un_evenement_est_prepare_signe_et_livre(client, fabrique):
    abonnement = client.post(
        "/abonnements", json={"url": "https://erp.exemple.fr/docuflow", "evenements": ["facture.a_valider"], "auteur": "Moussa"}
    ).json()
    recus = []

    def serveur(requete):
        recus.append(requete)
        return httpx.Response(200)

    client.post("/factures", files={"fichier": (MOYENNE, pdf(), "application/pdf")})
    with fabrique() as session:
        livraison = evenements_sortants.livrer_une(session, httpx.Client(transport=httpx.MockTransport(serveur)))
        etat, identifiant = livraison.etat, str(livraison.id)

    assert etat == "livree"
    requete = recus[0]
    corps = json.loads(requete.content)
    assert corps["evenement"] == "facture.a_valider"
    assert corps["facture"]["numero"] == "FA-2026-0412"
    horodatage = requete.headers["X-Verifac-Horodatage"]
    # Le destinataire vérifie la signature avec le secret reçu à la création de l'abonnement.
    assert requete.headers["X-Verifac-Signature"] == evenements_sortants.signer(abonnement["secret"], horodatage, requete.content)
    assert requete.headers["X-Verifac-Livraison"] == identifiant
    assert requete.headers["X-Verifac-Evenement"] == "facture.a_valider"
    # L'ancien nom du produit n'est plus envoyé.
    assert not [nom for nom in requete.headers if nom.lower().startswith("x-docuflow-")]


def test_la_documentation_ne_montre_que_l_api_publique(client):
    # La documentation complète listait toutes les adresses internes (comptes, console…) : elle n'existe plus.
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404

    schema = client.get("/v1/openapi.json")
    assert schema.status_code == 200
    assert set(schema.json()["paths"]) == {"/v1/factures", "/v1/factures/{facture_id}"}
    assert schema.json()["components"]["securitySchemes"]["cle"]["scheme"] == "bearer"
    page = client.get("/v1/docs")
    assert page.status_code == 200 and "/api/v1/openapi.json" in page.text


def test_seuls_les_evenements_choisis_partent(client, fabrique):
    client.post("/abonnements", json={"url": "https://erp.exemple.fr/docuflow", "evenements": ["facture.rejetee"], "auteur": "Moussa"})

    client.post("/factures", files={"fichier": (MOYENNE, pdf(), "application/pdf")})

    with fabrique() as session:
        assert session.scalars(select(Livraison)).all() == []


def test_un_echec_est_retente_puis_abandonne(client, fabrique):
    client.post("/abonnements", json={"url": "https://erp.exemple.fr/docuflow", "evenements": ["facture.recue"], "auteur": "Moussa"})
    client.post("/factures", files={"fichier": (MOYENNE, pdf(), "application/pdf")})
    en_panne = httpx.Client(transport=httpx.MockTransport(lambda requete: httpx.Response(503)))

    with fabrique() as session:
        livraison = evenements_sortants.livrer_une(session, en_panne)
        assert (livraison.etat, livraison.tentatives, livraison.derniere_reponse) == ("en_attente", 1, "HTTP 503")
        assert livraison.prochain_essai_le > datetime.now(UTC) + timedelta(seconds=20)  # pas avant 30 s
        for _ in range(evenements_sortants.TENTATIVES_MAX - 1):
            livraison.prochain_essai_le = datetime.now(UTC) - timedelta(days=1)  # on avance l'horloge
            session.flush()
            evenements_sortants.livrer_une(session, en_panne)
        assert (livraison.etat, livraison.tentatives) == ("abandonnee", evenements_sortants.TENTATIVES_MAX)


def test_l_evenement_d_essai_et_la_desactivation(client, fabrique):
    abonnement = client.post("/abonnements", json={"url": "https://erp.exemple.fr/docuflow", "evenements": ["facture.validee"], "auteur": "Moussa"}).json()

    vue = client.post(f"/abonnements/{abonnement['id']}/essai").json()
    client.delete(f"/abonnements/{abonnement['id']}")

    assert vue["livraisons"][0]["evenement"] == "essai"
    assert "secret" not in vue
    assert client.get("/abonnements").json()["abonnements"] == []
    with fabrique() as session:
        livraison = evenements_sortants.livrer_une(session, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))))
        assert livraison.etat == "abandonnee"  # désactivé : plus rien ne part


# ───────── Les relances ─────────


def mail(niveau, il_y_a_h, rappel=None, maintenant=datetime(2026, 11, 15, 12, tzinfo=UTC)):
    return SimpleNamespace(type="NOTIFICATION", detail={"niveau": niveau, **({"rappel": rappel} if rappel else {})}, cree_le=maintenant - timedelta(hours=il_y_a_h))


MAINTENANT = datetime(2026, 11, 15, 12, tzinfo=UTC)


def facture_echeance(jours):
    return SimpleNamespace(donnees={"date_echeance": (date(2026, 11, 15) + timedelta(days=jours)).isoformat()})


def test_pas_de_relance_avant_48_heures():
    assert relances.a_relancer(facture_echeance(30), "comptable", [mail("comptable", 47)], MAINTENANT) is None
    assert "49 heures" in relances.a_relancer(facture_echeance(30), "comptable", [mail("comptable", 49)], MAINTENANT)


def test_une_echeance_proche_fait_relancer_plus_tot():
    raison = relances.a_relancer(facture_echeance(2), "comptable", [mail("comptable", 25)], MAINTENANT)

    assert raison == "l'échéance de paiement tombe dans 2 jours."


def test_deux_relances_au_plus_et_jamais_sans_premier_mail():
    deja = [mail("comptable", 200), mail("comptable", 100, "x"), mail("comptable", 50, "y")]

    assert relances.a_relancer(facture_echeance(30), "comptable", deja, MAINTENANT) is None
    assert relances.a_relancer(facture_echeance(30), "comptable", [], MAINTENANT) is None
    # Le mail du comptable ne compte pas pour le directeur financier, qui n'a jamais été prévenu.
    assert relances.a_relancer(facture_echeance(30), "directeur_financier", [mail("comptable", 100)], MAINTENANT) is None


def test_la_relance_part_au_bon_niveau_avec_son_rappel(client, fabrique, boite):
    client.post("/factures", files={"fichier": (MOYENNE, pdf(), "application/pdf")})
    assert [m.destinataire for m in boite.mails] == ["claire@exemple.fr"]

    with fabrique() as session:
        nombre = relances.relancer(session, datetime.now(UTC) + timedelta(hours=49))
        session.commit()
        notifications.envoyer_en_attente(session, fabrique, boite)

    assert nombre == 1
    rappel = boite.mails[-1]
    assert rappel.destinataire == "claire@exemple.fr"
    assert rappel.sujet.startswith("Rappel : approbation demandée")
    assert rappel.idempotence != boite.mails[0].idempotence  # sinon Resend l'ignorerait
    with fabrique() as session:  # juste après, rien de plus : la relance remet le compteur à zéro
        assert relances.relancer(session, datetime.now(UTC) + timedelta(hours=1)) == 0


def test_le_travailleur_livre_et_relance_sans_planter(client, fabrique):
    from moteur import travailleur

    # Adresse locale fermée : la livraison échoue tout de suite et sera retentée.
    client.post("/abonnements", json={"url": "http://127.0.0.1:9/docuflow", "evenements": ["facture.recue"], "auteur": "Moussa"})
    client.post("/factures", files={"fichier": (MOYENNE, pdf(), "application/pdf")})

    assert travailleur.livrer_les_evenements(fabrique) == 1
    assert travailleur.livrer_les_evenements(fabrique) == 0  # pas avant 30 s
    assert travailleur.faire_les_relances(fabrique) == 0  # le premier mail vient de partir
    livraison = client.get("/abonnements").json()["abonnements"][0]["livraisons"][0]
    assert (livraison["etat"], livraison["tentatives"], livraison["reponse"]) == ("en_attente", 1, "ConnectError")
