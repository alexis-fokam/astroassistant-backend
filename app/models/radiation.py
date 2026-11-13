"""Dosimétrie et météo spatiale (F5, §9 ``radiation_dose``)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, enum_type
from app.models.enums import DataSource, SpaceWeatherKind

if TYPE_CHECKING:
    from app.models.crew import CrewMember


class SpaceWeatherEvent(Base):
    """Événement de météo spatiale : éruption, SPE, CME (F5.3, F5.4).

    Les événements rejoués depuis la base DONKI gardent leur identifiant d'origine.
    """

    __tablename__ = "space_weather_events"
    __table_args__ = (
        CheckConstraint(
            "peak_proton_flux_pfu IS NULL OR peak_proton_flux_pfu >= 0", name="flux_positive"
        ),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="chronology"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[SpaceWeatherKind] = mapped_column(enum_type(SpaceWeatherKind))
    flare_class: Mapped[str | None] = mapped_column(String(8))  # ex. « X8.2 »
    donki_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    started_at: Mapped[datetime] = mapped_column(index=True)
    peak_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]
    peak_proton_flux_pfu: Mapped[float | None]  # protons ≥ 10 MeV
    shelter_deadline_at: Mapped[datetime | None]  # compte à rebours d'abri (F5.4)
    description: Mapped[str | None] = mapped_column(Text)


class RadiationDose(Base):
    """Relevé dosimétrique d'un astronaute : débit courant et cumuls (F5.1, F5.2)."""

    __tablename__ = "radiation_doses"
    __table_args__ = (
        Index("ix_radiation_doses_crew_time", "crew_member_id", "recorded_at"),
        CheckConstraint(
            "dose_rate_msv_h >= 0 AND mission_cumulative_msv >= 0 "
            "AND career_cumulative_msv >= mission_cumulative_msv",
            name="dose_values",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_member_id: Mapped[int] = mapped_column(ForeignKey("crew_members.id", ondelete="CASCADE"))
    event_id: Mapped[int | None] = mapped_column(
        ForeignKey("space_weather_events.id", ondelete="SET NULL"), index=True
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )
    recorded_at: Mapped[datetime]
    dose_rate_msv_h: Mapped[float]
    mission_cumulative_msv: Mapped[float]
    career_cumulative_msv: Mapped[float]
    source: Mapped[DataSource] = mapped_column(enum_type(DataSource), default=DataSource.SENSOR)

    crew_member: Mapped[CrewMember] = relationship()
    event: Mapped[SpaceWeatherEvent | None] = relationship()
