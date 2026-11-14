"""Base de données : les factures et le journal de ce qui leur arrive.

Deux tables :
- factures   : une ligne par document reçu, avec son état et ses données ;
- evenements : la piste d'audit. Chaque étape y ajoute une ligne, jamais modifiée ensuite.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, String, create_engine, func
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
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    facture: Mapped[FactureEnBase] = relationship(back_populates="evenements")


def creer_moteur(url: str | None = None) -> Engine:
    return create_engine(url or config.lire("DATABASE_URL"), pool_pre_ping=True)


def creer_tables(moteur: Engine) -> None:
    Base.metadata.create_all(moteur)
