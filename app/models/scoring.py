"""Sorties du pipeline IA : features calculées et scores de risque par domaine."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, enum_type, utcnow
from app.models.enums import HealthLevel, RiskDomain

if TYPE_CHECKING:
    from app.models.crew import CrewMember


class FeatureSnapshot(Base):
    """Features agrégées sur une fenêtre (moyennes, pentes, z-scores…) à un tick du pipeline."""

    __tablename__ = "feature_snapshots"
    __table_args__ = (
        Index("ix_feature_snapshots_crew_time", "crew_member_id", "computed_at"),
        CheckConstraint("window_end >= window_start", name="window_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_member_id: Mapped[int] = mapped_column(ForeignKey("crew_members.id", ondelete="CASCADE"))
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )
    computed_at: Mapped[datetime] = mapped_column(default=utcnow)
    window_start: Mapped[datetime]
    window_end: Mapped[datetime]
    # ex. {"heart_rate": {"mean": 74.2, "z": 1.3, "slope": 0.4}, "sleep_debt_h": 5.5, ...}
    features: Mapped[dict[str, Any]]

    crew_member: Mapped[CrewMember] = relationship()


class RiskScore(Base):
    """Score de risque 0..100 d'un domaine à un tick (F2.5, F2.6, §9 ``risk_score``).

    Plus le score est haut, plus le risque est élevé (0-39 NOMINAL, 40-69 WARNING,
    70-100 CRITICAL). Le domaine GLOBAL porte l'agrégation pondérée ; son niveau
    peut être forcé par un domaine critique (règle « max-severity »).
    """

    __tablename__ = "risk_scores"
    __table_args__ = (
        Index("ix_risk_scores_crew_domain_time", "crew_member_id", "domain", "computed_at"),
        CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
        CheckConstraint(
            "anomaly_score IS NULL OR (anomaly_score BETWEEN 0 AND 1)", name="anomaly_range"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_member_id: Mapped[int] = mapped_column(ForeignKey("crew_members.id", ondelete="CASCADE"))
    feature_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("feature_snapshots.id", ondelete="SET NULL")
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )
    computed_at: Mapped[datetime] = mapped_column(default=utcnow)

    domain: Mapped[RiskDomain] = mapped_column(enum_type(RiskDomain))
    score: Mapped[float]
    level: Mapped[HealthLevel] = mapped_column(enum_type(HealthLevel))
    anomaly_score: Mapped[float | None]  # sortie Isolation Forest normalisée, 0..1
    # Facteurs explicatifs (F2.7) :
    # [{"feature": "hrv_rmssd", "value": 31, "baseline": 48, "contribution": 0.42}, ...]
    factors: Mapped[list[Any]] = mapped_column(default=list)
    model_version: Mapped[str | None] = mapped_column(String(32))

    crew_member: Mapped[CrewMember] = relationship()
    feature_snapshot: Mapped[FeatureSnapshot | None] = relationship()
