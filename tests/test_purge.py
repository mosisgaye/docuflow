"""La purge retire seulement les données techniques périmées, jamais ce qui sert de preuve."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from moteur import purge
from moteur.base import (
    Abonnement,
    AppelConnecteur,
    Compte,
    DemandeConnexion,
    DemandeOAuth,
    EtatTache,
    Evenement,
    FactureEnBase,
    Livraison,
    Tache,
)

MAINTENANT = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def compter(session, modele) -> int:
    return session.scalar(select(func.count()).select_from(modele))


def test_la_purge_retire_le_perime_et_garde_le_reste(session):
    vieux, recent = MAINTENANT - timedelta(days=120), MAINTENANT - timedelta(hours=2)

    facture = FactureEnBase(empreinte=uuid.uuid4().hex, nom_fichier="a.pdf", etat="validee", anomalies=[])
    session.add(facture)
    session.flush()
    session.add(Evenement(facture=facture, rang=1, type="RECEPTION", etat="validee", auteur="moteur", detail={}, cree_le=vieux))
    session.add_all(
        [
            Tache(facture_id=facture.id, etat=EtatTache.TERMINEE.value, modifie_le=vieux),  # purgée
            Tache(facture_id=facture.id, etat=EtatTache.ABANDONNEE.value, modifie_le=vieux),  # gardée : un incident
            Tache(facture_id=facture.id, etat=EtatTache.TERMINEE.value, modifie_le=recent),  # gardée : récente
        ]
    )
    compte = Compte(nom="Claire", email=f"{uuid.uuid4().hex}@exemple.test", role="membre", niveaux=[], cree_par="test")
    session.add(compte)
    session.flush()
    session.add_all(
        [
            DemandeConnexion(compte_id=compte.id, empreinte_jeton="a" * 64, empreinte_code="x", essais=0, expire_le=vieux),
            DemandeConnexion(compte_id=compte.id, empreinte_jeton="b" * 64, empreinte_code="x", essais=0, expire_le=MAINTENANT + timedelta(minutes=10)),
            DemandeOAuth(etat="vieux", connecteur="hubspot", verificateur="v", auteur="test", cree_le=vieux),
            DemandeOAuth(etat="recent", connecteur="hubspot", verificateur="v", auteur="test", cree_le=recent),
            AppelConnecteur(connecteur="odoo", outil="chercher", arguments={}, statut="ok", cree_le=vieux),
            AppelConnecteur(connecteur="odoo", outil="chercher", arguments={}, statut="ok", cree_le=recent),
        ]
    )
    abonnement = Abonnement(url="https://exemple.test/crochet", evenements=["facture.validee"], secret="s", actif=True, cree_par="test")
    session.add(abonnement)
    session.flush()
    session.add_all(
        [
            Livraison(abonnement_id=abonnement.id, evenement="facture.validee", charge={}, etat="livree", livree_le=vieux),
            Livraison(abonnement_id=abonnement.id, evenement="facture.validee", charge={}, etat="abandonnee"),
        ]
    )
    session.flush()

    supprimees = purge.purger(session, MAINTENANT)

    assert supprimees == {"taches": 1, "demandes_connexion": 1, "demandes_oauth": 1, "appels_connecteurs": 1, "livraisons": 1, "oauth_codes": 0, "oauth_jetons": 0}
    assert compter(session, Tache) == 2
    assert compter(session, DemandeConnexion) == 1
    assert compter(session, DemandeOAuth) == 1
    assert compter(session, AppelConnecteur) == 1
    assert compter(session, Livraison) == 1
    # Ce qui sert de preuve reste, même vieux de 120 jours.
    assert compter(session, FactureEnBase) == 1
    assert compter(session, Evenement) == 1
