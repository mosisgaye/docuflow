"""Le workflow d'une facture : de la réception à la validation.

    recue ──> extraite ──> a_valider ──> validee ──> exportee
      │           │            │
      │           └──> en_anomalie ──> rejetee
      └──> echec (nouvel essai possible)

Chaque changement d'état passe par _passer(), qui refuse les transitions
interdites et écrit une ligne dans le journal.

Deux temps :
- recevoir()          enregistre la facture et sa tâche de lecture, tout de suite ;
- lire_et_controler()  fait la lecture et les contrôles, appelée par le travailleur.
traiter() enchaîne les deux d'un coup, pour les outils et les tests.
"""

import hashlib
import pathlib
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from moteur.base import Etat, EtatTache, Evenement, FactureEnBase, Tache
from moteur.controles import Anomalie, Gravite, controler, est_validable
from moteur.export import ErreurExport, ecriture, en_csv, en_json, envoyer_au_logiciel, nom_fichier
from moteur.extraction_llm import ErreurExtraction, ResultatExtraction, extraire
from moteur.consignes import enregistrer as enregistrer_consigne
from moteur.facturx import LECTEUR as LECTEUR_FACTURX
from moteur.facturx import FacturXInvalide, lire_facturx
from moteur.lecture_pdf import lire_pdf
from moteur.modeles import Facture
from moteur.odoo import ErreurOdoo, Odoo

MOTEUR = "moteur"

TRANSITIONS: dict[Etat, set[Etat]] = {
    Etat.RECUE: {Etat.EXTRAITE, Etat.ECHEC},
    Etat.ECHEC: {Etat.EXTRAITE, Etat.ECHEC},
    Etat.EXTRAITE: {Etat.A_VALIDER, Etat.EN_ANOMALIE},
    Etat.A_VALIDER: {Etat.VALIDEE, Etat.REJETEE},
    Etat.EN_ANOMALIE: {Etat.REJETEE},
    Etat.VALIDEE: {Etat.EXPORTEE},
    Etat.REJETEE: set(),
    Etat.EXPORTEE: set(),
}


class TransitionInterdite(Exception):
    """On a demandé un changement d'état que le workflow n'autorise pas."""


class FactureIntrouvable(Exception):
    pass


@dataclass(frozen=True)
class ResultatTraitement:
    facture: FactureEnBase
    deja_vue: bool  # vrai si ce fichier avait déjà été reçu : rien n'a été refait
    tache: Tache | None = None  # la tâche de lecture créée, s'il y en a une


def _journaliser(session: Session, facture: FactureEnBase, type_evenement: str, auteur: str, detail: dict | None = None) -> None:
    session.add(
        Evenement(
            facture=facture,
            rang=len(facture.evenements) + 1,
            type=type_evenement,
            etat=facture.etat,
            auteur=auteur,
            detail=detail or {},
        )
    )
    session.flush()


def _passer(session: Session, facture: FactureEnBase, etat: Etat, type_evenement: str, auteur: str, detail: dict | None = None) -> None:
    if etat not in TRANSITIONS[Etat(facture.etat)]:
        raise TransitionInterdite(f"Passage interdit de « {facture.etat} » à « {etat.value} ».")
    facture.etat = etat.value
    _journaliser(session, facture, type_evenement, auteur, detail)


def _doublon_metier(session: Session, facture: FactureEnBase) -> list[Anomalie]:
    """Même fournisseur et même numéro qu'une autre facture non rejetée."""
    if not facture.fournisseur_siret or not facture.numero_facture:
        return []
    # Deux dépôts simultanés de la même facture se feraient passer chacun pour l'original.
    # Ce verrou, propre au couple fournisseur et numéro, les fait passer l'un après l'autre :
    # le second attend que le premier soit enregistré, puis le voit.
    cle = f"{facture.fournisseur_siret}|{facture.numero_facture}"
    session.execute(text("select pg_advisory_xact_lock(hashtextextended(:cle, 0))"), {"cle": cle})
    autre = session.scalars(
        select(FactureEnBase).where(
            FactureEnBase.fournisseur_siret == facture.fournisseur_siret,
            FactureEnBase.numero_facture == facture.numero_facture,
            FactureEnBase.id != facture.id,
            FactureEnBase.etat != Etat.REJETEE.value,
        )
    ).first()
    if autre is None:
        return []
    return [
        Anomalie(
            "DOUBLON_FACTURE",
            Gravite.BLOQUANTE,
            f"La facture n° {facture.numero_facture} de ce fournisseur existe déjà (fichier « {autre.nom_fichier} »).",
            "numero_facture",
        )
    ]


