"""Le workflow d'une facture : de la réception à la validation.

    recue ──> extraite ──> a_valider ──(en_approbation)──> validee ──> exportee
      │           │            │
      │           └──> en_anomalie ──> rejetee
Le passage de a_valider à validee suit le circuit d'approbation (moteur/approbation.py).
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
from moteur.controles import Anomalie, Gravite, controler, est_validable, iban_normalise, iban_valide
from moteur.export import ErreurExport, ecriture, en_csv, en_json, envoyer_au_logiciel, nom_fichier
from moteur.extraction_llm import ErreurExtraction, ResultatExtraction, extraire, extraire_images
from moteur.consignes import enregistrer as enregistrer_consigne
from moteur.facturx import LECTEUR as LECTEUR_FACTURX
from moteur.facturx import FacturXInvalide, lire_facturx
from moteur.lecture_pdf import lire_pdf, pages_en_images
from moteur.modeles import Facture
from moteur.odoo import ErreurOdoo, Odoo
from moteur.approbation import LIBELLES, ApprobationRefusee, approuver, circuit, niveau_attendu, version_en_vigueur
from moteur import notifications

MOTEUR = "moteur"

TRANSITIONS: dict[Etat, set[Etat]] = {
    Etat.RECUE: {Etat.EXTRAITE, Etat.ECHEC},
    Etat.ECHEC: {Etat.EXTRAITE, Etat.ECHEC},
    Etat.EXTRAITE: {Etat.A_VALIDER, Etat.EN_ANOMALIE},
    Etat.A_VALIDER: {Etat.VALIDEE, Etat.REJETEE, Etat.EN_APPROBATION},
    Etat.EN_APPROBATION: {Etat.VALIDEE, Etat.REJETEE},
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
    extracteur_images: Callable[[list[bytes]], ResultatExtraction] = extraire_images,
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
    #    Un scan ou une photo n'a pas de texte : l'IA lit alors les images de ses pages.
    if donnees is None:
        lu = lire_pdf(contenu)
        images = []
        if not lu.a_du_texte:
            try:
                images = pages_en_images(contenu)
            except Exception:  # noqa: BLE001 - un PDF que même le rendu ne sait pas ouvrir
                images = []
            if not images:
                _passer(session, facture, Etat.ECHEC, "LECTURE_IMPOSSIBLE", MOTEUR, {"raison": "Le PDF ne contient ni texte ni page lisible."})
                return
        try:
            resultat = extracteur_images(images) if images else extracteur(lu.texte)
        except ErreurExtraction as erreur:
            if erreur.passagere and not echec_si_passagere:
                raise
            _passer(session, facture, Etat.ECHEC, "EXTRACTION_ECHOUEE", MOTEUR, {"raison": str(erreur)})
            return
        donnees = resultat.facture
        detail = {"source": "ia-image" if images else "ia", "fournisseur_llm": resultat.fournisseur, "modele": resultat.modele, "duree_s": round(resultat.duree_s, 2)}
        if images:
            detail |= {"pages_lues": len(images), "pages_total": lu.nb_pages}
        if resultat.jetons:
            detail["jetons"] = resultat.jetons  # le coût réel de cette lecture, compté par le fournisseur d'IA
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
    detail = {"anomalies": [anomalie.code for anomalie in anomalies]}
    if etat == Etat.A_VALIDER:
        # Qui doit approuver, selon les règles en vigueur : calculé une fois, gardé avec la facture.
        facture.circuit = circuit(facture.donnees, facture.anomalies, version_en_vigueur(session))
        detail["circuit"] = [niveau["niveau"] for niveau in facture.circuit["niveaux"]]
        if facture.circuit["bloque"]:
            detail["bloque"] = facture.circuit["bloque"]
    _passer(session, facture, etat, "CONTROLE", MOTEUR, detail)
    if etat == Etat.A_VALIDER and facture.circuit["version"] is not None and not facture.circuit["bloque"]:
        notifications.demander(session, facture, facture.circuit["niveaux"][0]["niveau"])


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
    verdict, anomalies_iban = _iban_face_a_odoo(donnees, fournisseur.ibans)
    _journaliser(
        session, facture, "FOURNISSEUR_ODOO", MOTEUR,
        {"trouve": True, "id": fournisseur.id, "nom": fournisseur.nom, "adresse": odoo.adresse_fiche("res.partner", fournisseur.id), "iban": verdict},
    )
    return anomalies_iban + _commande_dans_odoo(session, facture, donnees, odoo, fournisseur.id)


def _masque(iban: str) -> str:
    return f"…{iban[-4:]}"


def _iban_face_a_odoo(donnees: Facture, connus: tuple[str, ...]) -> tuple[str, list[Anomalie]]:
    """Compare l'IBAN imprimé sur la facture à ceux connus dans Odoo pour ce fournisseur.

    C'est la parade à la fraude au changement de coordonnées bancaires : un escroc se fait passer
    pour un vrai fournisseur et donne « ses nouvelles coordonnées ». La facture n'est pas refusée
    (un vrai changement de banque existe) : elle est signalée, et les règles d'approbation
    exigent alors l'accord du directeur financier, après vérification par téléphone.
    """
    if not donnees.fournisseur_iban:
        return "absent", []
    iban = iban_normalise(donnees.fournisseur_iban)
    if not iban_valide(iban):
        return "invalide", []  # déjà signalé par les contrôles (IBAN_INVALIDE, bloquant)
    if not connus:
        return "inconnu", [
            Anomalie(
                "IBAN_NOUVEAU",
                Gravite.AVERTISSEMENT,
                f"Aucun IBAN n'est connu dans Odoo pour ce fournisseur : vérifiez celui de la facture ({_masque(iban)}) avant le premier paiement.",
                "fournisseur_iban",
            )
        ]
    if iban in connus:
        return "conforme", []
    return "different", [
        Anomalie(
            "IBAN_DIFFERENT",
            Gravite.AVERTISSEMENT,
            f"L'IBAN de cette facture ({_masque(iban)}) n'est pas celui connu dans Odoo pour ce fournisseur "
            f"({', '.join(_masque(connu) for connu in connus)}). Risque de fraude au changement de coordonnées bancaires : "
            "appelez le fournisseur au numéro habituel, jamais à celui écrit sur la facture, avant tout paiement.",
            "fournisseur_iban",
        )
    ]


def _commande_dans_odoo(session: Session, facture: FactureEnBase, donnees: Facture, odoo: Odoo, fournisseur_id: int) -> list[Anomalie]:
    """Compare la facture au bon de commande. Un écart ou une absence de commande est un avertissement :
    la personne qui valide le voit, et les règles d'approbation pourront s'en servir."""
    try:
        rapprochement = odoo.rapprocher(fournisseur_id, donnees)
    except ErreurOdoo as erreur:
        _journaliser(session, facture, "ODOO_INDISPONIBLE", MOTEUR, {"raison": str(erreur)})
        return []
    detail = {"statut": rapprochement.statut, "commande": rapprochement.commande, "ecarts": rapprochement.ecarts}
    if rapprochement.commande_id:
        detail["adresse"] = odoo.adresse_fiche("purchase.order", rapprochement.commande_id)
    _journaliser(session, facture, "COMMANDE_ODOO", MOTEUR, detail)
    if rapprochement.statut == "sans_commande":
        return [Anomalie("SANS_COMMANDE", Gravite.AVERTISSEMENT, "Aucun bon de commande dans Odoo ne correspond à cette facture : achat fait sans commande ?", "lignes")]
    if rapprochement.statut == "ecart":
        return [
            Anomalie("ECART_COMMANDE", Gravite.AVERTISSEMENT, f"Écart avec le bon de commande {rapprochement.commande} : {ecart}.", "lignes")
            for ecart in rapprochement.ecarts
        ]
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
    extracteur_images: Callable[[list[bytes]], ResultatExtraction] = extraire_images,
) -> ResultatTraitement:
    """Reçoit un PDF et le lit tout de suite : utilisé par les outils et les tests.

    En service, l'API appelle recevoir() et le travailleur fait la lecture.
    """
    resultat = recevoir(session, contenu, nom_fichier)
    if resultat.tache is not None:
        resultat.tache.tentatives += 1
        lire_et_controler(session, resultat.facture, contenu, extracteur, aujourd_hui, odoo=odoo, extracteur_images=extracteur_images)
        resultat.tache.etat = (EtatTache.ABANDONNEE if resultat.facture.etat == Etat.ECHEC.value else EtatTache.TERMINEE).value
        session.flush()
    return resultat


def _charger(session: Session, facture_id: uuid.UUID) -> FactureEnBase:
    facture = session.get(FactureEnBase, facture_id)
    if facture is None:
        raise FactureIntrouvable(str(facture_id))
    return facture


def valider(session: Session, facture_id: uuid.UUID, auteur: str) -> FactureEnBase:
    """Approbation par une personne, au niveau attendu du circuit. Impossible si un contrôle bloquant a échoué.

    La facture devient « validée » quand tous les niveaux du circuit ont approuvé ; avant, elle est
    « en approbation ». Deux approbations simultanées passent l'une après l'autre.
    """
    facture = session.get(FactureEnBase, facture_id, with_for_update=True)
    if facture is None:
        raise FactureIntrouvable(str(facture_id))
    if facture.etat not in (Etat.A_VALIDER.value, Etat.EN_APPROBATION.value):
        raise TransitionInterdite(f"Passage interdit de « {facture.etat} » à « {Etat.VALIDEE.value} ».")
    try:
        approbation, termine = approuver(session, facture, auteur)
    except ApprobationRefusee as erreur:
        raise TransitionInterdite(str(erreur)) from erreur
    detail = {"niveau": approbation.niveau, "libelle": LIBELLES[approbation.niveau]}
    if termine:
        _passer(session, facture, Etat.VALIDEE, "VALIDATION", auteur, detail)
    elif facture.etat == Etat.A_VALIDER.value:
        _passer(session, facture, Etat.EN_APPROBATION, "APPROBATION", auteur, detail)
    else:
        _journaliser(session, facture, "APPROBATION", auteur, detail)
    if not termine:
        notifications.demander(session, facture, niveau_attendu(session, facture))
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
