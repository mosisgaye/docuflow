"""Le travailleur : lit les factures en attente, une tâche à la fois.

Lancement : uv run python -m moteur.travailleur
On peut en lancer plusieurs en parallèle : ils ne prennent jamais la même tâche.

Comment c'est fiable :
- Une tâche est prise avec « SELECT … FOR UPDATE SKIP LOCKED » puis traitée dans la
  même transaction. Tant qu'un travailleur la tient, les autres passent à la suivante.
- Si le travailleur plante en pleine lecture (coupure, kill -9, redémarrage du serveur),
  sa connexion se ferme, PostgreSQL annule la transaction et libère la tâche. Un autre
  travailleur la reprend : aucune facture ne reste bloquée, aucune n'est lue deux fois.
- Une panne passagère de l'IA reprogramme la tâche plus tard, avec un délai croissant.
  Une erreur définitive, ou trop de pannes, met la facture en échec et abandonne la tâche.

Limite connue : une facture qui ferait planter le processus lui-même à chaque essai
serait reprise indéfiniment. Il faudrait alors la retirer de la file à la main.
"""

import logging
import pathlib
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from moteur import config, evenements_sortants, relances
from moteur.base import Etat, EtatTache, FactureEnBase, Tache, creer_moteur, verifier_schema
from moteur.extraction_llm import ErreurExtraction, ResultatExtraction, extraire, extraire_images
from moteur.odoo import Odoo, depuis_configuration
from moteur.notifications import envoyer_en_attente
from moteur.workflow import MOTEUR, _journaliser, _passer, lire_et_controler

# Délais avant chaque nouvel essai d'une tâche : 30 s, 2 min, 10 min, 30 min, 2 h.
PLAN_DE_REPRISE_S = [30, 120, 600, 1800, 7200]
TENTATIVES_MAX = len(PLAN_DE_REPRISE_S)
ATTENTE_FILE_VIDE_S = 1.0
RELANCES_TOUTES_LES_S = 600
LIVRAISONS_PAR_TOUR = 20

journal = logging.getLogger("moteur.travailleur")


@dataclass(frozen=True)
class CompteRendu:
    tache_id: str
    facture_id: str
    resultat: str  # "lue", "reprogrammee", "abandonnee"
    detail: str = ""


