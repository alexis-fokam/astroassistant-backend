"""Protocoles de contre-mesure (F4) : registre des versions, matériel requis, exécutions.

Le contenu d'un protocole (déclencheur, étapes, critère de sortie) est dans les YAML de
``app/protocols/`` ; la table ``protocols`` garde la version chargée, pour que chaque
exécution reste liée au texte exact qui a été suivi.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, enum_type, utcnow
from app.models.enums import AlertLevel, ProtocolRunStatus, RiskDomain

if TYPE_CHECKING:
    from app.models.alerts import Alert
    from app.models.crew import CrewMember
    from app.models.medical import InventoryItem


class Protocol(Base):
    """Version chargée d'un protocole de la bibliothèque (F4.1)."""

    __tablename__ = "protocols"
    __table_args__ = (
        UniqueConstraint("code", "version"),
        CheckConstraint(
            "expected_duration_min IS NULL OR expected_duration_min > 0", name="duration_positive"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    code: Mapped[str] = mapped_column(
        String(64), index=True, comment="Code du protocole (ex. PRT-STRESS-01)"
    )
    version: Mapped[str] = mapped_column(String(16), comment="Version du fichier YAML")
    title: Mapped[str] = mapped_column(String(160), comment="Titre affiché")
    description: Mapped[str | None] = mapped_column(Text, comment="Résumé du protocole")
    domain: Mapped[RiskDomain | None] = mapped_column(
        enum_type(RiskDomain), comment="Domaine de risque traité"
    )
    severity: Mapped[AlertLevel] = mapped_column(
        enum_type(AlertLevel), comment="Gravité pour laquelle il est conçu"
    )
    expected_duration_min: Mapped[int | None] = mapped_column(comment="Durée prévue en minutes")
    file_path: Mapped[str] = mapped_column(String(255), comment="Chemin du fichier YAML source")
    checksum: Mapped[str] = mapped_column(
        String(64), comment="Empreinte SHA-256 du fichier YAML chargé"
    )
    is_active: Mapped[bool] = mapped_column(default=True, comment="Version utilisable")
    loaded_at: Mapped[datetime] = mapped_column(default=utcnow, comment="Date de chargement (UTC)")

    requirements: Mapped[list[ProtocolRequirement]] = relationship(
        back_populates="protocol", cascade="all, delete-orphan", passive_deletes=True
    )


class ProtocolRequirement(Base):
    """Matériel de la pharmacie nécessaire à un protocole, vérifié avant exécution (F11.2)."""

    __tablename__ = "protocol_requirements"
    __table_args__ = (
        UniqueConstraint("protocol_id", "item_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    protocol_id: Mapped[int] = mapped_column(
        ForeignKey("protocols.id", ondelete="CASCADE"), comment="Protocole concerné"
    )
    item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="CASCADE"),
        index=True,
        comment="Article de pharmacie requis",
    )
    quantity: Mapped[float] = mapped_column(default=1, comment="Quantité nécessaire")
    is_optional: Mapped[bool] = mapped_column(default=False, comment="Matériel facultatif")

    protocol: Mapped[Protocol] = relationship(back_populates="requirements")
    item: Mapped[InventoryItem] = relationship()


class ProtocolRun(Base):
    """Exécution d'un protocole par un astronaute, étape par étape (F4.5, §9 protocol_run)."""

    __tablename__ = "protocol_runs"
    __table_args__ = (
        Index("ix_protocol_runs_crew_status", "crew_member_id", "status"),
        CheckConstraint("efficacy IS NULL OR (efficacy BETWEEN 0 AND 1)", name="efficacy_range"),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="chronology"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    protocol_id: Mapped[int] = mapped_column(
        ForeignKey("protocols.id", ondelete="RESTRICT"), comment="Version du protocole suivie"
    )
    alert_id: Mapped[int | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="SET NULL"),
        index=True,
        comment="Alerte qui a déclenché le protocole",
    )
    crew_member_id: Mapped[int] = mapped_column(
        ForeignKey("crew_members.id", ondelete="CASCADE"), comment="Membre qui exécute"
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True, comment="Simulation d'origine"
    )
    status: Mapped[ProtocolRunStatus] = mapped_column(
        enum_type(ProtocolRunStatus),
        default=ProtocolRunStatus.IN_PROGRESS,
        comment="En cours, terminé ou abandonné",
    )
    steps: Mapped[list[Any]] = mapped_column(
        default=list, comment="Avancement (JSON) : code de chaque étape et heure de validation"
    )
    started_at: Mapped[datetime] = mapped_column(default=utcnow, comment="Début (UTC)")
    ended_at: Mapped[datetime | None] = mapped_column(comment="Fin (UTC)")
    efficacy: Mapped[float | None] = mapped_column(
        comment="Efficacité réévaluée après le protocole, de 0 à 1"
    )

    protocol: Mapped[Protocol] = relationship()
    alert: Mapped[Alert | None] = relationship(back_populates="protocol_runs")
    crew_member: Mapped[CrewMember] = relationship()
