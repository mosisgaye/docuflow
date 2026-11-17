"""La Console de l'opérateur Verifac : ce qu'il faut voir pour faire tourner une installation chez un client.

Elle ne montre que des faits mesurés en base :
- santé : la base répond, la file de lecture, le travailleur (dernière tâche traitée) ;
- version : le code en service (VERIFAC_VERSION, posé au déploiement) et la migration appliquée ;
- usage : factures reçues par jour, états, comptes ;
- IA : lectures, jetons comptés par le fournisseur d'IA, coût seulement si le prix est renseigné
  (VERIFAC_PRIX_ENTREE et VERIFAC_PRIX_SORTIE, en euros par million de jetons) : on n'invente pas de tarif ;
- incidents : lectures abandonnées, mails non partis.

L'opérateur peut aussi créer le premier administrateur d'une installation qui n'en a plus, et rien d'autre :
il n'approuve jamais et ne publie jamais (moteur/comptes.py).
"""

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from moteur import comptes, config
from moteur.base import Compte, EtatTache, Evenement, FactureEnBase, Tache

JOURS = 30


def _prix(nom: str) -> Decimal | None:
    valeur = config.lire(nom, "").strip().replace(",", ".")
    try:
        prix = Decimal(valeur) if valeur else None
    except InvalidOperation:
        return None
    return prix if prix is not None and prix >= 0 else None


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def etat(session: Session, maintenant: datetime | None = None) -> dict:
    maintenant = maintenant or datetime.now(UTC)
    depuis = maintenant - timedelta(days=JOURS)

    # Santé
    session.execute(text("select 1"))
    taches = dict(session.execute(select(Tache.etat, func.count()).group_by(Tache.etat)).all())
    plus_ancienne = session.scalar(select(func.min(Tache.cree_le)).where(Tache.etat == EtatTache.EN_ATTENTE.value))
    derniere_traitee = session.scalar(select(func.max(Tache.modifie_le)).where(Tache.etat != EtatTache.EN_ATTENTE.value))
    migration = session.execute(text("select version_num from alembic_version")).scalar()

    # Usage
    par_jour = dict(
        session.execute(
            select(func.date(FactureEnBase.cree_le), func.count()).where(FactureEnBase.cree_le >= depuis).group_by(func.date(FactureEnBase.cree_le))
        ).all()
    )
    jours = [(depuis + timedelta(days=rang + 1)).date() for rang in range(JOURS)]
    par_etat = dict(session.execute(select(FactureEnBase.etat, func.count()).group_by(FactureEnBase.etat)).all())
    tous = session.scalars(select(Compte)).all()
    actifs = [compte for compte in tous if compte.actif]

    # IA : les lectures des 30 derniers jours, telles que le fournisseur d'IA les a comptées
    lectures = session.scalars(select(Evenement.detail).where(Evenement.type == "EXTRACTION", Evenement.cree_le >= depuis)).all()
    ia = [detail for detail in lectures if str(detail.get("source", "")).startswith("ia")]
    entree = sum(int((detail.get("jetons") or {}).get("entree") or 0) for detail in ia)
    sortie = sum(int((detail.get("jetons") or {}).get("sortie") or 0) for detail in ia)
    prix_entree, prix_sortie = _prix("VERIFAC_PRIX_ENTREE"), _prix("VERIFAC_PRIX_SORTIE")
    cout = (
        float(round((Decimal(entree) * prix_entree + Decimal(sortie) * prix_sortie) / Decimal(1_000_000), 2))
        if prix_entree is not None and prix_sortie is not None
        else None
    )

    # Incidents récents
    abandonnees = session.execute(
        select(Tache.facture_id, Tache.derniere_erreur, Tache.modifie_le).where(Tache.etat == EtatTache.ABANDONNEE.value).order_by(Tache.modifie_le.desc()).limit(10)
    ).all()
    mails = session.execute(
        select(Evenement.facture_id, Evenement.detail, Evenement.cree_le).where(Evenement.type == "NOTIFICATION_ECHOUEE").order_by(Evenement.cree_le.desc()).limit(10)
    ).all()
    incidents = sorted(
        [{"type": "lecture", "facture_id": str(f), "message": (erreur or "Lecture abandonnée")[:300], "le": _iso(le)} for f, erreur, le in abandonnees]
        + [{"type": "mail", "facture_id": str(f), "message": str(detail.get("raison", "Mail non envoyé"))[:300], "le": _iso(le)} for f, detail, le in mails],
        key=lambda incident: incident["le"] or "",
        reverse=True,
    )[:10]

    return {
        "sante": {
            "base": "ok",
            "file_en_attente": taches.get(EtatTache.EN_ATTENTE.value, 0),
            "plus_ancienne_attente_s": round((maintenant - plus_ancienne).total_seconds()) if plus_ancienne else None,
            "derniere_tache_traitee": _iso(derniere_traitee),
            "lectures_abandonnees": taches.get(EtatTache.ABANDONNEE.value, 0),
        },
        "version": {"code": config.lire("VERIFAC_VERSION", "") or None, "migration": migration},
        "usage": {
            "jours": [{"jour": jour.isoformat(), "factures": par_jour.get(jour, 0)} for jour in jours],
            "factures_30_jours": sum(par_jour.values()),
            "factures_total": sum(par_etat.values()),
            "par_etat": par_etat,
            "comptes_actifs": len(actifs),
            "administrateurs": sum(1 for compte in actifs if compte.role == "administrateur"),
            "derniere_connexion": _iso(max((compte.derniere_connexion for compte in tous if compte.derniere_connexion), default=None)),
        },
        "ia": {
            "lectures_30_jours": len(ia),
            "modeles": dict(Counter(str(detail.get("modele") or "inconnu") for detail in ia)),
            "jetons_entree": entree,
            "jetons_sortie": sortie,
            "cout_30_jours_eur": cout,
            "prix_renseigne": cout is not None,
        },
        "incidents": incidents,
    }


def creer_premier_administrateur(session: Session, nom: str, email: str, operateur: str) -> Compte:
    """Seulement si l'installation n'a plus aucun administrateur actif : sinon c'est au client de gérer son équipe."""
    if comptes.administrateurs_actifs(session) > 0:
        raise comptes.CompteInvalide("Cette installation a déjà un administrateur : c'est lui qui gère l'équipe.")
    return comptes.creer(session, nom, email, "administrateur", [], f"{operateur} (opérateur)")