def lire_et_controler(
    session: Session,
    facture: FactureEnBase,
    contenu: bytes,
    extracteur: Callable[[str], ResultatExtraction] = extraire,
    aujourd_hui: date | None = None,
    echec_si_passagere: bool = True,
    odoo: Odoo | None = None,
) -> None:
    """Lit la facture (Factur-X ou IA) puis la contrôle.

    Avec odoo, le fournisseur est aussi cherché dans le logiciel du client : inconnu, il donne
    un avertissement ; si Odoo ne répond pas, la lecture continue et le journal le dit.

    Avec echec_si_passagere=False, une panne passagère de l'IA n'est pas traitée ici :
    ErreurExtraction est relancée, la facture reste « reçue », et c'est la file de tâches
    qui décide de retenter plus tard (voir moteur/travailleur.py).
    """
    # 1. Facture électronique Factur-X : les données sont dans le XML joint, pas besoin d'IA.
    donnees, detail = None, {}
    debut = time.monotonic()
    try:
        donnees = lire_facturx(contenu)
    except FacturXInvalide as erreur:
        # XML présent mais mauvais : on le signale, et on se rabat sur la lecture par l'IA.
        _journaliser(session, facture, "FACTURX_ILLISIBLE", MOTEUR, {"raison": str(erreur)})
    if donnees is not None:
        detail = {"source": "factur-x", "lecteur": LECTEUR_FACTURX, "duree_s": round(time.monotonic() - debut, 4)}

    # 2. Sinon, PDF ordinaire : on lit son texte et on le confie à l'IA.
    if donnees is None:
        lu = lire_pdf(contenu)
        if not lu.a_du_texte:
            _passer(session, facture, Etat.ECHEC, "LECTURE_IMPOSSIBLE", MOTEUR, {"raison": "Le PDF ne contient pas de texte (scan ou photo)."})
            return
        try:
            resultat = extracteur(lu.texte)
        except ErreurExtraction as erreur:
            if erreur.passagere and not echec_si_passagere:
                raise
            _passer(session, facture, Etat.ECHEC, "EXTRACTION_ECHOUEE", MOTEUR, {"raison": str(erreur)})
            return
        donnees = resultat.facture
        detail = {"source": "ia", "fournisseur_llm": resultat.fournisseur, "modele": resultat.modele, "duree_s": round(resultat.duree_s, 2)}
        if resultat.consigne is not None:
            detail["consigne"] = enregistrer_consigne(session, resultat.consigne)
        if resultat.tentatives > 1:
            detail["tentatives"] = resultat.tentatives

    facture.donnees = donnees.model_dump(mode="json")
    facture.fournisseur_siret = donnees.fournisseur_siret
    facture.numero_facture = donnees.numero_facture
    _passer(session, facture, Etat.EXTRAITE, "EXTRACTION", MOTEUR, detail)

    anomalies = [*controler(donnees, aujourd_hui), *_doublon_metier(session, facture), *_fournisseur_dans_odoo(session, facture, donnees, odoo)]
    facture.anomalies = [asdict(anomalie) for anomalie in anomalies]
    etat = Etat.A_VALIDER if est_validable(anomalies) else Etat.EN_ANOMALIE
    _passer(session, facture, etat, "CONTROLE", MOTEUR, {"anomalies": [anomalie.code for anomalie in anomalies]})


