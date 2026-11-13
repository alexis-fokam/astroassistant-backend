"""Données brutes : mesures des capteurs et check-in quotidien de l'équipage."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, enum_type, utcnow
from app.models.enums import DataSource, Metric

if TYPE_CHECKING:
    from app.models.crew import CrewMember, Device


class VitalReading(Base):
    """Une mesure horodatée (format long : une ligne = une valeur) — §9 ``vital_reading``.

    Table la plus volumineuse : l'index (crew_member_id, metric, recorded_at)
    sert les fenêtres glissantes du pipeline (§8.1) et les graphiques (F1.6).
    """

    __tablename__ = "vital_readings"
    __table_args__ = (
        Index("ix_vital_readings_crew_metric_time", "crew_member_id", "metric", "recorded_at"),
        CheckConstraint("quality IS NULL OR (quality BETWEEN 0 AND 1)", name="quality_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_member_id: Mapped[int] = mapped_column(ForeignKey("crew_members.id", ondelete="CASCADE"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id", ondelete="SET NULL"))
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )
    metric: Mapped[Metric] = mapped_column(enum_type(Metric))
    value: Mapped[float]
    quality: Mapped[float | None]  # indice de confiance du capteur, 0..1
    is_artifact: Mapped[bool] = mapped_column(default=False)  # écarté au nettoyage (§6.1)
    source: Mapped[DataSource] = mapped_column(enum_type(DataSource), default=DataSource.SENSOR)
    recorded_at: Mapped[datetime]  # instant de la mesure (horloge capteur)
    received_at: Mapped[datetime] = mapped_column(default=utcnow)  # instant d'ingestion

    crew_member: Mapped[CrewMember] = relationship(back_populates="readings")
    device: Mapped[Device | None] = relationship()


_SYMPTOMS = ("headache", "vision_change", "congestion", "back_pain", "nausea")
_SCALES = ("sleep_quality", "mood", "stress", "isolation", "energy")


class Checkin(Base):
    """Check-in qualitatif quotidien (F3, §9 ``checkin``).

    Symptômes en gravité 0..3 (aucun, léger, modéré, sévère) ; ressentis en échelle 0..10.
    ``vision_change`` est l'indice SANS (F3.2).
    """

    __tablename__ = "checkins"
    __table_args__ = (
        Index("ix_checkins_crew_time", "crew_member_id", "submitted_at"),
        *(
            CheckConstraint(f"{c} IS NULL OR ({c} BETWEEN 0 AND 3)", name=f"{c}_range")
            for c in _SYMPTOMS
        ),
        *(
            CheckConstraint(f"{c} IS NULL OR ({c} BETWEEN 0 AND 10)", name=f"{c}_range")
            for c in _SCALES
        ),
        CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0", name="duration_positive"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_member_id: Mapped[int] = mapped_column(ForeignKey("crew_members.id", ondelete="CASCADE"))
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )
    scheduled_for: Mapped[datetime | None]  # heure planifiée, pour le rappel (F3.5)
    submitted_at: Mapped[datetime] = mapped_column(default=utcnow)
    duration_seconds: Mapped[int | None]  # cible < 90 s (F3.1)

    headache: Mapped[int | None] = mapped_column(SmallInteger)
    vision_change: Mapped[int | None] = mapped_column(SmallInteger)
    congestion: Mapped[int | None] = mapped_column(SmallInteger)
    back_pain: Mapped[int | None] = mapped_column(SmallInteger)
    nausea: Mapped[int | None] = mapped_column(SmallInteger)

    sleep_quality: Mapped[int | None] = mapped_column(SmallInteger)
    mood: Mapped[int | None] = mapped_column(SmallInteger)
    stress: Mapped[int | None] = mapped_column(SmallInteger)
    isolation: Mapped[int | None] = mapped_column(SmallInteger)
    energy: Mapped[int | None] = mapped_column(SmallInteger)

    notes: Mapped[str | None] = mapped_column(Text)  # note libre optionnelle (F3.3)

    crew_member: Mapped[CrewMember] = relationship(back_populates="checkins")
