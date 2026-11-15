"""Sorties du pipeline IA : indicateurs calculés et scores de risque par domaine."""

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
    """Indicateurs agrégés sur une fenêtre (moyennes, pentes, z-scores) à un passage du pipeline."""

    __tablename__ = "feature_snapshots"
    __table_args__ = (
        Index("ix_feature_snapshots_crew_time", "crew_member_id", "computed_at"),
        CheckConstraint("window_end >= window_start", name="window_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    crew_member_id: Mapped[int] = mapped_column(
        ForeignKey("crew_members.id", ondelete="CASCADE"), comment="Membre concerné"
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True, comment="Simulation d'origine"
    )
    computed_at: Mapped[datetime] = mapped_column(default=utcnow, comment="Date du calcul (UTC)")
    window_start: Mapped[datetime] = mapped_column(comment="Début de la fenêtre analysée (UTC)")
    window_end: Mapped[datetime] = mapped_column(comment="Fin de la fenêtre analysée (UTC)")
    features: Mapped[dict[str, Any]] = mapped_column(
        comment='Indicateurs calculés (JSON), ex. {"heart_rate": {"mean": 74, "z": 1.3}}'
    )

    crew_member: Mapped[CrewMember] = relationship()


class RiskScore(Base):
    """Score de risque 0-100 d'un domaine à un instant (F2.5, F2.6, §9 risk_score).

    Plus le score est haut, plus le risque est élevé. Le domaine GLOBAL porte l'agrégation ;
    son niveau peut être forcé par un domaine critique (règle « max-severity »).
    """

    __tablename__ = "risk_scores"
    __table_args__ = (
        Index("ix_risk_scores_crew_domain_time", "crew_member_id", "domain", "computed_at"),
        CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
        CheckConstraint(
            "anomaly_score IS NULL OR (anomaly_score BETWEEN 0 AND 1)", name="anomaly_range"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    crew_member_id: Mapped[int] = mapped_column(
        ForeignKey("crew_members.id", ondelete="CASCADE"), comment="Membre concerné"
    )
    feature_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("feature_snapshots.id", ondelete="SET NULL"),
        comment="Indicateurs ayant servi au calcul",
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True, comment="Simulation d'origine"
    )
    computed_at: Mapped[datetime] = mapped_column(default=utcnow, comment="Date du calcul (UTC)")
    domain: Mapped[RiskDomain] = mapped_column(
        enum_type(RiskDomain), comment="Domaine de risque ou GLOBAL"
    )
    score: Mapped[float] = mapped_column(
        comment="Score de risque de 0 à 100 (0-39 NOMINAL, 40-69 WARNING, 70-100 CRITICAL)"
    )
    level: Mapped[HealthLevel] = mapped_column(
        enum_type(HealthLevel), comment="Niveau déduit du score"
    )
    anomaly_score: Mapped[float | None] = mapped_column(
        comment="Sortie normalisée de l'Isolation Forest, 0 à 1"
    )
    factors: Mapped[list[Any]] = mapped_column(
        default=list,
        comment="Facteurs explicatifs (JSON) : indicateur, valeur, baseline, contribution (F2.7)",
    )
    model_version: Mapped[str | None] = mapped_column(
        String(32), comment="Version du modèle utilisé"
    )

    crew_member: Mapped[CrewMember] = relationship()
    feature_snapshot: Mapped[FeatureSnapshot | None] = relationship()