def _fournisseur_dans_odoo(session: Session, facture: FactureEnBase, donnees: Facture, odoo: Odoo | None) -> list[Anomalie]:
    if odoo is None or not (donnees.fournisseur_siret or donnees.fournisseur_tva):
        return []
    try:
        fournisseur = odoo.trouver_fournisseur(donnees.fournisseur_siret, donnees.fournisseur_tva)
    except ErreurOdoo as erreur:
        # Odoo indisponible n'empêche pas de lire la facture : on le note, sans inventer d'anomalie.
        _journaliser(session, facture, "ODOO_INDISPONIBLE", MOTEUR, {"raison": str(erreur)})
        return []
    if fournisseur is None:
        _journaliser(session, facture, "FOURNISSEUR_ODOO", MOTEUR, {"trouve": False})
        return [
            Anomalie(
                "FOURNISSEUR_INCONNU",
                Gravite.AVERTISSEMENT,
                f"Le fournisseur « {donnees.fournisseur_nom or donnees.fournisseur_siret} » n'existe pas dans Odoo : il faudra le créer avant l'envoi en comptabilité.",
                "fournisseur_nom",
            )
        ]
    _journaliser(
        session, facture, "FOURNISSEUR_ODOO", MOTEUR,
        {"trouve": True, "id": fournisseur.id, "nom": fournisseur.nom, "adresse": odoo.adresse_fiche("res.partner", fournisseur.id)},
    )
    return []


def _mettre_en_file(session: Session, facture: FactureEnBase) -> Tache | None:
    """Crée la tâche de lecture de la facture, sauf s'il y en a déjà une en attente."""
    tache_id = session.execute(
        insert(Tache)
        .values(id=uuid.uuid4(), facture_id=facture.id, etat=EtatTache.EN_ATTENTE.value)
        # La condition est écrite en toutes lettres, comme dans la définition de l'index partiel :
        # passée en paramètre, PostgreSQL ne retrouve plus l'index une fois la requête préparée.
        .on_conflict_do_nothing(index_elements=[Tache.facture_id], index_where=text("etat = 'en_attente'"))
        .returning(Tache.id)
    ).scalar_one_or_none()
    return session.get(Tache, tache_id) if tache_id else None


def ranger_fichier(dossier: pathlib.Path, contenu: bytes) -> pathlib.Path:
    """Écrit le PDF dans le dossier des fichiers reçus, sous son empreinte. À faire AVANT recevoir() :
    le travailleur ne doit jamais trouver une tâche dont le fichier n'existe pas encore."""
    chemin = dossier / f"{hashlib.sha256(contenu).hexdigest()}.pdf"
    if not chemin.exists():
        provisoire = chemin.with_suffix(f".{uuid.uuid4().hex}.tmp")
        provisoire.write_bytes(contenu)
        provisoire.replace(chemin)  # le fichier apparaît d'un coup, jamais à moitié écrit
    return chemin


def recevoir(session: Session, contenu: bytes, nom_fichier: str, origine: dict | None = None) -> ResultatTraitement:
    """Enregistre le PDF reçu et sa tâche de lecture. Ne lit rien : c'est le travail du travailleur.

    La facture et sa tâche sont créées dans la même transaction : l'une n'existe jamais sans l'autre.
    Idempotent : le même fichier envoyé deux fois ne crée qu'une facture. Seule une facture
    en échec est remise en file.
    origine : d'où vient le fichier quand ce n'est pas un dépôt à l'écran (par exemple un mail),
    recopiée dans le journal.
    """
    origine = origine or {}
    empreinte = hashlib.sha256(contenu).hexdigest()
    # On réserve l'empreinte d'abord. Si le même fichier arrive deux fois en même temps,
    # la base fait attendre le second dépôt jusqu'à ce que le premier soit enregistré,
    # au lieu de laisser les deux insérer et l'un des deux échouer.
    nouvel_id = session.execute(
        insert(FactureEnBase)
        .values(id=uuid.uuid4(), empreinte=empreinte, nom_fichier=nom_fichier, etat=Etat.RECUE.value, anomalies=[])
        .on_conflict_do_nothing(index_elements=[FactureEnBase.empreinte])
        .returning(FactureEnBase.id)
    ).scalar_one_or_none()

    if nouvel_id is None:
        # Fichier déjà connu. Le verrou de ligne évite que deux renvois simultanés
        # d'une facture en échec la remettent chacun en file.
        existante = session.scalars(select(FactureEnBase).where(FactureEnBase.empreinte == empreinte).with_for_update()).one()
        if existante.etat == Etat.ECHEC.value:
            _journaliser(session, existante, "NOUVEL_ESSAI", MOTEUR, {"nom_fichier": nom_fichier, **origine})
            return ResultatTraitement(existante, deja_vue=False, tache=_mettre_en_file(session, existante))
        _journaliser(session, existante, "DOUBLON_FICHIER", MOTEUR, {"nom_fichier": nom_fichier, **origine})
        return ResultatTraitement(existante, deja_vue=True)

    facture = session.get(FactureEnBase, nouvel_id)
    _journaliser(session, facture, "RECEPTION", MOTEUR, {"nom_fichier": nom_fichier, "taille_octets": len(contenu), **origine})
    return ResultatTraitement(facture, deja_vue=False, tache=_mettre_en_file(session, facture))


