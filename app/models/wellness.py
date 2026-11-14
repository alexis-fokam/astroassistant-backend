"""Countermeasures and daily life: exercise (F6), sleep (F7), vigilance PVT (F8),
nutrition and hydration (F13)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, enum_type, utcnow
from app.models.enums import DataSource, ExerciseIntensity, ExerciseKind, IntakeKind, SessionStatus

if TYPE_CHECKING:
    from app.models.crew import CrewMember


class ExerciseSession(Base):
    """Séance d'exercice planifiée puis réalisée ou manquée (F6.1, §9 exercise_session)."""

    __tablename__ = "exercise_sessions"
    __table_args__ = (
        Index("ix_exercise_sessions_crew_time", "crew_member_id", "scheduled_at"),
        CheckConstraint("duration_min IS NULL OR duration_min > 0", name="duration_positive"),
        CheckConstraint("avg_heart_rate IS NULL OR avg_heart_rate > 0", name="hr_positive"),
        CheckConstraint(
            "status != 'completed' OR duration_min IS NOT NULL", name="completed_has_duration"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    crew_member_id: Mapped[int] = mapped_column(
        ForeignKey("crew_members.id", ondelete="CASCADE"), comment="Membre concerné"
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True, comment="Simulation d'origine"
    )
    kind: Mapped[ExerciseKind] = mapped_column(
        enum_type(ExerciseKind), comment="Appareil : résistance ARED, tapis T2, vélo CEVIS"
    )
    status: Mapped[SessionStatus] = mapped_column(
        enum_type(SessionStatus),
        default=SessionStatus.PLANNED,
        comment="Planifiée, réalisée ou manquée",
    )
    scheduled_at: Mapped[datetime] = mapped_column(comment="Créneau planifié (UTC)")
    started_at: Mapped[datetime | None] = mapped_column(comment="Début réel (UTC)")
    duration_min: Mapped[int | None] = mapped_column(comment="Durée réalisée en minutes")
    intensity: Mapped[ExerciseIntensity | None] = mapped_column(
        enum_type(ExerciseIntensity), comment="Intensité de la séance"
    )
    avg_heart_rate: Mapped[float | None] = mapped_column(
        comment="Fréquence cardiaque moyenne (bpm)"
    )
    notes: Mapped[str | None] = mapped_column(Text, comment="Commentaire")

    crew_member: Mapped[CrewMember] = relationship()


class SleepSession(Base):
    """Période de sommeil mesurée ou déclarée (F7.1, §9 sleep_session)."""

    __tablename__ = "sleep_sessions"
    __table_args__ = (
        Index("ix_sleep_sessions_crew_time", "crew_member_id", "started_at"),
        CheckConstraint("ended_at > started_at", name="chronology"),
        CheckConstraint("quality IS NULL OR (quality BETWEEN 0 AND 100)", name="quality_range"),
        CheckConstraint("awakenings IS NULL OR awakenings >= 0", name="awakenings_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    crew_member_id: Mapped[int] = mapped_column(
        ForeignKey("crew_members.id", ondelete="CASCADE"), comment="Membre concerné"
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True, comment="Simulation d'origine"
    )
    started_at: Mapped[datetime] = mapped_column(comment="Endormissement (UTC)")
    ended_at: Mapped[datetime] = mapped_column(comment="Réveil (UTC)")
    quality: Mapped[int | None] = mapped_column(SmallInteger, comment="Score de sommeil, 0 à 100")
    awakenings: Mapped[int | None] = mapped_column(SmallInteger, comment="Nombre de réveils")
    latency_min: Mapped[int | None] = mapped_column(comment="Délai d'endormissement en minutes")
    source: Mapped[DataSource] = mapped_column(
        enum_type(DataSource),
        default=DataSource.SENSOR,
        comment="Origine : capteur, saisie, simulateur",
    )

    crew_member: Mapped[CrewMember] = relationship()


class PvtResult(Base):
    """Résultat d'un test de vigilance psychomotrice de 3 minutes (F8, §9 pvt_result)."""

    __tablename__ = "pvt_results"
    __table_args__ = (
        Index("ix_pvt_results_crew_time", "crew_member_id", "taken_at"),
        CheckConstraint(
            "median_rt_ms > 0 AND lapses >= 0 AND false_starts >= 0 AND stimuli_count > 0",
            name="pvt_values",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    crew_member_id: Mapped[int] = mapped_column(
        ForeignKey("crew_members.id", ondelete="CASCADE"), comment="Membre testé"
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True, comment="Simulation d'origine"
    )
    taken_at: Mapped[datetime] = mapped_column(default=utcnow, comment="Date du test (UTC)")
    duration_seconds: Mapped[int] = mapped_column(
        default=180, comment="Durée du test en secondes (F8.1)"
    )
    stimuli_count: Mapped[int] = mapped_column(comment="Nombre de stimuli présentés")
    median_rt_ms: Mapped[float] = mapped_column(comment="Temps de réaction médian (ms)")
    lapses: Mapped[int] = mapped_column(comment="Inattentions : réactions de plus de 500 ms (F8.2)")
    false_starts: Mapped[int] = mapped_column(default=0, comment="Réponses avant le stimulus")

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

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    crew_member_id: Mapped[int] = mapped_column(
        ForeignKey("crew_members.id", ondelete="CASCADE"), comment="Membre concerné"
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True, comment="Simulation d'origine"
    )
    logged_at: Mapped[datetime] = mapped_column(default=utcnow, comment="Heure de la prise (UTC)")
    kind: Mapped[IntakeKind] = mapped_column(
        enum_type(IntakeKind), comment="Repas, collation ou eau"
    )
    portion_code: Mapped[str | None] = mapped_column(
        String(64), comment="Portion prédéfinie (ex. main_dish)"
    )
    energy_kcal: Mapped[float | None] = mapped_column(comment="Apport énergétique (kcal)")
    water_ml: Mapped[float | None] = mapped_column(comment="Volume d'eau (ml)")

    crew_member: Mapped[CrewMember] = relationship()
