"""Base de données : les factures et le journal de ce qui leur arrive.

Les tables :
- factures   : une ligne par document reçu, avec son état et ses données ;
- evenements : la piste d'audit. Chaque étape y ajoute une ligne, jamais modifiée ensuite ;
- consignes  : le texte exact de chaque version des consignes données à l'IA ;
- taches     : la file des lectures à faire, prises par le travailleur (moteur/travailleur.py) ;
- mails_recus : chaque mail reçu à l'adresse de dépôt, et ce qu'on a fait de ses pièces jointes.

Toute modification de ces modèles demande une migration (dossier migrations/).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, create_engine, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from moteur import config


class Etat(StrEnum):
    RECUE = "recue"  # le fichier est arrivé
    EXTRAITE = "extraite"  # le LLM a rendu des données valides
    A_VALIDER = "a_valider"  # contrôles passés, une personne doit valider
    EN_ANOMALIE = "en_anomalie"  # un contrôle bloquant a échoué
    VALIDEE = "validee"  # une personne a validé
    REJETEE = "rejetee"  # une personne a rejeté
    EXPORTEE = "exportee"  # envoyée au logiciel tiers
    ECHEC = "echec"  # lecture ou extraction impossible ; un nouvel essai est permis


class EtatTache(StrEnum):
    EN_ATTENTE = "en_attente"  # à faire, dès que prochain_essai_le est passé
    TERMINEE = "terminee"  # la lecture a abouti
    ABANDONNEE = "abandonnee"  # erreur définitive, ou trop de pannes : la facture est en échec


class Base(DeclarativeBase):
    pass


class FactureEnBase(Base):
    __tablename__ = "factures"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # L'empreinte est unique : un même fichier ne peut pas créer deux factures.
    empreinte: Mapped[str] = mapped_column(String(64), unique=True)
    nom_fichier: Mapped[str] = mapped_column(String(255))
    etat: Mapped[str] = mapped_column(String(20), index=True)
    donnees: Mapped[dict | None] = mapped_column(JSONB)
    anomalies: Mapped[list] = mapped_column(JSONB, default=list)
    # Recopiés depuis les données pour retrouver vite un doublon.
    fournisseur_siret: Mapped[str | None] = mapped_column(String(14))
    numero_facture: Mapped[str | None] = mapped_column(String(100))
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    modifie_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    evenements: Mapped[list["Evenement"]] = relationship(back_populates="facture", order_by="Evenement.rang")

    __table_args__ = (Index("ix_factures_fournisseur_numero", "fournisseur_siret", "numero_facture"),)


class Evenement(Base):
    __tablename__ = "evenements"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    facture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("factures.id"), index=True)
    rang: Mapped[int]  # ordre de l'événement dans la vie de la facture
    type: Mapped[str] = mapped_column(String(40))
    etat: Mapped[str] = mapped_column(String(20))  # état de la facture après l'événement
    auteur: Mapped[str] = mapped_column(String(100))  # "moteur" ou le nom de la personne
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    # clock_timestamp() et non now() : now() donne l'heure de DÉBUT de la transaction.
    # Une lecture de 11 secondes datait alors tous ses événements de la même seconde.
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())

    facture: Mapped[FactureEnBase] = relationship(back_populates="evenements")


class Consigne(Base):
    __tablename__ = "consignes"

    id: Mapped[str] = mapped_column(String(12), primary_key=True)  # empreinte du contenu
    usage: Mapped[str] = mapped_column(String(20))
    texte: Mapped[str] = mapped_column(Text)
    schema: Mapped[dict | list] = mapped_column(JSONB)  # format de réponse imposé à l'IA
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Tache(Base):
    __tablename__ = "taches"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    facture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("factures.id"), index=True)
    type: Mapped[str] = mapped_column(String(20), server_default="lecture")
    etat: Mapped[str] = mapped_column(String(20), server_default=EtatTache.EN_ATTENTE.value)
    tentatives: Mapped[int] = mapped_column(Integer, server_default="0")
    prochain_essai_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    derniere_erreur: Mapped[str | None] = mapped_column(Text)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    modifie_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # Le travailleur cherche les tâches en attente dont l'heure est venue : cet index ne contient qu'elles.
        Index("ix_taches_a_faire", "prochain_essai_le", postgresql_where=text("etat = 'en_attente'")),
        # Jamais deux tâches en attente pour la même facture.
        Index("uq_taches_une_en_attente", "facture_id", unique=True, postgresql_where=text("etat = 'en_attente'")),
    )


class MailRecu(Base):
    __tablename__ = "mails_recus"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # L'identifiant donné par la messagerie (en-tête Message-ID) : un mail renvoyé n'est traité qu'une fois.
    message_id: Mapped[str] = mapped_column(String(998), unique=True)
    expediteur: Mapped[str] = mapped_column(String(320))
    objet: Mapped[str] = mapped_column(Text, server_default="")
    statut: Mapped[str] = mapped_column(String(20))  # "traite" (au moins une facture) ou "sans_facture"
    pieces: Mapped[list] = mapped_column(JSONB, default=list)  # ce qu'on a fait de chaque pièce jointe
    recu_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def creer_moteur(url: str | None = None) -> Engine:
    return create_engine(url or config.lire("DATABASE_URL"), pool_pre_ping=True)


class SchemaPasAJour(RuntimeError):
    """La base n'est pas à la dernière migration : le moteur refuse de démarrer."""


def configuration_alembic(url: str | None = None):
    """Configuration Alembic du projet, éventuellement pointée sur une autre base."""
    from alembic.config import Config

    reglages = Config(str(config.RACINE / "alembic.ini"))
    if url:
        reglages.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return reglages


def verifier_schema(moteur: Engine) -> None:
    """Vérifie que la base est à la dernière migration.

    On ne migre jamais au démarrage : appliquer une migration est une étape
    de déploiement explicite (uv run alembic upgrade head), pas un effet de bord.
    """
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    attendue = ScriptDirectory.from_config(configuration_alembic()).get_current_head()
    with moteur.connect() as connexion:
        actuelle = MigrationContext.configure(connexion).get_current_revision()
    if actuelle != attendue:
        raise SchemaPasAJour(
            f"La base est à la migration {actuelle or 'aucune'}, le moteur attend {attendue}. "
            "Lancez : uv run alembic upgrade head"
        )
