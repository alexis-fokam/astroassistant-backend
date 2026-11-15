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
    """Alerte issue d'une règle clinique ou d'un modèle (§9 alert).

    Cycle de vie : ouverte → acquittée par le CMO avec commentaire → résolue.
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

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    crew_member_id: Mapped[int] = mapped_column(
        ForeignKey("crew_members.id", ondelete="CASCADE"), comment="Membre concerné par l'alerte"
    )
    risk_score_id: Mapped[int | None] = mapped_column(
        ForeignKey("risk_scores.id", ondelete="SET NULL"), comment="Score qui a déclenché l'alerte"
    )
    recommended_protocol_id: Mapped[int | None] = mapped_column(
        ForeignKey("protocols.id", ondelete="SET NULL"), comment="Protocole proposé (F4)"
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True, comment="Simulation d'origine"
    )
    level: Mapped[AlertLevel] = mapped_column(
        enum_type(AlertLevel), comment="Gravité : info, warning, critical"
    )
    domain: Mapped[RiskDomain] = mapped_column(
        enum_type(RiskDomain), comment="Domaine de risque concerné"
    )
    domain_label: Mapped[str | None] = mapped_column(
        String(64),
        comment="Libellé clinique plus précis que le domaine (ex. Neuro-oculaire pour le SANS)",
    )
    method: Mapped[DetectionMethod] = mapped_column(
        enum_type(DetectionMethod),
        comment="Méthode de détection (seuil, z-score, Isolation Forest…)",
    )
    rule_code: Mapped[str | None] = mapped_column(
        String(64), comment="Règle YAML déclenchée (ex. HRV-01)"
    )
    status: Mapped[AlertStatus] = mapped_column(
        enum_type(AlertStatus), default=AlertStatus.OPEN, comment="Ouverte, acquittée ou résolue"
    )
    title: Mapped[str] = mapped_column(String(160), comment="Titre court")
    message: Mapped[str] = mapped_column(Text, comment="Message affiché à l'équipage")
    metric: Mapped[Metric | None] = mapped_column(enum_type(Metric), comment="Métrique en cause")
    observed_value: Mapped[float | None] = mapped_column(comment="Valeur observée")
    threshold: Mapped[float | None] = mapped_column(comment="Seuil franchi")
    factors: Mapped[list[Any]] = mapped_column(
        default=list, comment="Trois facteurs principaux (JSON, F2.7)"
    )
    triggered_at: Mapped[datetime] = mapped_column(default=utcnow, comment="Déclenchement (UTC)")
    acknowledged_at: Mapped[datetime | None] = mapped_column(comment="Acquittement (UTC)")
    acknowledged_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL"), comment="Médecin de bord qui a acquitté"
    )
    ack_comment: Mapped[str | None] = mapped_column(
        Text, comment="Commentaire d'acquittement (F9.2)"
    )
    resolved_at: Mapped[datetime | None] = mapped_column(comment="Résolution (UTC)")

    crew_member: Mapped[CrewMember] = relationship(
        back_populates="alerts", foreign_keys=[crew_member_id]
    )
    acknowledged_by: Mapped[CrewMember | None] = relationship(foreign_keys=[acknowledged_by_id])
    risk_score: Mapped[RiskScore | None] = relationship()
    recommended_protocol: Mapped[Protocol | None] = relationship()
    protocol_runs: Mapped[list[ProtocolRun]] = relationship(back_populates="alert")


class EmergencyEvent(Base):
    """Déclenchement du mode urgence (F12) : qui, pour qui, étapes suivies et clôture (U-04)."""

    __tablename__ = "emergency_events"
    __table_args__ = (
        CheckConstraint("status = 'active' OR closed_at IS NOT NULL", name="closed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    patient_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL"), index=True, comment="Membre en détresse"
    )
    triggered_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL"),
        comment="Membre qui a déclenché l'urgence",
    )
    closed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL"), comment="Médecin de bord qui a clôturé"
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True, comment="Simulation d'origine"
    )
    status: Mapped[EmergencyStatus] = mapped_column(
        enum_type(EmergencyStatus), default=EmergencyStatus.ACTIVE, comment="Active ou clôturée"
    )
    triggered_at: Mapped[datetime] = mapped_column(default=utcnow, comment="Déclenchement (UTC)")
    steps: Mapped[list[Any]] = mapped_column(
        default=list, comment="Étapes de premiers secours réalisées (JSON)"
    )
    outcome: Mapped[str | None] = mapped_column(
        String(32), comment="Issue : stabilisée, surveillance rapprochée, évacuation demandée"
    )
    closed_at: Mapped[datetime | None] = mapped_column(comment="Clôture (UTC)")
    summary: Mapped[str | None] = mapped_column(Text, comment="Compte rendu du médecin de bord")

    patient: Mapped[CrewMember | None] = relationship(foreign_keys=[patient_id])
    triggered_by: Mapped[CrewMember | None] = relationship(foreign_keys=[triggered_by_id])
    closed_by: Mapped[CrewMember | None] = relationship(foreign_keys=[closed_by_id])
