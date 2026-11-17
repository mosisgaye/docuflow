"""Relancer la personne qui doit approuver une facture et ne l'a pas encore fait.

Quand relancer (les délais par défaut ; chaque version du circuit peut les régler par niveau,
et une facture garde ceux de la version avec laquelle son circuit a été calculé) :
- 48 heures après le dernier mail envoyé à ce niveau, sans décision ;
- plus tôt (24 heures) si l'échéance de paiement tombe dans 3 jours ou moins :
  une facture payée en retard coûte des pénalités.
Au plus 2 relances par niveau : au-delà, ce n'est plus un oubli, c'est un sujet à traiter
de vive voix. La facture reste visible dans DocuFlow.

Une relance n'est faite que si le premier mail est bien parti : si les mails ne sont pas
configurés, l'approbation se fait dans DocuFlow et il n'y a personne à relancer.

Le travailleur appelle relancer() régulièrement. Un verrou PostgreSQL garantit qu'un seul
travailleur s'en occupe à la fois : deux travailleurs ne relancent jamais deux fois.
"""

from collections import Counter
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from moteur import notifications
from moteur.approbation import RELANCES_DEFAUT, niveau_attendu
from moteur.base import Etat, Evenement, FactureEnBase

DELAI_NORMAL = timedelta(hours=48)
DELAI_URGENT = timedelta(hours=24)
JOURS_URGENCE = 3
RELANCES_MAX = 2
VERROU = 734_211  # numéro arbitraire du verrou consultatif « relances »


def _date(valeur) -> date | None:
    try:
        return date.fromisoformat(valeur) if valeur else None
    except (TypeError, ValueError):
        return None


def reglage(facture: FactureEnBase, niveau: str) -> tuple[timedelta, timedelta, int]:
    """Les délais (normal, urgent) et le maximum de relances de ce niveau, figés dans le circuit de la facture."""
    propre = ((getattr(facture, "circuit", None) or {}).get("relances") or {}).get(niveau) or RELANCES_DEFAUT
    return timedelta(hours=propre["delai_h"]), timedelta(hours=propre["delai_urgent_h"]), propre["maximum"]


def a_relancer(facture: FactureEnBase, niveau: str, mails: list[Evenement], maintenant: datetime) -> str | None:
    """La raison de relancer ce niveau maintenant, ou None. Ne lit que ce qu'on lui donne : facile à tester."""
    delai_normal, delai_urgent, maximum = reglage(facture, niveau)
    du_niveau = [e for e in mails if e.detail.get("niveau") == niveau]
    if not any(e.type == "NOTIFICATION" for e in du_niveau):
        return None  # le premier mail n'est jamais parti : personne n'a été prévenu par mail
    # Comptées par personne : deux personnes au même niveau reçoivent chacune leur relance.
    par_personne = Counter(e.detail.get("destinataire") for e in du_niveau if e.detail.get("rappel"))
    if max(par_personne.values(), default=0) >= maximum:
        return None
    attente = maintenant - max(e.cree_le for e in du_niveau)
    echeance = _date((facture.donnees or {}).get("date_echeance"))
    jours = (echeance - maintenant.date()).days if echeance else None
    if jours is not None and jours <= JOURS_URGENCE and attente >= delai_urgent:
        return "l'échéance est dépassée." if jours < 0 else f"l'échéance de paiement tombe dans {jours} jour{'s' if jours > 1 else ''}."
    if attente >= delai_normal:
        return f"cette facture attend votre décision depuis {int(attente.total_seconds() // 3600)} heures."
    return None


def relancer(session: Session, maintenant: datetime | None = None) -> int:
    """Prépare les relances dues (elles partent après le commit, comme les autres mails). Renvoie leur nombre."""
    if not session.scalar(text("SELECT pg_try_advisory_xact_lock(:v)"), {"v": VERROU}):
        return 0  # un autre travailleur s'en occupe
    maintenant = maintenant or datetime.now(UTC)
    factures = session.scalars(
        select(FactureEnBase).where(FactureEnBase.etat.in_([Etat.A_VALIDER.value, Etat.EN_APPROBATION.value]))
    ).all()
    nombre = 0
    for facture in factures:
        if not facture.circuit or facture.circuit.get("bloque") or facture.circuit.get("version") is None:
            continue
        niveau = niveau_attendu(session, facture)
        if niveau is None:
            continue
        mails = list(
            session.scalars(
                select(Evenement).where(Evenement.facture_id == facture.id, Evenement.type.in_(["NOTIFICATION", "NOTIFICATION_ECHOUEE"]))
            )
        )
        raison = a_relancer(facture, niveau, mails, maintenant)
        if raison and notifications.demander(session, facture, niveau, rappel=raison):
            nombre += 1
    return nombre