def prendre_une_tache(session: Session) -> Tache | None:
    """Prend la plus ancienne tâche prête, en la verrouillant. Les tâches tenues par un autre sont sautées."""
    return session.scalars(
        select(Tache)
        .where(Tache.etat == EtatTache.EN_ATTENTE.value, Tache.prochain_essai_le <= func.now())
        .order_by(Tache.prochain_essai_le)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()


def _abandonner(session: Session, tache: Tache, facture: FactureEnBase, raison: str) -> CompteRendu:
    if facture.etat != Etat.ECHEC.value:
        _passer(session, facture, Etat.ECHEC, "EXTRACTION_ECHOUEE", MOTEUR, {"raison": raison, "tentatives": tache.tentatives})
    tache.etat = EtatTache.ABANDONNEE.value
    tache.derniere_erreur = raison
    return CompteRendu(str(tache.id), str(facture.id), "abandonnee", raison)


def traiter_une_tache(
    session: Session,
    dossier: pathlib.Path,
    extracteur: Callable[[str], ResultatExtraction] = extraire,
    aujourd_hui: date | None = None,
    odoo: Odoo | None = None,
    extracteur_images: Callable[[list[bytes]], ResultatExtraction] = extraire_images,
) -> CompteRendu | None:
    """Prend une tâche et la mène au bout. Ne valide pas la transaction : c'est à l'appelant de le faire.

    Renvoie None si aucune tâche n'est prête.
    """
    tache = prendre_une_tache(session)
    if tache is None:
        return None
    facture = session.get(FactureEnBase, tache.facture_id, with_for_update=True)
    tache.tentatives += 1

    try:
        contenu = (dossier / f"{facture.empreinte}.pdf").read_bytes()
    except FileNotFoundError:
        return _abandonner(session, tache, facture, "Le fichier PDF de la facture est introuvable sur le serveur.")

    try:
        lire_et_controler(session, facture, contenu, extracteur, aujourd_hui, echec_si_passagere=False, odoo=odoo, extracteur_images=extracteur_images)
    except ErreurExtraction as erreur:
        if tache.tentatives >= TENTATIVES_MAX:
            return _abandonner(session, tache, facture, f"{erreur} ; abandon après {tache.tentatives} tentatives.")
        delai = max(PLAN_DE_REPRISE_S[tache.tentatives - 1], erreur.attendre_avant or 0)
        tache.prochain_essai_le = func.now() + timedelta(seconds=delai)
        tache.derniere_erreur = str(erreur)
        _journaliser(
            session, facture, "NOUVEL_ESSAI_PROGRAMME", MOTEUR, {"raison": str(erreur), "tentative": tache.tentatives, "dans_s": round(delai)}
        )
        return CompteRendu(str(tache.id), str(facture.id), "reprogrammee", f"dans {round(delai)} s : {erreur}")

    if facture.etat == Etat.ECHEC.value:  # erreur définitive : scan illisible, clé refusée…
        tache.etat = EtatTache.ABANDONNEE.value
        tache.derniere_erreur = str(facture.evenements[-1].detail.get("raison", ""))
        return CompteRendu(str(tache.id), str(facture.id), "abandonnee", tache.derniere_erreur)
    tache.etat = EtatTache.TERMINEE.value
    tache.derniere_erreur = None
    return CompteRendu(str(tache.id), str(facture.id), "lue", facture.etat)


def livrer_les_evenements(fabrique_session: Callable[[], Session], maximum: int = LIVRAISONS_PAR_TOUR) -> int:
    """Envoie les événements sortants dus. Chaque livraison a sa propre transaction."""
    faites = 0
    for _ in range(maximum):
        with fabrique_session() as session:
            livraison = evenements_sortants.livrer_une(session)
            # Lu avant le commit : après, les attributs ne sont plus chargés.
            resume = livraison and (str(livraison.id)[:8], livraison.evenement, livraison.etat, livraison.derniere_reponse)
            session.commit()
        if not resume:
            break
        faites += 1
        journal.info("livraison=%s evenement=%s etat=%s %s", *resume)
    return faites


def faire_les_relances(fabrique_session: Callable[[], Session]) -> int:
    with fabrique_session() as session:
        nombre = relances.relancer(session)
        session.commit()
        envoyer_en_attente(session, fabrique_session)
    if nombre:
        journal.info("Relances envoyées : %s", nombre)
    return nombre


def boucle(arret: threading.Event, fabrique_session: Callable[[], Session], dossier: pathlib.Path, extracteur=extraire, odoo: Odoo | None = None) -> None:
    """Traite les tâches tant qu'on ne demande pas l'arrêt. Une tâche commencée est toujours terminée."""
    prochaines_relances = 0.0
    while not arret.is_set():
        try:
            livrer_les_evenements(fabrique_session)
            if time.monotonic() >= prochaines_relances:
                prochaines_relances = time.monotonic() + RELANCES_TOUTES_LES_S
                faire_les_relances(fabrique_session)
        except Exception:  # noqa: BLE001
            journal.exception("Erreur imprévue pendant les livraisons ou les relances.")
        debut = time.monotonic()
        try:
            with fabrique_session() as session:
                compte_rendu = traiter_une_tache(session, dossier, extracteur, odoo=odoo)
                session.commit()
                envoyer_en_attente(session, fabrique_session)  # les mails ne partent qu'une fois la lecture enregistrée
        except Exception:  # noqa: BLE001 - le travailleur ne doit jamais mourir sur une erreur imprévue
            journal.exception("Erreur imprévue : la tâche est relâchée et sera reprise.")
            arret.wait(5)
            continue
        if compte_rendu is None:
            arret.wait(ATTENTE_FILE_VIDE_S)
            continue
        journal.info(
            "tache=%s facture=%s resultat=%s duree_s=%.2f %s",
            compte_rendu.tache_id[:8], compte_rendu.facture_id[:8], compte_rendu.resultat, time.monotonic() - debut, compte_rendu.detail,
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("alembic").setLevel(logging.WARNING)  # la vérification du schéma n'a rien à dire quand tout va bien
    moteur = creer_moteur()
    verifier_schema(moteur)
    arret = threading.Event()

    def demander_arret(signal_recu, _cadre) -> None:
        journal.info("Arrêt demandé (%s) : fin de la tâche en cours, puis arrêt.", signal.Signals(signal_recu).name)
        arret.set()

    signal.signal(signal.SIGTERM, demander_arret)
    signal.signal(signal.SIGINT, demander_arret)
    dossier = config.dossier_fichiers()
    odoo = depuis_configuration()
    journal.info("Travailleur démarré : fichiers dans %s ; Odoo : %s", dossier, odoo or "non branché")
    boucle(arret, lambda: Session(moteur), dossier, odoo=odoo)
    moteur.dispose()
    journal.info("Travailleur arrêté.")


if __name__ == "__main__":
    main()