def traiter(
    session: Session,
    contenu: bytes,
    nom_fichier: str,
    extracteur: Callable[[str], ResultatExtraction] = extraire,
    aujourd_hui: date | None = None,
    odoo: Odoo | None = None,
) -> ResultatTraitement:
    """Reçoit un PDF et le lit tout de suite : utilisé par les outils et les tests.

    En service, l'API appelle recevoir() et le travailleur fait la lecture.
    """
    resultat = recevoir(session, contenu, nom_fichier)
    if resultat.tache is not None:
        resultat.tache.tentatives += 1
        lire_et_controler(session, resultat.facture, contenu, extracteur, aujourd_hui, odoo=odoo)
        resultat.tache.etat = (EtatTache.ABANDONNEE if resultat.facture.etat == Etat.ECHEC.value else EtatTache.TERMINEE).value
        session.flush()
    return resultat


def _charger(session: Session, facture_id: uuid.UUID) -> FactureEnBase:
    facture = session.get(FactureEnBase, facture_id)
    if facture is None:
        raise FactureIntrouvable(str(facture_id))
    return facture


def valider(session: Session, facture_id: uuid.UUID, auteur: str) -> FactureEnBase:
    """Validation par une personne. Impossible si un contrôle bloquant a échoué."""
    facture = _charger(session, facture_id)
    _passer(session, facture, Etat.VALIDEE, "VALIDATION", auteur)
    return facture


def rejeter(session: Session, facture_id: uuid.UUID, auteur: str, motif: str) -> FactureEnBase:
    facture = _charger(session, facture_id)
    _passer(session, facture, Etat.REJETEE, "REJET", auteur, {"motif": motif})
    return facture


def exporter(
    session: Session,
    facture_id: uuid.UUID,
    auteur: str,
    dossier: pathlib.Path,
    client=None,
    odoo: Odoo | None = None,
    dossier_fichiers: pathlib.Path | None = None,
) -> FactureEnBase:
    """Envoie une facture validée à la comptabilité. Sans effet si elle est déjà exportée.

    Le fichier CSV de l'écriture est toujours produit. Avec odoo, la facture fournisseur est
    créée dans Odoo, PDF joint ; sinon, l'écriture part vers EXPORT_WEBHOOK_URL s'il est réglé.

    En cas d'échec, la facture reste « validée », l'échec est inscrit au journal et
    ErreurExport est levée : il suffit de relancer l'export.
    """
    facture = session.get(FactureEnBase, facture_id, with_for_update=True)  # deux exports simultanés passent l'un après l'autre
    if facture is None:
        raise FactureIntrouvable(str(facture_id))
    if facture.etat == Etat.EXPORTEE.value:
        return facture
    if facture.etat != Etat.VALIDEE.value:
        raise TransitionInterdite(f"Seule une facture validée peut être exportée (celle-ci est « {facture.etat} »).")
    try:
        donnees = Facture.model_validate(facture.donnees)
        lignes = ecriture(donnees)
        dossier.mkdir(parents=True, exist_ok=True)
        chemin = dossier / nom_fichier(donnees, str(facture.id))
        provisoire = chemin.with_suffix(".tmp")
        provisoire.write_text(en_csv(lignes), encoding="utf-8", newline="")
        provisoire.replace(chemin)  # le fichier apparaît d'un coup, jamais à moitié écrit
        if odoo is not None:
            pdf = (dossier_fichiers / f"{facture.empreinte}.pdf") if dossier_fichiers else None
            envoi = odoo.envoyer_facture(donnees, pdf.read_bytes() if pdf and pdf.exists() else None, facture.nom_fichier)
        else:
            envoi = envoyer_au_logiciel(str(facture.id), lignes, client)
    except ErreurExport as erreur:
        _journaliser(session, facture, "EXPORT_ECHOUE", auteur, {"raison": str(erreur)})
        raise
    _passer(session, facture, Etat.EXPORTEE, "EXPORT", auteur, {"fichier": chemin.name, "ecriture": en_json(lignes), "logiciel": envoi})
    return facture
