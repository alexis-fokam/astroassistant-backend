"""Raw data: sensor readings and the crew's daily check-in."""

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
    """Mesure horodatée d'une constante, au format long : une ligne = une valeur (§9 vital_reading).

    Table la plus volumineuse : l'index (membre, métrique, instant) sert les fenêtres
    glissantes du pipeline (§8.1) et les graphiques (F1.6).
    """

    __tablename__ = "vital_readings"
    __table_args__ = (
        Index("ix_vital_readings_crew_metric_time", "crew_member_id", "metric", "recorded_at"),
        CheckConstraint("quality IS NULL OR (quality BETWEEN 0 AND 1)", name="quality_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    crew_member_id: Mapped[int] = mapped_column(
        ForeignKey("crew_members.id", ondelete="CASCADE"), comment="Membre mesuré"
    )
    device_id: Mapped[int | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"), comment="Capteur source"
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"),
        index=True,
        comment="Simulation qui a produit la mesure",
    )
    metric: Mapped[Metric] = mapped_column(
        enum_type(Metric), comment="Constante mesurée (unité fixée par la métrique)"
    )
    value: Mapped[float] = mapped_column(comment="Valeur mesurée")
    quality: Mapped[float | None] = mapped_column(
        comment="Indice de confiance du capteur, de 0 à 1"
    )
    is_artifact: Mapped[bool] = mapped_column(
        default=False, comment="Mesure écartée au nettoyage (§6.1)"
    )
    source: Mapped[DataSource] = mapped_column(
        enum_type(DataSource),
        default=DataSource.SENSOR,
        comment="Origine : capteur, simulateur, saisie, dataset",
    )
    recorded_at: Mapped[datetime] = mapped_column(
        comment="Instant de la mesure, horloge du capteur (UTC)"
    )
    received_at: Mapped[datetime] = mapped_column(
        default=utcnow, comment="Instant d'ingestion par l'API (UTC)"
    )

    crew_member: Mapped[CrewMember] = relationship(back_populates="readings")
    device: Mapped[Device | None] = relationship()


# Symptoms rated 0-3 (none, mild, moderate, severe) and self-rated scales 0-10 (spec F3.2).
# dizziness, skin_issue and crew_relations cover NASA HRP risks: sensorimotor/vestibular,
# host-microorganism interactions and inadequate teamwork.
_SYMPTOMS = (
    "headache",
    "vision_change",
    "congestion",
    "back_pain",
    "nausea",
    "dizziness",
    "skin_issue",
)
_SCALES = ("sleep_quality", "mood", "stress", "isolation", "energy", "crew_relations")


class Checkin(Base):
    """Check-in qualitatif quotidien (F3, §9 checkin) : symptômes de 0 à 3, ressentis de 0 à 10."""

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

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    crew_member_id: Mapped[int] = mapped_column(
        ForeignKey("crew_members.id", ondelete="CASCADE"), comment="Membre qui répond"
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True, comment="Simulation d'origine"
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(
        comment="Heure planifiée, pour le rappel (F3.5)"
    )
    submitted_at: Mapped[datetime] = mapped_column(
        default=utcnow, comment="Heure de validation (UTC)"
    )
    duration_seconds: Mapped[int | None] = mapped_column(
        comment="Durée de remplissage (objectif < 90 s, F3.1)"
    )

    headache: Mapped[int | None] = mapped_column(
        SmallInteger, comment="Maux de tête, de 0 (aucun) à 3 (sévère)"
    )
    vision_change: Mapped[int | None] = mapped_column(
        SmallInteger, comment="Vision floue ou modifiée, 0 à 3 (indice SANS)"
    )
    congestion: Mapped[int | None] = mapped_column(SmallInteger, comment="Congestion nasale, 0 à 3")
    back_pain: Mapped[int | None] = mapped_column(SmallInteger, comment="Douleurs dorsales, 0 à 3")
    nausea: Mapped[int | None] = mapped_column(SmallInteger, comment="Nausées, 0 à 3")
    dizziness: Mapped[int | None] = mapped_column(
        SmallInteger, comment="Vertiges ou troubles de l'équilibre, 0 à 3 (risque vestibulaire HRP)"
    )
    skin_issue: Mapped[int | None] = mapped_column(
        SmallInteger, comment="Éruption ou infection cutanée, 0 à 3 (risque micro-organismes HRP)"
    )

    sleep_quality: Mapped[int | None] = mapped_column(
        SmallInteger, comment="Qualité de sommeil ressentie, 0 à 10"
    )
    mood: Mapped[int | None] = mapped_column(SmallInteger, comment="Humeur, 0 à 10")
    stress: Mapped[int | None] = mapped_column(SmallInteger, comment="Niveau de stress, 0 à 10")
    isolation: Mapped[int | None] = mapped_column(
        SmallInteger, comment="Sentiment d'isolement, 0 à 10"
    )
    energy: Mapped[int | None] = mapped_column(SmallInteger, comment="Énergie, 0 à 10")
    crew_relations: Mapped[int | None] = mapped_column(
        SmallInteger,
        comment="Qualité des relations avec l'équipage, 0 à 10 (risque travail d'équipe HRP)",
    )

    notes: Mapped[str | None] = mapped_column(Text, comment="Note libre facultative (F3.3)")

    crew_member: Mapped[CrewMember] = relationship(back_populates="checkins")
