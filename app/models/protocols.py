"""Protocoles de contre-mesures (F4) : registre des versions, matériel requis, exécutions.

Le contenu des protocoles (déclencheur, étapes, critère de sortie) vit dans les
fichiers YAML de ``app/protocols/`` ; la table ``protocols`` garde la trace de la
version chargée, pour que chaque exécution reste rattachée au texte exact suivi.
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

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), index=True)  # ex. « PRT-STRESS-01 »
    version: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[RiskDomain | None] = mapped_column(enum_type(RiskDomain))
    severity: Mapped[AlertLevel] = mapped_column(enum_type(AlertLevel))
    expected_duration_min: Mapped[int | None]
    file_path: Mapped[str] = mapped_column(String(255))
    checksum: Mapped[str] = mapped_column(String(64))  # SHA-256 du YAML chargé
    is_active: Mapped[bool] = mapped_column(default=True)
    loaded_at: Mapped[datetime] = mapped_column(default=utcnow)

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

    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("protocols.id", ondelete="CASCADE"))
    item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[float] = mapped_column(default=1)
    is_optional: Mapped[bool] = mapped_column(default=False)

    protocol: Mapped[Protocol] = relationship(back_populates="requirements")
    item: Mapped[InventoryItem] = relationship()


class ProtocolRun(Base):
    """Exécution d'un protocole par un astronaute (F4.5, §9 ``protocol_run``).

    ``steps`` suit l'avancement étape par étape :
    ``[{"code": "breathing", "done_at": "2026-10-13T14:12:00Z"}, ...]``.
    ``efficacy`` est réévaluée après le protocole (0 = sans effet, 1 = objectif atteint).
    """

    __tablename__ = "protocol_runs"
    __table_args__ = (
        Index("ix_protocol_runs_crew_status", "crew_member_id", "status"),
        CheckConstraint("efficacy IS NULL OR (efficacy BETWEEN 0 AND 1)", name="efficacy_range"),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="chronology"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    protocol_id: Mapped[int] = mapped_column(ForeignKey("protocols.id", ondelete="RESTRICT"))
    alert_id: Mapped[int | None] = mapped_column(
        ForeignKey("alerts.id", ondelete="SET NULL"), index=True
    )
    crew_member_id: Mapped[int] = mapped_column(ForeignKey("crew_members.id", ondelete="CASCADE"))
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[ProtocolRunStatus] = mapped_column(
        enum_type(ProtocolRunStatus), default=ProtocolRunStatus.IN_PROGRESS
    )
    steps: Mapped[list[Any]] = mapped_column(default=list)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    ended_at: Mapped[datetime | None]
    efficacy: Mapped[float | None]

    protocol: Mapped[Protocol] = relationship()
    alert: Mapped[Alert | None] = relationship(back_populates="protocol_runs")
    crew_member: Mapped[CrewMember] = relationship()
