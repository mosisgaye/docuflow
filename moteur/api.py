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
    GET  /circuit/catalogue           ce que l'éditeur de circuit peut régler (champs, comparaisons, anomalies…)
    GET  /circuit/brouillon           le brouillon du circuit, ou la version en service s'il n'y en a pas
    PUT  /circuit/brouillon           enregistrer le graphe du brouillon (vérifié ; aucune facture n'est touchée)
    DELETE /circuit/brouillon         annuler les modifications : retour à la version en service
    GET  /circuit/differences         ce que le brouillon change, en phrases
    POST /circuit/publier             faire du brouillon la version suivante (les factures en cours gardent la leur)
    POST /circuit/tester              le chemin que prendrait une facture avec le brouillon (rien n'est écrit)
    GET  /circuit/versions            les versions publiées, avec ce que chacune a changé
    GET  /circuit/executions          le chemin réellement suivi par les dernières factures
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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pypdf.errors import PyPdfError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, object_session, sessionmaker

from moteur import config, editeur_circuit
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
from moteur.catalogue_circuit import catalogue
from moteur import acces, cles_api, evenements_sortants, notifications
from moteur.base import Abonnement, CleApi, Livraison, MailRecu, MembreEquipe
from moteur.approbation import NIVEAUX
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
    date_echeance: str | None = None
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


class CodeAcces(BaseModel):
    code: str = Field(min_length=1, max_length=200)


class NouveauMembre(BaseModel):
    nom: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    niveau: str
    auteur: str = Field(min_length=1, max_length=100)


class NouvelleCle(BaseModel):
    nom: str = Field(min_length=1, max_length=100)
    droits: list[str] = Field(min_length=1)
    auteur: str = Field(min_length=1, max_length=100)


class NouvelAbonnement(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    evenements: list[str] = Field(min_length=1)
    auteur: str = Field(min_length=1, max_length=100)


def _publique(facture: FactureEnBase, complete: bool = False) -> dict:
    """La facture vue par l'API publique (/v1). Format stable : on ajoute des champs, on n'en retire jamais."""
    donnees = facture.donnees or {}
    vue = {
        "id": str(facture.id),
        "etat": facture.etat,
        "numero": facture.numero_facture,
        "fournisseur": donnees.get("fournisseur_nom"),
        "siret": facture.fournisseur_siret,
        "date_facture": donnees.get("date_facture"),
        "date_echeance": donnees.get("date_echeance"),
        "total_ht": donnees.get("total_ht"),
        "total_tva": donnees.get("total_tva"),
        "total_ttc": donnees.get("total_ttc"),
        "anomalies": [{"code": a["code"], "message": a["message"]} for a in facture.anomalies],
        "recue_le": facture.cree_le.isoformat(),
    }
    if complete:
        vue["donnees"] = facture.donnees
        vue["journal"] = [{"type": e.type, "etat": e.etat, "auteur": e.auteur, "le": e.cree_le.isoformat()} for e in facture.evenements]
    return vue


def _vue_cle(cle: CleApi) -> dict:
    return {
        "id": str(cle.id), "nom": cle.nom, "debut": f"dfk_{cle.prefixe}_…", "droits": cle.droits, "creee_par": cle.creee_par,
        "creee_le": cle.creee_le.isoformat(), "utilisee_le": cle.utilisee_le.isoformat() if cle.utilisee_le else None,
        "revoquee_le": cle.revoquee_le.isoformat() if cle.revoquee_le else None,
    }


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
        "date_echeance": donnees.get("date_echeance"),
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
    tentatives = acces.Tentatives()
    # Toutes adresses confondues : derrière Vercel, l'adresse vue peut être partagée ou falsifiée.
    tentatives_toutes = acces.Tentatives(maximum=acces.ESSAIS_MAX_TOTAL)

    @application.middleware("http")
    async def code_d_acces(requete: Request, suite):
        # Sans code configuré (développement), tout passe. Sinon, le cookie du code est exigé.
        if not acces.autorise(requete.url.path, requete.cookies.get(acces.COOKIE)):
            return JSONResponse({"detail": "Code d’accès requis.", "acces": True}, status_code=status.HTTP_401_UNAUTHORIZED)
        return await suite(requete)

    def adresse_client(requete: Request) -> str:
        # Vercel → Cloudflare → tunnel : le visiteur est le premier de X-Forwarded-For (posé par Vercel),
        # sinon CF-Connecting-IP (accès direct), sinon l'adresse de la connexion.
        premier = requete.headers.get("x-forwarded-for", "").split(",")[0].strip()
        return premier or requete.headers.get("cf-connecting-ip") or (requete.client.host if requete.client else "inconnue")

    @application.get("/acces")
    def etat_acces(requete: Request) -> dict:
        requis = bool(acces.code())
        return {"requis": requis, "ouvert": acces.autorise("/", requete.cookies.get(acces.COOKIE))}

    @application.post("/acces")
    def entrer(demande: CodeAcces, requete: Request, reponse: Response) -> dict:
        if not acces.code():
            return {"requis": False, "ouvert": True}
        adresse = adresse_client(requete)
        if tentatives.bloquee(adresse) or tentatives_toutes.bloquee("*"):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Trop d’essais. Réessayez dans un quart d’heure.")
        if not acces.code_correct(demande.code):
            tentatives.noter_echec(adresse)
            tentatives_toutes.noter_echec("*")
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Code incorrect.")
        securise = requete.url.scheme == "https" or requete.headers.get("x-forwarded-proto") == "https"
        reponse.set_cookie(
            acces.COOKIE, acces.jeton(acces.code()), max_age=acces.DUREE_COOKIE_S, httponly=True, secure=securise, samesite="lax", path="/"
        )
        return {"requis": True, "ouvert": True}

    @application.delete("/acces")
    def sortir(reponse: Response) -> dict:
        reponse.delete_cookie(acces.COOKIE, path="/")
        return {"requis": bool(acces.code()), "ouvert": not acces.code()}

    def refuser_si_quota(session: Session) -> None:
        if acces.quota_atteint(session):
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"Limite de la démonstration atteinte : {acces.depots_par_jour()} factures par jour. Réessayez demain.",
            )

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

    def fichier_en_pdf(fichier: UploadFile) -> tuple[bytes, str]:
        """Le fichier déposé, vérifié, et mis en PDF si c'est une photo."""
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
        return contenu, nom

    @application.post("/factures", response_model=FactureDeposee, status_code=status.HTTP_202_ACCEPTED)
    def deposer(reponse: Response, fichier: UploadFile = File(...), session: Session = Depends(session_de_requete, scope="function")) -> dict:
        refuser_si_quota(session)
        contenu, nom = fichier_en_pdf(fichier)
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
        refuser_si_quota(session)  # le Worker rejette alors le mail : l'expéditeur est prévenu
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

    @application.get("/circuit/catalogue")
    def catalogue_du_circuit() -> dict:
        return catalogue()

    @application.get("/circuit/brouillon")
    def lire_brouillon(session: Session = Depends(session_de_requete, scope="function")) -> dict:
        return editeur_circuit.lire(session)

    class Brouillon(BaseModel):
        auteur: str = Field(min_length=1, max_length=100)
        graphe: dict  # les étapes et les liens dessinés (moteur/graphe_circuit.py), vérifiés par le moteur
        relances: dict | None = None

    @application.put("/circuit/brouillon")
    def enregistrer_brouillon(demande: Brouillon, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        if not demande.auteur.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Indiquez votre nom : chaque modification est inscrite à un nom.")
        try:
            return editeur_circuit.enregistrer(session, demande.graphe, demande.relances, demande.auteur.strip())
        except editeur_circuit.BrouillonInvalide as erreur:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(erreur)) from erreur

    @application.delete("/circuit/brouillon")
    def annuler_brouillon(session: Session = Depends(session_de_requete, scope="function")) -> dict:
        return editeur_circuit.annuler(session)

    @application.get("/circuit/differences")
    def differences_du_brouillon(session: Session = Depends(session_de_requete, scope="function")) -> dict:
        return editeur_circuit.differences(session)

    class TestCircuit(BaseModel):
        facture_id: uuid.UUID

    @application.post("/circuit/tester")
    def tester_circuit(demande: TestCircuit, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        facture = session.get(FactureEnBase, demande.facture_id)
        if facture is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Facture introuvable.")
        try:
            return editeur_circuit.tester(session, facture)
        except editeur_circuit.TestImpossible as erreur:
            raise HTTPException(status.HTTP_409_CONFLICT, str(erreur)) from erreur

    @application.get("/circuit/versions")
    def versions_du_circuit(session: Session = Depends(session_de_requete, scope="function")) -> dict:
        return {"versions": editeur_circuit.versions(session)}

    @application.get("/circuit/executions")
    def executions_du_circuit(limite: int = 20, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        return {"executions": editeur_circuit.executions(session, limite)}

    class PublicationCircuit(BaseModel):
        auteur: str = Field(min_length=1, max_length=100)

    @application.post("/circuit/publier", status_code=status.HTTP_201_CREATED)
    def publier_circuit(demande: PublicationCircuit, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        if not demande.auteur.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Indiquez votre nom : chaque publication est inscrite à un nom.")
        try:
            version = editeur_circuit.publier_brouillon(session, demande.auteur.strip())
        except editeur_circuit.PublicationImpossible as erreur:
            raise HTTPException(status.HTTP_409_CONFLICT, str(erreur)) from erreur
        logging.getLogger("moteur.api").info("Circuit publié : version %s par %s", version.version, version.publie_par)
        return {"version": version.version, "publie_par": version.publie_par, "changements": version.changements}

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
<title>{titre} | Verifac</title><style>
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

    # ───────── API publique (/v1) : pour les autres logiciels, avec une clé ─────────

    def acces_cle(droit: str) -> Callable:
        def verifier(authorization: str | None = Header(default=None), session: Session = Depends(session_de_requete, scope="function")) -> CleApi:
            try:
                return cles_api.verifier(session, authorization, droit)
            except cles_api.AccesRefuse as erreur:
                entetes = {"WWW-Authenticate": "Bearer"} if erreur.code == 401 else None
                raise HTTPException(erreur.code, str(erreur), headers=entetes) from erreur

        return verifier

    @application.get("/v1/factures", tags=["API publique"])
    def v1_lister(
        etat: Etat | None = None, limite: int = 50, cle: CleApi = Depends(acces_cle("factures:lire")),
        session: Session = Depends(session_de_requete, scope="function"),
    ) -> dict:
        """Les factures, des plus récentes aux plus anciennes (200 au plus), filtrables par état."""
        requete = select(FactureEnBase).order_by(FactureEnBase.cree_le.desc()).limit(max(1, min(limite, 200)))
        if etat is not None:
            requete = requete.where(FactureEnBase.etat == etat.value)
        return {"factures": [_publique(facture) for facture in session.scalars(requete)]}

    @application.get("/v1/factures/{facture_id}", tags=["API publique"])
    def v1_detailler(
        facture_id: uuid.UUID, cle: CleApi = Depends(acces_cle("factures:lire")), session: Session = Depends(session_de_requete, scope="function")
    ) -> dict:
        """Une facture, avec toutes ses données lues et son journal."""
        return _publique(facture_ou_404(session, facture_id), complete=True)

    @application.post("/v1/factures", tags=["API publique"], status_code=status.HTTP_202_ACCEPTED)
    def v1_deposer(
        reponse: Response, fichier: UploadFile = File(...), cle: CleApi = Depends(acces_cle("factures:deposer")),
        session: Session = Depends(session_de_requete, scope="function"),
    ) -> dict:
        """Dépose une facture (PDF ou photo). Elle est lue dans les secondes qui suivent : suivez son état,
        ou abonnez-vous à « facture.a_valider »."""
        refuser_si_quota(session)
        contenu, nom = fichier_en_pdf(fichier)
        resultat = recevoir(session, contenu, nom, {"source": "api", "cle_api": f"dfk_{cle.prefixe}", "cle_nom": cle.nom})
        if resultat.deja_vue:
            reponse.status_code = status.HTTP_200_OK
        return {**_publique(resultat.facture), "deja_vue": resultat.deja_vue}

    # ───────── Réglages : l'équipe qui approuve, et la réception des factures ─────────

    def vue_membre(membre: MembreEquipe) -> dict:
        return {"id": str(membre.id), "nom": membre.nom, "email": membre.email, "niveau": membre.niveau, "cree_par": membre.cree_par, "cree_le": membre.cree_le.isoformat()}

    @application.get("/reglages/equipe")
    def lire_equipe(session: Session = Depends(session_de_requete, scope="function")) -> dict:
        membres = session.scalars(select(MembreEquipe).order_by(MembreEquipe.cree_le))
        return {"niveaux": {niveau: LIBELLES[niveau] for niveau in NIVEAUX}, "membres": [vue_membre(m) for m in membres]}

    @application.post("/reglages/equipe", status_code=status.HTTP_201_CREATED)
    def ajouter_membre(demande: NouveauMembre, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        if demande.niveau not in NIVEAUX:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Rôle inconnu.")
        email = demande.email.strip().lower()
        if session.scalar(select(MembreEquipe).where(MembreEquipe.email == email, MembreEquipe.niveau == demande.niveau)):
            raise HTTPException(status.HTTP_409_CONFLICT, f"{email} a déjà ce rôle.")
        membre = MembreEquipe(nom=demande.nom.strip(), email=email, niveau=demande.niveau, cree_par=demande.auteur.strip())
        session.add(membre)
        session.flush()
        session.refresh(membre)
        return vue_membre(membre)

    @application.delete("/reglages/equipe/{membre_id}")
    def retirer_membre(membre_id: uuid.UUID, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        membre = session.get(MembreEquipe, membre_id)
        if membre is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Personne introuvable.")
        session.delete(membre)
        return {"id": str(membre_id)}

    @application.get("/reglages/reception")
    def lire_reception(session: Session = Depends(session_de_requete, scope="function")) -> dict:
        """L'adresse où envoyer les factures, et les derniers mails reçus (avec le texte de ceux sans facture)."""
        mails = session.scalars(select(MailRecu).order_by(MailRecu.recu_le.desc()).limit(15))
        return {
            "adresse": config.lire("RECEPTION_ADRESSE", "depot@factures.moussagaye.com"),
            "active": bool(cles_mail),
            "mails": [
                {
                    "id": str(m.id), "expediteur": m.expediteur, "objet": m.objet, "statut": m.statut, "recu_le": m.recu_le.isoformat(),
                    "factures": sum(1 for piece in m.pieces if piece.get("resultat") in ("facture", "deja_recue")), "texte": m.texte,
                }
                for m in mails
            ],
        }

    # ───────── Gestion des clés et des abonnements (écran « Accès développeurs ») ─────────

    @application.get("/cles-api")
    def lister_cles(session: Session = Depends(session_de_requete, scope="function")) -> dict:
        cles = session.scalars(select(CleApi).order_by(CleApi.creee_le.desc()))
        return {"droits": cles_api.DROITS, "cles": [_vue_cle(cle) for cle in cles]}

    @application.post("/cles-api", status_code=status.HTTP_201_CREATED)
    def creer_cle(demande: NouvelleCle, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        try:
            creee = cles_api.creer(session, demande.nom.strip(), demande.droits, demande.auteur.strip())
        except ValueError as erreur:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(erreur)) from erreur
        session.refresh(creee.cle)
        return {**_vue_cle(creee.cle), "cle": creee.secret_complet}  # montrée cette fois-ci seulement

    @application.delete("/cles-api/{cle_id}")
    def revoquer_cle(cle_id: uuid.UUID, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        cle = session.get(CleApi, cle_id)
        if cle is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Clé introuvable.")
        cles_api.revoquer(session, cle)
        return _vue_cle(cle)

    def vue_abonnement(session: Session, abonnement: Abonnement) -> dict:
        livraisons = session.scalars(
            select(Livraison).where(Livraison.abonnement_id == abonnement.id).order_by(Livraison.cree_le.desc()).limit(10)
        )
        return {
            "id": str(abonnement.id), "url": abonnement.url, "evenements": abonnement.evenements, "actif": abonnement.actif,
            "cree_par": abonnement.cree_par, "cree_le": abonnement.cree_le.isoformat(),
            "livraisons": [
                {
                    "id": str(l.id), "evenement": l.evenement, "etat": l.etat, "tentatives": l.tentatives, "reponse": l.derniere_reponse,
                    "cree_le": l.cree_le.isoformat(), "prochain_essai_le": l.prochain_essai_le.isoformat() if l.etat == "en_attente" else None,
                }
                for l in livraisons
            ],
        }

    @application.get("/abonnements")
    def lister_abonnements(session: Session = Depends(session_de_requete, scope="function")) -> dict:
        abonnements = session.scalars(select(Abonnement).where(Abonnement.actif).order_by(Abonnement.cree_le.desc()))
        return {"evenements": evenements_sortants.EVENEMENTS, "abonnements": [vue_abonnement(session, a) for a in abonnements]}

    @application.post("/abonnements", status_code=status.HTTP_201_CREATED)
    def creer_abonnement(demande: NouvelAbonnement, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        try:
            abonnement, secret = evenements_sortants.creer_abonnement(session, demande.url.strip(), demande.evenements, demande.auteur.strip())
        except evenements_sortants.AbonnementRefuse as erreur:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(erreur)) from erreur
        session.refresh(abonnement)
        return {**vue_abonnement(session, abonnement), "secret": secret}  # montré cette fois-ci seulement

    @application.post("/abonnements/{abonnement_id}/essai", status_code=status.HTTP_202_ACCEPTED)
    def essayer_abonnement(abonnement_id: uuid.UUID, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        """Envoie un événement d'essai, pour vérifier l'adresse et la signature sans toucher à une facture."""
        abonnement = session.get(Abonnement, abonnement_id)
        if abonnement is None or not abonnement.actif:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Abonnement introuvable.")
        session.add(Livraison(abonnement_id=abonnement.id, evenement="essai", charge={"evenement": "essai", "message": "Événement d'essai envoyé depuis Verifac."}))
        session.flush()
        return vue_abonnement(session, abonnement)

    @application.delete("/abonnements/{abonnement_id}")
    def arreter_abonnement(abonnement_id: uuid.UUID, session: Session = Depends(session_de_requete, scope="function")) -> dict:
        """Désactive l'abonnement : plus rien ne part. L'historique des livraisons est gardé."""
        abonnement = session.get(Abonnement, abonnement_id)
        if abonnement is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Abonnement introuvable.")
        abonnement.actif = False
        session.flush()
        return {"id": str(abonnement.id), "actif": False}

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
