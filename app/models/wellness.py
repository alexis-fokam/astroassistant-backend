"""Contre-mesures et hygiène de vie : exercice (F6), sommeil (F7), vigilance PVT (F8),
nutrition et hydratation (F13)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, enum_type, utcnow
from app.models.enums import (
    DataSource,
    ExerciseIntensity,
    ExerciseKind,
    IntakeKind,
    SessionStatus,
)

if TYPE_CHECKING:
    from app.models.crew import CrewMember


class ExerciseSession(Base):
    """Séance d'exercice planifiée puis réalisée ou manquée (F6.1, §9 ``exercise_session``).

    Les séances ``missed`` consécutives déclenchent l'alerte de rattrapage (F6.3).
    """

    __tablename__ = "exercise_sessions"
    __table_args__ = (
        Index("ix_exercise_sessions_crew_time", "crew_member_id", "scheduled_at"),
        CheckConstraint("duration_min IS NULL OR duration_min > 0", name="duration_positive"),
        CheckConstraint("avg_heart_rate IS NULL OR avg_heart_rate > 0", name="hr_positive"),
        CheckConstraint(
            "status != 'completed' OR duration_min IS NOT NULL", name="completed_has_duration"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_member_id: Mapped[int] = mapped_column(ForeignKey("crew_members.id", ondelete="CASCADE"))
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[ExerciseKind] = mapped_column(enum_type(ExerciseKind))
    status: Mapped[SessionStatus] = mapped_column(
        enum_type(SessionStatus), default=SessionStatus.PLANNED
    )
    scheduled_at: Mapped[datetime]
    started_at: Mapped[datetime | None]
    duration_min: Mapped[int | None]
    intensity: Mapped[ExerciseIntensity | None] = mapped_column(enum_type(ExerciseIntensity))
    avg_heart_rate: Mapped[float | None]
    notes: Mapped[str | None] = mapped_column(Text)

    crew_member: Mapped[CrewMember] = relationship()


class SleepSession(Base):
    """Période de sommeil (F7.1, §9 ``sleep_session``)."""

    __tablename__ = "sleep_sessions"
    __table_args__ = (
        Index("ix_sleep_sessions_crew_time", "crew_member_id", "started_at"),
        CheckConstraint("ended_at > started_at", name="chronology"),
        CheckConstraint("quality IS NULL OR (quality BETWEEN 0 AND 100)", name="quality_range"),
        CheckConstraint("awakenings IS NULL OR awakenings >= 0", name="awakenings_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_member_id: Mapped[int] = mapped_column(ForeignKey("crew_members.id", ondelete="CASCADE"))
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime]
    quality: Mapped[int | None] = mapped_column(SmallInteger)  # score de sommeil 0..100
    awakenings: Mapped[int | None] = mapped_column(SmallInteger)
    latency_min: Mapped[int | None]  # délai d'endormissement
    source: Mapped[DataSource] = mapped_column(enum_type(DataSource), default=DataSource.SENSOR)

    crew_member: Mapped[CrewMember] = relationship()


class PvtResult(Base):
    """Résultat d'un test de vigilance psychomotrice (F8, §9 ``pvt_result``)."""

    __tablename__ = "pvt_results"
    __table_args__ = (
        Index("ix_pvt_results_crew_time", "crew_member_id", "taken_at"),
        CheckConstraint(
            "median_rt_ms > 0 AND lapses >= 0 AND false_starts >= 0 AND stimuli_count > 0",
            name="pvt_values",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_member_id: Mapped[int] = mapped_column(ForeignKey("crew_members.id", ondelete="CASCADE"))
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )
    taken_at: Mapped[datetime] = mapped_column(default=utcnow)
    duration_seconds: Mapped[int] = mapped_column(default=180)  # test court de 3 min (F8.1)
    stimuli_count: Mapped[int]
    median_rt_ms: Mapped[float]
    lapses: Mapped[int]  # temps de réaction > 500 ms (F8.2)
    false_starts: Mapped[int] = mapped_column(default=0)

    crew_member: Mapped[CrewMember] = relationship()


class IntakeLog(Base):
    """Saisie rapide d'un repas ou d'une prise d'eau en portions prédéfinies (F13.1)."""

    __tablename__ = "intake_logs"
    __table_args__ = (
        Index("ix_intake_logs_crew_time", "crew_member_id", "logged_at"),
        CheckConstraint(
            "(energy_kcal IS NULL OR energy_kcal >= 0) AND (water_ml IS NULL OR water_ml >= 0)",
            name="intake_values",
        ),
        CheckConstraint("kind != 'water' OR water_ml IS NOT NULL", name="water_has_volume"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_member_id: Mapped[int] = mapped_column(ForeignKey("crew_members.id", ondelete="CASCADE"))
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )
    logged_at: Mapped[datetime] = mapped_column(default=utcnow)
    kind: Mapped[IntakeKind] = mapped_column(enum_type(IntakeKind))
    portion_code: Mapped[str | None] = mapped_column(String(64))  # ex. « main_dish »
    energy_kcal: Mapped[float | None]
    water_ml: Mapped[float | None]

    crew_member: Mapped[CrewMember] = relationship()
