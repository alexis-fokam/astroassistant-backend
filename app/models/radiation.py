"""Dosimetry and space weather (spec F5, §9 radiation_dose)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, enum_type
from app.models.enums import DataSource, SpaceWeatherKind

if TYPE_CHECKING:
    from app.models.crew import CrewMember
    from app.models.datasets import DatasetSource


class SpaceWeatherEvent(Base):
    """Événement de météo spatiale : éruption, SPE, CME (F5.3, F5.4), réel (DONKI) ou simulé."""

    __tablename__ = "space_weather_events"
    __table_args__ = (
        CheckConstraint(
            "peak_proton_flux_pfu IS NULL OR peak_proton_flux_pfu >= 0", name="flux_positive"
        ),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="chronology"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("dataset_sources.id", ondelete="SET NULL"),
        index=True,
        comment="Jeu de données d'origine (vide si l'événement est simulé)",
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"),
        index=True,
        comment="Simulation qui rejoue l'événement",
    )
    kind: Mapped[SpaceWeatherKind] = mapped_column(
        enum_type(SpaceWeatherKind), comment="Type d'événement"
    )
    flare_class: Mapped[str | None] = mapped_column(
        String(8), comment="Classe d'éruption (ex. X8.2)"
    )
    donki_id: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        comment="Identifiant DONKI d'origine (ex. 2017-09-10T16:45:00-SEP-001)",
    )
    started_at: Mapped[datetime] = mapped_column(index=True, comment="Début de l'événement (UTC)")
    peak_at: Mapped[datetime | None] = mapped_column(comment="Pic de l'événement (UTC)")
    ended_at: Mapped[datetime | None] = mapped_column(comment="Fin de l'événement (UTC)")
    peak_proton_flux_pfu: Mapped[float | None] = mapped_column(
        comment="Flux maximal de protons ≥ 10 MeV (pfu)"
    )
    shelter_deadline_at: Mapped[datetime | None] = mapped_column(
        comment="Heure limite pour rejoindre l'abri (F5.4)"
    )
    description: Mapped[str | None] = mapped_column(Text, comment="Description ou note d'origine")

    source: Mapped[DatasetSource | None] = relationship()


class RadiationDose(Base):
    """Relevé dosimétrique d'un astronaute : débit et cumuls mission/carrière (F5.1, F5.2)."""

    __tablename__ = "radiation_doses"
    __table_args__ = (
        Index("ix_radiation_doses_crew_time", "crew_member_id", "recorded_at"),
        CheckConstraint(
            "dose_rate_msv_h >= 0 AND mission_cumulative_msv >= 0 "
            "AND career_cumulative_msv >= mission_cumulative_msv",
            name="dose_values",
        ),
        CheckConstraint(
            "neutron_fraction IS NULL OR (neutron_fraction BETWEEN 0 AND 1)", name="neutron_range"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    crew_member_id: Mapped[int] = mapped_column(
        ForeignKey("crew_members.id", ondelete="CASCADE"), comment="Membre porteur du dosimètre"
    )
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("space_weather_events.id", ondelete="SET NULL"),
        index=True,
        comment="Événement solaire en cours au moment du relevé",
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True, comment="Simulation d'origine"
    )
    recorded_at: Mapped[datetime] = mapped_column(comment="Instant du relevé (UTC)")
    dose_rate_msv_h: Mapped[float] = mapped_column(comment="Débit d'équivalent de dose (mSv/h)")
    mission_cumulative_msv: Mapped[float] = mapped_column(
        comment="Dose cumulée depuis le début de la mission (mSv)"
    )
    career_cumulative_msv: Mapped[float] = mapped_column(
        comment="Dose cumulée sur la carrière (mSv)"
    )
    neutron_fraction: Mapped[float | None] = mapped_column(
        comment="Part de la dose due aux neutrons, de 0 à 1 (≈ 0,3 sur l'ISS selon l'ASC)"
    )
    source: Mapped[DataSource] = mapped_column(
        enum_type(DataSource), default=DataSource.SENSOR, comment="Origine du relevé"
    )

    crew_member: Mapped[CrewMember] = relationship()
    event: Mapped[SpaceWeatherEvent | None] = relationship()
