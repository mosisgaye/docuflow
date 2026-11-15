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
    POST /agent                       parler à l'assistant (réponse envoyée au fil de l'eau)
    GET  /statistiques                les chiffres du tableau de bord
    GET  /sante                       l'API et la base répondent-elles ? où en est la file de tâches ?

Lancement : uv run uvicorn moteur.api:creer_application --factory --port 8010
La lecture des factures est faite par un processus à part : uv run python -m moteur.travailleur
"""

import json
import pathlib
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from pypdf.errors import PyPdfError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from moteur import config
from moteur.agent import converser, flux_openai
from moteur.agent import version_consigne as consigne_assistant
from moteur.consignes import enregistrer as enregistrer_consigne
from moteur.base import Etat, EtatTache, Evenement, FactureEnBase, Tache, creer_moteur, verifier_schema
from moteur.extraction_llm import ResultatExtraction, extraire
from moteur.export import ErreurEnvoi, ErreurExport
from moteur.lecture_pdf import lire_pdf
from moteur.odoo import Odoo, depuis_configuration
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
    return {
        **_resume(facture),
        "donnees": facture.donnees,
        "anomalies": facture.anomalies,
        "evenements": [EvenementSortie.model_validate(evenement) for evenement in facture.evenements],
    }


def creer_application(
    fabrique_session: Callable[[], Session] | None = None,
    extracteur: Callable[[str], ResultatExtraction] = extraire,
    dossier_fichiers: pathlib.Path | None = None,
    llm_agent: Callable = flux_openai,
    dossier_exports: pathlib.Path | None = None,
    client_export=None,
    traiter_tout_de_suite: bool = False,
    cles_mail: list | None = None,
    odoo: Odoo | None | str = "configuration",
) -> FastAPI:
    """Construit l'application. Les paramètres servent aux tests ; en service, tout vient de .env.

    traiter_tout_de_suite : lire la facture pendant la requête au lieu de la confier au travailleur.
    Utile aux tests et aux démonstrations sans travailleur ; jamais en service.
    cles_mail : clés publiques des adaptateurs de messagerie. Sans elles, la réception par mail est fermée.
    odoo : le connecteur Odoo ; par défaut, celui de la configuration (None s'il n'y a pas de clé).
    """
    if fabrique_session is None:
        moteur_base = creer_moteur()
        verifier_schema(moteur_base)
        fabrique_session = sessionmaker(moteur_base)
    dossier = dossier_fichiers or config.dossier_fichiers()
    dossier.mkdir(parents=True, exist_ok=True)
    cles_mail = cles_mail if cles_mail is not None else cles_publiques(config.lire("RECEPTION_MAIL_CLES_PUBLIQUES", ""))
    odoo = depuis_configuration() if odoo == "configuration" else odoo
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
        if not contenu.startswith(b"%PDF-"):
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Seuls les fichiers PDF sont acceptés.")
        try:
            lire_pdf(contenu)  # vérifie que le PDF s'ouvre
        except PyPdfError as erreur:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ce fichier PDF est illisible.") from erreur
        # Le fichier est écrit AVANT la tâche : le travailleur ne peut jamais chercher un fichier absent.
        ranger_fichier(dossier, contenu)
        nom = pathlib.Path(fichier.filename or "facture.pdf").name
        if traiter_tout_de_suite:
            resultat = traiter(session, contenu, nom, extracteur, odoo=odoo)
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
                for evenement in converser(session, messages, contexte, llm_agent):
                    yield f"data: {json.dumps(evenement, ensure_ascii=False)}\n\n"
            finally:
                session.rollback()
                session.close()

        return StreamingResponse(flux(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return application
