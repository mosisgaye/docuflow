"""API web du moteur : ce que l'interface appelle.

    POST /factures                    déposer un PDF : enregistré tout de suite (202), lu par le travailleur
    GET  /factures                    lister (filtre possible sur l'état)
    GET  /factures/{id}               détail, anomalies et journal
    GET  /factures/{id}/fichier       le PDF d'origine
    POST /factures/{id}/validation    valider (une personne)
    POST /factures/{id}/rejet         rejeter (une personne, avec un motif)
    POST /factures/{id}/export        envoyer une facture validée à la comptabilité
    GET  /factures/{id}/export        le fichier CSV de l'écriture comptable
    POST /reception/mail              un mail brut reçu à l'adresse de dépôt, transmis et signé par l'adaptateur
    GET  /connecteurs                 le catalogue des connecteurs, et ceux qui sont branchés
    GET  /connecteurs/{id}            un connecteur : ses outils, les derniers appels de l'assistant
    POST /connecteurs/{id}/branchement   brancher un connecteur (son serveur MCP doit répondre)
    DELETE /connecteurs/{id}/branchement débrancher
    PUT  /connecteurs/{id}/outils     choisir les outils de lecture autorisés
    POST /connecteurs/{id}/oauth      commencer la connexion d'un compte (renvoie l'adresse de l'éditeur)
    GET  /oauth/retour                l'éditeur y renvoie le navigateur après la connexion
    GET  /regles                      les règles d'approbation en vigueur
    POST /regles                      publier une nouvelle version des règles
    GET  /approbation/{jeton}         la page de confirmation ouverte depuis le lien du mail
    POST /approbation/{jeton}         approuver ou rejeter depuis cette page
    POST /agent                       parler à l'assistant (réponse envoyée au fil de l'eau)
    GET  /statistiques                les chiffres du tableau de bord
    GET  /sante                       l'API et la base répondent-elles ? où en est la file de tâches ?

Lancement : uv run uvicorn moteur.api:creer_application --factory --port 8010
La lecture des factures est faite par un processus à part : uv run python -m moteur.travailleur
"""

import json
import logging
from html import escape as html_escape
import pathlib
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime

import httpx
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pypdf.errors import PyPdfError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, object_session, sessionmaker

from moteur import config
from moteur.agent import converser, flux_openai
from moteur.agent import version_consigne as consigne_assistant
from moteur.consignes import enregistrer as enregistrer_consigne
from moteur.base import Etat, EtatTache, Evenement, FactureEnBase, Tache, creer_moteur, verifier_schema
from moteur.extraction_llm import ResultatExtraction, extraire, extraire_images
from moteur.export import ErreurEnvoi, ErreurExport
from moteur.lecture_pdf import image_en_pdf, lire_pdf
from moteur.odoo import Odoo, depuis_configuration
from moteur.base import AppelConnecteur, ConnecteurBranche
from moteur import oauth
from moteur.approbation import LIBELLES, approbations_valides, empreinte, niveau_attendu, publier, version_en_vigueur
from moteur import notifications
from moteur.connecteurs import CATALOGUE, ErreurConnecteur, Passerelle, adresse_serveur, fiche_catalogue
from moteur.reception_mail import SignatureInvalide, cles_publiques, lire_mail_brut, recevoir_mail, verifier_signature
from moteur.workflow import FactureIntrouvable, TransitionInterdite, exporter, ranger_fichier, recevoir, rejeter, traiter, valider

TAILLE_MAX_OCTETS = 10 * 1024 * 1024
TAILLE_MAX_MAIL_OCTETS = 30 * 1024 * 1024  # Email Routing n'accepte pas de mail de plus de 25 Mo


