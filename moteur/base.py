"""Base de données : les factures et le journal de ce qui leur arrive.

Les tables :
- factures   : une ligne par document reçu, avec son état et ses données ;
- evenements : la piste d'audit. Chaque étape y ajoute une ligne, jamais modifiée ensuite ;
- consignes  : le texte exact de chaque version des consignes données à l'IA ;
- taches     : la file des lectures à faire, prises par le travailleur (moteur/travailleur.py) ;
- mails_recus : chaque mail reçu à l'adresse de dépôt, et ce qu'on a fait de ses pièces jointes ;
- connecteurs et appels_connecteurs : les logiciels branchés (MCP) et le journal de leurs appels ;
- demandes_oauth et jetons_connecteurs : les connexions par compte (OAuth), jetons chiffrés ;
- regles_approbation et approbations : qui doit approuver une facture, et qui l'a fait ;
- brouillon_circuit : le circuit en cours de modification dans l'éditeur, pas encore publié ;
- cles_api, abonnements et livraisons : l'API publique et les événements envoyés aux autres logiciels.

Toute modification de ces modèles demande une migration (dossier migrations/).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, create_engine, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from moteur import config


class Etat(StrEnum):
    RECUE = "recue"  # le fichier est arrivé
    EXTRAITE = "extraite"  # le LLM a rendu des données valides
    A_VALIDER = "a_valider"  # contrôles passés, une personne doit valider
    EN_APPROBATION = "en_approbation"  # approuvée à un niveau, d'autres niveaux doivent encore approuver
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
    # Qui doit approuver et pourquoi, calculé par les règles à la fin des contrôles (moteur/approbation.py).
    circuit: Mapped[dict | None] = mapped_column(JSONB)
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
    # Le texte d'un mail SANS facture (4 000 caractères au plus). Utile surtout pour le code de
    # confirmation qu'envoie Gmail ou Outlook quand on met en place la règle de transfert.
    texte: Mapped[str | None] = mapped_column(Text)


class ConnecteurBranche(Base):
    """Un connecteur du catalogue que l'entreprise a branché, avec les outils qu'elle autorise."""

    __tablename__ = "connecteurs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # identifiant du catalogue : odoo, hubspot…
    actif: Mapped[bool] = mapped_column(server_default=text("true"))
    # Outils autorisés. None : tous les outils de LECTURE du serveur. Une écriture n'est jamais autorisée d'office.
    outils_autorises: Mapped[list | None] = mapped_column(JSONB)
    branche_par: Mapped[str] = mapped_column(String(100))
    branche_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AppelConnecteur(Base):
    """Journal de chaque appel d'outil fait par l'assistant à un connecteur. Jamais modifié ensuite."""

    __tablename__ = "appels_connecteurs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    connecteur: Mapped[str] = mapped_column(String(40), index=True)
    outil: Mapped[str] = mapped_column(String(100))
    arguments: Mapped[dict] = mapped_column(JSONB, default=dict)
    statut: Mapped[str] = mapped_column(String(20))  # "ok", "erreur" ou "refuse"
    detail: Mapped[str | None] = mapped_column(Text)
    duree_ms: Mapped[int | None] = mapped_column(Integer)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())


class DemandeOAuth(Base):
    """Une connexion OAuth commencée : le navigateur est parti chez l'éditeur et doit revenir avec ce « state »."""

    __tablename__ = "demandes_oauth"

    etat: Mapped[str] = mapped_column(String(64), primary_key=True)  # le « state » OAuth, aléatoire
    connecteur: Mapped[str] = mapped_column(String(40))
    verificateur: Mapped[str] = mapped_column(Text)  # code_verifier PKCE, chiffré
    auteur: Mapped[str] = mapped_column(String(100))
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JetonConnecteur(Base):
    """Les jetons OAuth d'un connecteur, toujours chiffrés : la base seule ne permet pas de s'en servir."""

    __tablename__ = "jetons_connecteurs"

    connecteur: Mapped[str] = mapped_column(String(40), primary_key=True)
    acces: Mapped[str] = mapped_column(Text)
    renouvellement: Mapped[str | None] = mapped_column(Text)
    expire_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    modifie_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ReglesApprobation(Base):
    """Une version des règles d'approbation. Jamais modifiée : changer les règles publie une nouvelle version."""

    __tablename__ = "regles_approbation"

    version: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    regles: Mapped[list] = mapped_column(JSONB)
    # Les relances par niveau ({"comptable": {"delai_h": 48, ...}}). Absentes : les délais par défaut.
    relances: Mapped[dict | None] = mapped_column(JSONB)
    # Ce que cette version a changé, en phrases lisibles (publiée depuis l'éditeur). Absent avant l'éditeur.
    changements: Mapped[list | None] = mapped_column(JSONB)
    publie_par: Mapped[str] = mapped_column(String(100))
    publie_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BrouillonCircuit(Base):
    """Le circuit en cours de modification dans l'éditeur. Une seule ligne ; publier le vide.

    Il ne touche aucune facture : seules les versions publiées (regles_approbation) comptent.
    """

    __tablename__ = "brouillon_circuit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False, default=1)
    regles: Mapped[list] = mapped_column(JSONB)
    relances: Mapped[dict | None] = mapped_column(JSONB)
    modifie_par: Mapped[str] = mapped_column(String(100))
    modifie_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (CheckConstraint("id = 1", name="ck_brouillon_circuit_unique"),)


