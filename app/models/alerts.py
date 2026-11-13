"""Alertes cliniques (F2, F9.2) et événements d'urgence (F12)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, enum_type, utcnow
from app.models.enums import (
    AlertLevel,
    AlertStatus,
    DetectionMethod,
    EmergencyStatus,
    Metric,
    RiskDomain,
)

if TYPE_CHECKING:
    from app.models.crew import CrewMember
    from app.models.protocols import Protocol, ProtocolRun
    from app.models.scoring import RiskScore


class Alert(Base):
    """Alerte issue d'une règle clinique ou d'un modèle (§9 ``alert``).

    Cycle de vie : open → acknowledged (par le CMO, avec commentaire) → resolved.
    La file du CMO se trie par gravité puis ancienneté (F9.2).
    """

    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_crew_status", "crew_member_id", "status"),
        Index("ix_alerts_queue", "status", "level", "triggered_at"),
        CheckConstraint(
            "status != 'acknowledged' OR acknowledged_at IS NOT NULL", name="ack_has_timestamp"
        ),
        CheckConstraint("status != 'resolved' OR resolved_at IS NOT NULL", name="resolved_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_member_id: Mapped[int] = mapped_column(ForeignKey("crew_members.id", ondelete="CASCADE"))
    risk_score_id: Mapped[int | None] = mapped_column(
        ForeignKey("risk_scores.id", ondelete="SET NULL")
    )
    recommended_protocol_id: Mapped[int | None] = mapped_column(
        ForeignKey("protocols.id", ondelete="SET NULL")
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )

    level: Mapped[AlertLevel] = mapped_column(enum_type(AlertLevel))
    domain: Mapped[RiskDomain] = mapped_column(enum_type(RiskDomain))
    method: Mapped[DetectionMethod] = mapped_column(enum_type(DetectionMethod))
    rule_code: Mapped[str | None] = mapped_column(String(64))  # règle YAML déclenchée
    status: Mapped[AlertStatus] = mapped_column(enum_type(AlertStatus), default=AlertStatus.OPEN)

    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text)
    metric: Mapped[Metric | None] = mapped_column(enum_type(Metric))
    observed_value: Mapped[float | None]
    threshold: Mapped[float | None]
    factors: Mapped[list[Any]] = mapped_column(default=list)  # 3 facteurs principaux (F2.7)

    triggered_at: Mapped[datetime] = mapped_column(default=utcnow)
    acknowledged_at: Mapped[datetime | None]
    acknowledged_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL")
    )
    ack_comment: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None]

    crew_member: Mapped[CrewMember] = relationship(
        back_populates="alerts", foreign_keys=[crew_member_id]
    )
    acknowledged_by: Mapped[CrewMember | None] = relationship(foreign_keys=[acknowledged_by_id])
    risk_score: Mapped[RiskScore | None] = relationship()
    recommended_protocol: Mapped[Protocol | None] = relationship()
    protocol_runs: Mapped[list[ProtocolRun]] = relationship(back_populates="alert")


class EmergencyEvent(Base):
    """Déclenchement du mode urgence (F12) : qui, pour qui, déroulé et clôture."""

    __tablename__ = "emergency_events"
    __table_args__ = (
        CheckConstraint("status = 'active' OR closed_at IS NOT NULL", name="closed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL"), index=True
    )
    triggered_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL")
    )
    closed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL")
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[EmergencyStatus] = mapped_column(
        enum_type(EmergencyStatus), default=EmergencyStatus.ACTIVE
    )
    triggered_at: Mapped[datetime] = mapped_column(default=utcnow)
    steps: Mapped[list[Any]] = mapped_column(default=list)  # étapes de premiers secours suivies
    closed_at: Mapped[datetime | None]
    summary: Mapped[str | None] = mapped_column(Text)

    patient: Mapped[CrewMember | None] = relationship(foreign_keys=[patient_id])
    triggered_by: Mapped[CrewMember | None] = relationship(foreign_keys=[triggered_by_id])
    closed_by: Mapped[CrewMember | None] = relationship(foreign_keys=[closed_by_id])
