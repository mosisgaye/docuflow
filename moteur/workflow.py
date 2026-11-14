"""Le workflow d'une facture : de la réception à la validation.

    recue ──> extraite ──> a_valider ──> validee ──> exportee
      │           │            │
      │           └──> en_anomalie ──> rejetee
      └──> echec (nouvel essai possible)

Chaque changement d'état passe par _passer(), qui refuse les transitions
interdites et écrit une ligne dans le journal.
"""

import pathlib
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from moteur.base import Etat, Evenement, FactureEnBase
from moteur.controles import Anomalie, Gravite, controler, est_validable
from moteur.export import ErreurExport, ecriture, en_csv, en_json, envoyer_au_logiciel, nom_fichier
from moteur.extraction_llm import ErreurExtraction, ResultatExtraction, extraire
from moteur.consignes import enregistrer as enregistrer_consigne
from moteur.facturx import LECTEUR as LECTEUR_FACTURX
from moteur.facturx import FacturXInvalide, lire_facturx
from moteur.lecture_pdf import lire_pdf
from moteur.modeles import Facture

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


def _extraire_et_controler(
    session: Session,
    facture: FactureEnBase,
    contenu: bytes,
    extracteur: Callable[[str], ResultatExtraction],
    aujourd_hui: date | None,
) -> None:
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

    anomalies = [*controler(donnees, aujourd_hui), *_doublon_metier(session, facture)]
    facture.anomalies = [asdict(anomalie) for anomalie in anomalies]
    etat = Etat.A_VALIDER if est_validable(anomalies) else Etat.EN_ANOMALIE
    _passer(session, facture, etat, "CONTROLE", MOTEUR, {"anomalies": [anomalie.code for anomalie in anomalies]})


def traiter(
    session: Session,
    contenu: bytes,
    nom_fichier: str,
    extracteur: Callable[[str], ResultatExtraction] = extraire,
    aujourd_hui: date | None = None,
) -> ResultatTraitement:
    """Reçoit un PDF et le mène jusqu'à « à valider » ou « en anomalie ».

    Idempotent : le même fichier envoyé deux fois ne crée qu'une facture
    et n'appelle le LLM qu'une fois. Seule une facture en échec est retentée.
    """
    empreinte = lire_pdf(contenu).empreinte
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
        # d'une facture en échec relancent chacun l'extraction.
        existante = session.scalars(select(FactureEnBase).where(FactureEnBase.empreinte == empreinte).with_for_update()).one()
        if existante.etat == Etat.ECHEC.value:
            _journaliser(session, existante, "NOUVEL_ESSAI", MOTEUR, {"nom_fichier": nom_fichier})
            _extraire_et_controler(session, existante, contenu, extracteur, aujourd_hui)
            return ResultatTraitement(existante, deja_vue=False)
        _journaliser(session, existante, "DOUBLON_FICHIER", MOTEUR, {"nom_fichier": nom_fichier})
        return ResultatTraitement(existante, deja_vue=True)

    facture = session.get(FactureEnBase, nouvel_id)
    _journaliser(session, facture, "RECEPTION", MOTEUR, {"nom_fichier": nom_fichier, "taille_octets": len(contenu)})
    _extraire_et_controler(session, facture, contenu, extracteur, aujourd_hui)
    return ResultatTraitement(facture, deja_vue=False)


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


def exporter(session: Session, facture_id: uuid.UUID, auteur: str, dossier: pathlib.Path, client=None) -> FactureEnBase:
    """Envoie une facture validée à la comptabilité. Sans effet si elle est déjà exportée.

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
        envoi = envoyer_au_logiciel(str(facture.id), lignes, client)
    except ErreurExport as erreur:
        _journaliser(session, facture, "EXPORT_ECHOUE", auteur, {"raison": str(erreur)})
        raise
    _passer(session, facture, Etat.EXPORTEE, "EXPORT", auteur, {"fichier": chemin.name, "ecriture": en_json(lignes), "logiciel": envoi})
    return facture