class Approbation(Base):
    """L'approbation d'une facture à un niveau, par une personne, sur des données précises."""

    __tablename__ = "approbations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    facture_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("factures.id"), index=True)
    niveau: Mapped[str] = mapped_column(String(40))
    personne: Mapped[str] = mapped_column(String(100))
    # Empreinte des données approuvées : si elles changent ensuite, l'approbation ne vaut plus.
    empreinte_donnees: Mapped[str] = mapped_column(String(64))
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())

    __table_args__ = (UniqueConstraint("facture_id", "niveau", name="uq_approbations_facture_niveau"),)


class CleApi(Base):
    """Une clé d'accès à l'API publique. Seule son empreinte est gardée : la clé n'est montrée qu'une fois."""

    __tablename__ = "cles_api"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(String(100))  # à quoi elle sert : « Make », « Logiciel de paie »…
    prefixe: Mapped[str] = mapped_column(String(16), unique=True)  # début visible de la clé, pour la reconnaître
    empreinte: Mapped[str] = mapped_column(String(64))  # SHA-256 de la clé complète
    droits: Mapped[list] = mapped_column(JSONB)  # « factures:lire », « factures:deposer »
    creee_par: Mapped[str] = mapped_column(String(100))
    creee_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    utilisee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoquee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Abonnement(Base):
    """Une adresse web à prévenir quand certains événements arrivent aux factures (webhook)."""

    __tablename__ = "abonnements"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    url: Mapped[str] = mapped_column(Text)
    evenements: Mapped[list] = mapped_column(JSONB)  # « facture.validee », « facture.rejetee »…
    secret: Mapped[str] = mapped_column(Text)  # secret de signature des envois, chiffré
    actif: Mapped[bool] = mapped_column(server_default=text("true"))
    cree_par: Mapped[str] = mapped_column(String(100))
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Livraison(Base):
    """Un événement à livrer à un abonnement. Préparé dans la même transaction que le changement
    de la facture : il ne peut pas être perdu, ni annoncer un changement qui n'a pas eu lieu."""

    __tablename__ = "livraisons"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    abonnement_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("abonnements.id"), index=True)
    evenement: Mapped[str] = mapped_column(String(40))
    charge: Mapped[dict] = mapped_column(JSONB)
    etat: Mapped[str] = mapped_column(String(20), server_default="en_attente")  # en_attente, livree, abandonnee
    tentatives: Mapped[int] = mapped_column(Integer, server_default="0")
    prochain_essai_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    derniere_reponse: Mapped[str | None] = mapped_column(Text)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    livree_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("ix_livraisons_a_faire", "prochain_essai_le", postgresql_where=text("etat = 'en_attente'")),)


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


class MembreEquipe(Base):
    """Une personne de l'entreprise qui approuve les factures à un niveau (comptable, directeur financier, gérant)."""

    __tablename__ = "membres_equipe"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    nom: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(320))
    niveau: Mapped[str] = mapped_column(String(40))
    cree_par: Mapped[str] = mapped_column(String(100))
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("email", "niveau", name="uq_membres_equipe_email_niveau"),)