class EvenementSortie(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rang: int
    type: str
    etat: str
    auteur: str
    detail: dict
    cree_le: datetime


class FactureResume(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom_fichier: str
    etat: str
    numero_facture: str | None
    fournisseur_siret: str | None
    fournisseur_nom: str | None = None
    total_ttc: str | None = None
    nb_anomalies: int = 0
    cree_le: datetime


class FactureDetail(FactureResume):
    donnees: dict | None
    anomalies: list[dict]
    evenements: list[EvenementSortie]
    circuit: dict | None = None  # qui doit approuver et pourquoi
    approbations: list[dict] = []  # qui a déjà approuvé, à quel niveau
    niveau_attendu: str | None = None  # le prochain niveau qui doit approuver


class FactureDeposee(FactureDetail):
    deja_vue: bool


class Validation(BaseModel):
    auteur: str = Field(min_length=1, max_length=100)


class Rejet(Validation):
    motif: str = Field(min_length=1, max_length=500)


class MessageAgent(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(min_length=1, max_length=8000)


class DemandeAgent(BaseModel):
    messages: list[MessageAgent] = Field(min_length=1, max_length=40)
    facture_id: uuid.UUID | None = None  # la facture affichée à l'écran, s'il y en a une
    auteur: str | None = Field(default=None, max_length=100)  # la personne connectée, pour signer les courriels


def _resume(facture: FactureEnBase) -> dict:
    donnees = facture.donnees or {}
    return {
        "id": facture.id,
        "nom_fichier": facture.nom_fichier,
        "etat": facture.etat,
        "numero_facture": facture.numero_facture,
        "fournisseur_siret": facture.fournisseur_siret,
        "fournisseur_nom": donnees.get("fournisseur_nom"),
        "total_ttc": donnees.get("total_ttc"),
        "nb_anomalies": len(facture.anomalies),
        "cree_le": facture.cree_le,
    }


def _detail(facture: FactureEnBase) -> dict:
    session = object_session(facture)
    approuvables = facture.etat in (Etat.A_VALIDER.value, Etat.EN_APPROBATION.value)
    valides = approbations_valides(session, facture) if session else []
    return {
        **_resume(facture),
        "donnees": facture.donnees,
        "anomalies": facture.anomalies,
        "evenements": [EvenementSortie.model_validate(evenement) for evenement in facture.evenements],
        "circuit": facture.circuit,
        "approbations": [{"niveau": a.niveau, "personne": a.personne, "cree_le": a.cree_le.isoformat()} for a in valides],
        "niveau_attendu": niveau_attendu(session, facture) if session and approuvables else None,
    }


def creer_application(
    fabrique_session: Callable[[], Session] | None = None,
    extracteur: Callable[[str], ResultatExtraction] = extraire,
    dossier_fichiers: pathlib.Path | None = None,
    extracteur_images: Callable[[list[bytes]], ResultatExtraction] = extraire_images,
    llm_agent: Callable = flux_openai,
    dossier_exports: pathlib.Path | None = None,
    client_export=None,
    traiter_tout_de_suite: bool = False,
    cles_mail: list | None = None,
    odoo: Odoo | None | str = "configuration",
    passerelle: Passerelle | None = None,
    client_oauth: httpx.Client | None = None,
    envoyeur_mail: Callable | None = None,
) -> FastAPI:
    """Construit l'application. Les paramètres servent aux tests ; en service, tout vient de .env.

    traiter_tout_de_suite : lire la facture pendant la requête au lieu de la confier au travailleur.
    Utile aux tests et aux démonstrations sans travailleur ; jamais en service.
    cles_mail : clés publiques des adaptateurs de messagerie. Sans elles, la réception par mail est fermée.
    odoo : le connecteur Odoo ; par défaut, celui de la configuration (None s'il n'y a pas de clé).
    passerelle : l'accès aux connecteurs MCP ; par défaut, celui des serveurs du catalogue.
    """
    if fabrique_session is None:
        moteur_base = creer_moteur()
        verifier_schema(moteur_base)
        fabrique_session = sessionmaker(moteur_base)
    dossier = dossier_fichiers or config.dossier_fichiers()
    dossier.mkdir(parents=True, exist_ok=True)
    cles_mail = cles_mail if cles_mail is not None else cles_publiques(config.lire("RECEPTION_MAIL_CLES_PUBLIQUES", ""))
    odoo = depuis_configuration() if odoo == "configuration" else odoo
    passerelle = passerelle or Passerelle(fabrique_session)
    exports = dossier_exports or pathlib.Path(config.lire("EXPORTS_DOSSIER", str(config.RACINE / "donnees" / "exports")))

    # L'assistant ne garde pas ses conversations : on enregistre sa consigne une fois, au démarrage,
    # pour que l'empreinte jointe à ses propositions renvoie toujours à un texte connu.
    with fabrique_session() as session:
        enregistrer_consigne(session, consigne_assistant())
        session.commit()

    application = FastAPI(title="Moteur de factures", version="0.1.0")

    def session_de_requete() -> Iterator[Session]:
        # Une transaction par requête : tout est enregistré, ou rien.
        # Utilisée avec scope="function" : l'enregistrement a lieu AVANT l'envoi de la réponse.
        # Par défaut, FastAPI le ferait après, et l'interface pourrait relire une donnée pas encore enregistrée.
        session = fabrique_session()
        try:
            yield session
            session.commit()
            # Les mails d'approbation préparés pendant la requête partent maintenant, une fois tout enregistré.
            notifications.envoyer_en_attente(session, fabrique_session, envoyeur_mail or notifications.envoyer_par_resend)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def facture_ou_404(session: Session, facture_id: uuid.UUID) -> FactureEnBase:
        facture = session.get(FactureEnBase, facture_id)
        if facture is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Facture introuvable.")
        return facture

    @application.get("/sante")
    def sante(session: Session = Depends(session_de_requete, scope="function")) -> dict:
        """État du service et de la file : c'est le point de supervision."""
        session.execute(text("select 1"))
        compte = dict(session.execute(select(Tache.etat, func.count()).group_by(Tache.etat)).all())
        plus_ancienne = session.scalar(
            select(func.extract("epoch", func.now() - func.min(Tache.cree_le))).where(Tache.etat == EtatTache.EN_ATTENTE.value)
        )
        return {
            "etat": "ok",
            "file": {
                "en_attente": compte.get(EtatTache.EN_ATTENTE.value, 0),
                "abandonnees": compte.get(EtatTache.ABANDONNEE.value, 0),
                "plus_ancienne_attente_s": round(float(plus_ancienne)) if plus_ancienne is not None else None,
            },
        }

    @application.post("/factures", response_model=FactureDeposee, status_code=status.HTTP_202_ACCEPTED)
    def deposer(reponse: Response, fichier: UploadFile = File(...), session: Session = Depends(session_de_requete, scope="function")) -> dict:
        contenu = fichier.file.read(TAILLE_MAX_OCTETS + 1)
        if len(contenu) > TAILLE_MAX_OCTETS:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Fichier trop volumineux (10 Mo au maximum).")
        nom = pathlib.Path(fichier.filename or "facture.pdf").name
        if not contenu.startswith(b"%PDF-"):
            # Une photo de facture (JPEG, PNG, WebP…) est mise dans un PDF : le reste du circuit est le même.
            pdf = image_en_pdf(contenu)
            if pdf is None:
                raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Seuls les PDF et les photos (JPEG, PNG) sont acceptés.")
            contenu, nom = pdf, f"{pathlib.Path(nom).stem or 'photo'}.pdf"
        try:
            lire_pdf(contenu)  # vérifie que le PDF s'ouvre
        except PyPdfError as erreur:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ce fichier PDF est illisible.") from erreur
        # Le fichier est écrit AVANT la tâche : le travailleur ne peut jamais chercher un fichier absent.
        ranger_fichier(dossier, contenu)
        if traiter_tout_de_suite:
            resultat = traiter(session, contenu, nom, extracteur, odoo=odoo, extracteur_images=extracteur_images)
            reponse.status_code = status.HTTP_201_CREATED
        else:
            resultat = recevoir(session, contenu, nom)
        if resultat.deja_vue:
            reponse.status_code = status.HTTP_200_OK
        return {**_detail(resultat.facture), "deja_vue": resultat.deja_vue}

    async def corps_signe(
        requete: Request,
        horodatage: str | None = Header(default=None, alias="X-DocuFlow-Horodatage"),
        signature: str | None = Header(default=None, alias="X-DocuFlow-Signature"),
    ) -> bytes:
        """Le corps brut de la requête, seulement si l'adaptateur de messagerie l'a bien signé."""
        if not cles_mail:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "La réception par mail n'est pas configurée.")
        corps = b""
        async for morceau in requete.stream():
            corps += morceau
            if len(corps) > TAILLE_MAX_MAIL_OCTETS:
                raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Mail trop volumineux.")
        try:
            verifier_signature(cles_mail, horodatage, signature, corps)
        except SignatureInvalide as erreur:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(erreur)) from erreur
        return corps

    @application.post("/reception/mail", status_code=status.HTTP_202_ACCEPTED)
    def recevoir_un_mail(
        reponse: Response, corps: bytes = Depends(corps_signe), session: Session = Depends(session_de_requete, scope="function")
    ) -> dict:
        # Le corps est le mail brut, lu à la main (et non par FastAPI) : la signature porte sur ses octets exacts.
        if not corps.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Mail vide.")
        compte_rendu = recevoir_mail(session, lire_mail_brut(corps), dossier)
        if compte_rendu.deja_vu:
            reponse.status_code = status.HTTP_200_OK
        mail = compte_rendu.mail
        return {"id": mail.id, "deja_vu": compte_rendu.deja_vu, "statut": mail.statut, "pieces": mail.pieces}

    @application.get("/factures", response_model=list[FactureResume])
    def lister(etat: Etat | None = None, session: Session = Depends(session_de_requete, scope="function")) -> list[dict]:
        requete = select(FactureEnBase).order_by(FactureEnBase.cree_le.desc(), FactureEnBase.nom_fichier)
        if etat is not None:
            requete = requete.where(FactureEnBase.etat == etat.value)
        return [_resume(facture) for facture in session.scalars(requete)]

    @application.get("/factures/{facture_id}", response_model=FactureDetail)
    def detailler(facture_id: uuid.UUID, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        return _detail(facture_ou_404(session, facture_id))

    @application.get("/factures/{facture_id}/fichier")
    def telecharger(facture_id: uuid.UUID, session: Session = Depends(session_de_requete, scope="function")) -> FileResponse:
        facture = facture_ou_404(session, facture_id)
        chemin = dossier / f"{facture.empreinte}.pdf"
        if not chemin.exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Le fichier d'origine n'est plus disponible.")
        return FileResponse(chemin, media_type="application/pdf", filename=facture.nom_fichier, content_disposition_type="inline")

    def decider(action: Callable[[], FactureEnBase]) -> dict:
        try:
            return _detail(action())
        except FactureIntrouvable as erreur:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Facture introuvable.") from erreur
        except TransitionInterdite as erreur:
            raise HTTPException(status.HTTP_409_CONFLICT, str(erreur)) from erreur

    @application.post("/factures/{facture_id}/validation", response_model=FactureDetail)
    def valider_facture(facture_id: uuid.UUID, demande: Validation, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        return decider(lambda: valider(session, facture_id, demande.auteur))

    @application.post("/factures/{facture_id}/rejet", response_model=FactureDetail)
    def rejeter_facture(facture_id: uuid.UUID, demande: Rejet, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        return decider(lambda: rejeter(session, facture_id, demande.auteur, demande.motif))

    @application.post("/factures/{facture_id}/export", response_model=FactureDetail)
    def exporter_facture(facture_id: uuid.UUID, demande: Validation, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        try:
            return decider(lambda: exporter(session, facture_id, demande.auteur, exports, client_export, odoo=odoo, dossier_fichiers=dossier))
        except ErreurExport as erreur:
            # L'échec est inscrit au journal : on l'enregistre avant de répondre par une erreur.
            session.commit()
            code = status.HTTP_502_BAD_GATEWAY if isinstance(erreur, ErreurEnvoi) else status.HTTP_422_UNPROCESSABLE_CONTENT
            raise HTTPException(code, str(erreur)) from erreur

    @application.get("/factures/{facture_id}/export")
    def telecharger_export(facture_id: uuid.UUID, session: Session = Depends(session_de_requete, scope="function")) -> FileResponse:
        facture = facture_ou_404(session, facture_id)
        export = next((evenement for evenement in reversed(facture.evenements) if evenement.type == "EXPORT"), None)
        if export is None or not (exports / export.detail["fichier"]).exists():
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Cette facture n'a pas encore été exportée.")
        return FileResponse(exports / export.detail["fichier"], media_type="text/csv", filename=export.detail["fichier"])

    @application.get("/statistiques")
    def statistiques(session: Session = Depends(session_de_requete, scope="function")) -> dict:
        """Les chiffres du tableau de bord. Tout est calculé depuis la base, rien n'est estimé."""
        factures = list(session.scalars(select(FactureEnBase).order_by(FactureEnBase.cree_le.desc(), FactureEnBase.nom_fichier)))
        par_etat = {etat.value: 0 for etat in Etat}
        for facture in factures:
            par_etat[facture.etat] += 1
        conformes = sum(1 for facture in factures if not facture.anomalies and facture.etat != Etat.ECHEC.value)
        extractions = session.scalars(select(Evenement).where(Evenement.type == "EXTRACTION").order_by(Evenement.cree_le)).all()
        durees = [float(evenement.detail["duree_s"]) for evenement in extractions if "modele" in evenement.detail]
        lues_sans_ia = len({evenement.facture_id for evenement in extractions if evenement.detail.get("source") == "factur-x"})
        lues_par_ia = len({evenement.facture_id for evenement in extractions if "modele" in evenement.detail})
        derniers = session.scalars(select(Evenement).order_by(Evenement.cree_le.desc(), Evenement.rang.desc()).limit(8)).all()
        return {
            "total": len(factures),
            "par_etat": par_etat,
            "conformes": conformes,
            "anomalies_detectees": sum(len(facture.anomalies) for facture in factures),
            "duree_moyenne_s": round(sum(durees) / len(durees), 2) if durees else None,
            "lues_sans_ia": lues_sans_ia,
            "lues_par_ia": lues_par_ia,
            "durees_recentes_s": durees[-12:],
            "recentes": [_resume(facture) for facture in factures[:6]],
            "activite": [
                {
                    "facture_id": evenement.facture_id,
                    "numero_facture": evenement.facture.numero_facture,
                    "nom_fichier": evenement.facture.nom_fichier,
                    **EvenementSortie.model_validate(evenement).model_dump(),
                }
                for evenement in derniers
            ],
        }

    # ───────── Règles d'approbation ─────────

    @application.get("/regles")
    def lire_regles(session: Session = Depends(session_de_requete, scope="function")) -> dict | None:
        version = version_en_vigueur(session)
        if version is None:
            return None
        return {"version": version.version, "regles": version.regles, "publie_par": version.publie_par, "publie_le": version.publie_le}

    class Publication(BaseModel):
        auteur: str = Field(min_length=1, max_length=100)
        regles: list[dict] = Field(min_length=1, max_length=50)

    @application.post("/regles", status_code=status.HTTP_201_CREATED)
    def publier_regles(demande: Publication, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        try:
            version = publier(session, demande.regles, demande.auteur)
        except ValidationError as erreur:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Règle mal formée : {erreur.errors()[0]['msg']}") from erreur
        return {"version": version.version, "regles": version.regles, "publie_par": version.publie_par}

    # ───────── Approbation depuis le lien du mail ─────────

    def page(titre: str, corps: str, code: int = 200) -> HTMLResponse:
        return HTMLResponse(
            f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{titre} | DocuFlow</title><style>
body{{font:16px/1.55 Arial,sans-serif;background:#f4f6fb;color:#13203a;margin:0;padding:32px 16px}}
main{{max-width:560px;margin:0 auto;background:#fff;border:1px solid #dfe5ef;border-radius:16px;padding:24px}}
h1{{font-size:22px;margin:0 0 12px}} .doux{{color:#55627b}} .alerte{{background:#fdeed6;color:#8a4a00;padding:8px 12px;border-radius:8px}}
.erreur{{background:#fdecea;color:#b3261e;padding:10px 14px;border-radius:8px}}
button{{font:600 16px Arial,sans-serif;border:0;border-radius:10px;padding:12px 18px;cursor:pointer}}
.oui{{background:#1f5bff;color:#fff}} .non{{background:#fdecea;color:#b3261e}}
textarea{{width:100%;box-sizing:border-box;border:1px solid #dfe5ef;border-radius:8px;padding:8px;font:inherit}}
form{{margin-top:16px;display:grid;gap:8px}} dl{{display:grid;grid-template-columns:auto 1fr;gap:4px 14px}} dt{{color:#55627b}}
</style></head><body><main>{corps}</main></body></html>""",
            status_code=code,
        )

    def facture_du_lien(session: Session, jeton: str) -> tuple[FactureEnBase, dict]:
        """Le lien est-il encore valable pour cette facture, maintenant ? Sinon LienInvalide avec la raison."""
        charge = notifications.lire_lien(jeton)
        facture = session.get(FactureEnBase, uuid.UUID(charge["f"]), with_for_update=True)
        if facture is None:
            raise notifications.LienInvalide("Cette facture n'existe plus.")
        if facture.etat not in (Etat.A_VALIDER.value, Etat.EN_APPROBATION.value):
            raise notifications.LienInvalide(f"Cette facture est déjà « {facture.etat.replace('_', ' ')} » : il n'y a plus rien à décider.")
        if empreinte(facture.donnees)[:32] != charge["h"]:
            raise notifications.LienInvalide("La facture a changé depuis l'envoi du mail : ce lien ne vaut plus.")
        if niveau_attendu(session, facture) != charge["n"]:
            raise notifications.LienInvalide("Ce niveau a déjà été approuvé : ce lien a servi.")
        return facture, charge

    def resume_html(facture: FactureEnBase, charge: dict) -> str:
        from html import escape

        d = facture.donnees or {}
        lignes = "".join(f'<p class="alerte">{escape(a["message"])}</p>' for a in facture.anomalies)
        return (
            f"<h1>Facture {escape(str(d.get('numero_facture') or '?'))}</h1>"
            f"<dl><dt>Fournisseur</dt><dd>{escape(str(d.get('fournisseur_nom') or '?'))}</dd>"
            f"<dt>Total TTC</dt><dd>{escape(str(d.get('total_ttc') or '?'))} €</dd>"
            f"<dt>Votre rôle</dt><dd>{escape(LIBELLES[charge['n']])} ({escape(charge['p'])})</dd></dl>{lignes}"
        )

    @application.get("/approbation/{jeton}", response_class=HTMLResponse)
    def voir_approbation(jeton: str, session: Session = Depends(session_de_requete, scope="function")) -> HTMLResponse:
        try:
            facture, charge = facture_du_lien(session, jeton)
        except notifications.LienInvalide as erreur:
            return page("Lien sans effet", f'<h1>Lien sans effet</h1><p class="erreur">{html_escape(str(erreur))}</p>', 410)
        # Rien n'est fait à l'ouverture : il faut cliquer (les messageries ouvrent les liens toutes seules).
        return page(
            "Décision",
            resume_html(facture, charge)
            + '<form method="post"><input type="hidden" name="decision" value="approuver"><button class="oui">Approuver la facture</button></form>'
            + '<form method="post"><input type="hidden" name="decision" value="rejeter">'
            + '<label for="motif" class="doux">Ou rejeter, avec le motif :</label><textarea id="motif" name="motif" rows="2" maxlength="500" required></textarea>'
            + '<button class="non">Rejeter la facture</button></form>',
        )

    @application.post("/approbation/{jeton}", response_class=HTMLResponse)
    def decider_approbation(
        jeton: str, decision: str = Form(...), motif: str = Form(""), session: Session = Depends(session_de_requete, scope="function")
    ) -> HTMLResponse:
        try:
            facture, charge = facture_du_lien(session, jeton)
            if decision == "rejeter":
                if not motif.strip():
                    raise notifications.LienInvalide("Un rejet demande un motif.")
                rejeter(session, facture.id, charge["p"], motif.strip()[:500])
                return page("Facture rejetée", f"<h1>Facture rejetée</h1><p>Motif enregistré au journal, à votre nom ({html_escape(charge['p'])}).</p>")
            valider(session, facture.id, charge["p"])
        except (notifications.LienInvalide, TransitionInterdite) as erreur:
            return page("Décision impossible", f'<h1>Décision impossible</h1><p class="erreur">{html_escape(str(erreur))}</p>', 409)
        suite = "La facture est validée : tous les niveaux ont approuvé." if facture.etat == Etat.VALIDEE.value else "Le niveau suivant vient d'être prévenu par mail."
        return page("Facture approuvée", f"<h1>Merci, c'est approuvé</h1><p>{suite}</p>")

    # ───────── Connecteurs ─────────

    def connecteur_ou_404(identifiant: str) -> dict:
        entree = fiche_catalogue(identifiant)
        if entree is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Connecteur inconnu.")
        return entree

    def vue_connecteur(entree: dict, branche: ConnecteurBranche | None) -> dict:
        return {
            **{cle: valeur for cle, valeur in entree.items() if cle != "transport"},
            "branche": bool(branche and branche.actif),
            "outils_autorises": branche.outils_autorises if branche else None,
            "branche_par": branche.branche_par if branche else None,
            "branche_le": branche.branche_le if branche else None,
            # Pour une connexion par compte : DocuFlow a-t-il ce qu'il faut (identifiants de l'éditeur, clé) ?
            "connexion_prete": entree["connexion"] != "oauth" or oauth.pret(entree["id"]),
        }

    @application.get("/connecteurs")
    def lister_connecteurs(session: Session = Depends(session_de_requete, scope="function")) -> list[dict]:
        branches = {branche.id: branche for branche in session.scalars(select(ConnecteurBranche))}
        return [vue_connecteur(entree, branches.get(entree["id"])) for entree in CATALOGUE]

    @application.get("/connecteurs/{identifiant}")
    def detailler_connecteur(identifiant: str, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        entree = connecteur_ou_404(identifiant)
        branche = session.get(ConnecteurBranche, identifiant)
        outils, erreur = [], None
        if branche and branche.actif:
            try:
                outils = [
                    {"nom": o.nom, "description": o.description, "lecture": o.lecture, "autorise": passerelle.autorise(o, branche)}
                    for o in passerelle.outils_du_serveur(identifiant)
                ]
            except ErreurConnecteur as probleme:
                erreur = str(probleme)
        appels = session.scalars(
            select(AppelConnecteur).where(AppelConnecteur.connecteur == identifiant).order_by(AppelConnecteur.cree_le.desc()).limit(20)
        ).all()
        return {
            **vue_connecteur(entree, branche),
            "outils": outils,
            "erreur": erreur,
            "appels": [
                {"outil": a.outil, "arguments": a.arguments, "statut": a.statut, "detail": a.detail, "duree_ms": a.duree_ms, "cree_le": a.cree_le}
                for a in appels
            ],
        }

    class Branchement(BaseModel):
        auteur: str = Field(min_length=1, max_length=100)

    @application.post("/connecteurs/{identifiant}/branchement")
    def brancher(identifiant: str, demande: Branchement, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        entree = connecteur_ou_404(identifiant)
        if entree["statut"] not in ("disponible", "preversion"):
            raise HTTPException(status.HTTP_409_CONFLICT, f"{entree['nom']} n'est pas encore disponible.")
        try:
            joignable = passerelle.cible(identifiant) is not None
        except ErreurConnecteur as erreur:
            raise HTTPException(status.HTTP_409_CONFLICT, str(erreur)) from erreur
        if not joignable:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Connectez d'abord un compte {entree['nom']}." if entree["connexion"] == "oauth" else f"{entree['nom']} n'est pas configuré sur ce serveur.",
            )
        # On ne branche qu'un serveur qui répond : on lui demande ses outils.
        passerelle.oublier(identifiant)
        try:
            outils = passerelle.outils_du_serveur(identifiant)
        except ErreurConnecteur as erreur:
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(erreur)) from erreur
        branche = session.get(ConnecteurBranche, identifiant) or ConnecteurBranche(id=identifiant, branche_par=demande.auteur)
        branche.actif, branche.branche_par, branche.branche_le = True, demande.auteur, func.now()
        session.add(branche)
        session.flush()
        return {**vue_connecteur(entree, branche), "outils_lecture": [o.nom for o in outils if o.lecture], "outils_ecriture_ignores": [o.nom for o in outils if not o.lecture]}

    @application.delete("/connecteurs/{identifiant}/branchement")
    def debrancher(identifiant: str, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        entree = connecteur_ou_404(identifiant)
        branche = session.get(ConnecteurBranche, identifiant)
        if branche:
            branche.actif = False  # la ligne reste : le journal des appels garde son sens
        oauth.oublier(session, identifiant)  # les jetons d'un compte connecté sont effacés
        passerelle.oublier(identifiant)
        return vue_connecteur(entree, branche)

    @application.post("/connecteurs/{identifiant}/oauth")
    def commencer_oauth(identifiant: str, demande: Branchement, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        entree = connecteur_ou_404(identifiant)
        adresse = adresse_serveur(identifiant)
        if entree["connexion"] != "oauth" or adresse is None or entree["statut"] not in ("disponible", "preversion"):
            raise HTTPException(status.HTTP_409_CONFLICT, f"{entree['nom']} ne se connecte pas par compte.")
        try:
            return {"adresse": oauth.commencer(session, identifiant, adresse, demande.auteur, client_oauth)}
        except oauth.ErreurOAuth as erreur:
            raise HTTPException(status.HTTP_409_CONFLICT, str(erreur)) from erreur

    @application.get("/oauth/retour")
    def retour_oauth(
        state: str = "", code: str = "", error: str = "", session: Session = Depends(session_de_requete, scope="function")
    ) -> RedirectResponse:
        """L'éditeur renvoie ici le navigateur. On termine la connexion, puis on revient à la page Connecteurs."""
        interface = oauth.adresse_retour().split("/api/")[0]
        if error or not code:
            return RedirectResponse(f"{interface}/?oauth=refuse", status.HTTP_303_SEE_OTHER)
        try:
            demande = oauth.terminer(session, state, code, {e["id"]: adresse_serveur(e["id"]) for e in CATALOGUE if adresse_serveur(e["id"])}, client_oauth)
            session.commit()  # les jetons sont gardés même si la vérification qui suit échoue
            passerelle.oublier(demande.connecteur)
            passerelle.outils_du_serveur(demande.connecteur)  # le serveur répond-il avec ce compte ?
        except (oauth.ErreurOAuth, ErreurConnecteur) as erreur:
            # Le détail reste dans le journal du serveur : l'adresse ne transporte ni secret ni message d'erreur.
            logging.getLogger("moteur.api").warning("Connexion OAuth échouée : %s", erreur)
            return RedirectResponse(f"{interface}/?oauth=echec", status.HTTP_303_SEE_OTHER)
        branche = session.get(ConnecteurBranche, demande.connecteur) or ConnecteurBranche(id=demande.connecteur, branche_par=demande.auteur)
        branche.actif, branche.branche_par, branche.branche_le = True, demande.auteur, func.now()
        session.add(branche)
        return RedirectResponse(f"{interface}/?oauth=ok&connecteur={demande.connecteur}", status.HTTP_303_SEE_OTHER)

    class Autorisation(BaseModel):
        autorises: list[str] | None  # None : tous les outils de lecture

    @application.put("/connecteurs/{identifiant}/outils")
    def autoriser(identifiant: str, demande: Autorisation, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        entree = connecteur_ou_404(identifiant)
        branche = session.get(ConnecteurBranche, identifiant)
        if branche is None or not branche.actif:
            raise HTTPException(status.HTTP_409_CONFLICT, "Branchez d'abord ce connecteur.")
        if demande.autorises is not None:
            lecture = {o.nom for o in passerelle.outils_du_serveur(identifiant) if o.lecture}
            refuses = sorted(set(demande.autorises) - lecture)
            if refuses:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Seuls les outils de lecture peuvent être autorisés : {', '.join(refuses)}.")
        branche.outils_autorises = demande.autorises
        session.flush()
        return vue_connecteur(entree, branche)

    @application.post("/agent")
    def parler_a_l_agent(demande: DemandeAgent) -> StreamingResponse:
        def flux() -> Iterator[str]:
            # La session vit le temps de la réponse : l'agent ne fait que lire.
            session = fabrique_session()
            try:
                elements = []
                if demande.auteur:
                    elements.append(f"La personne s'appelle {demande.auteur} : signe les courriels de son nom.")
                if demande.facture_id:
                    facture = session.get(FactureEnBase, demande.facture_id)
                    if facture is not None:
                        elements.append(f"Elle regarde la facture n° {facture.numero_facture} (identifiant {facture.id}, état « {facture.etat} »).")
                contexte = " ".join(elements) or None
                messages = [message.model_dump() for message in demande.messages]
                for evenement in converser(session, messages, contexte, llm_agent, passerelle):
                    yield f"data: {json.dumps(evenement, ensure_ascii=False)}\n\n"
            finally:
                session.rollback()
                session.close()

        return StreamingResponse(flux(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return application
