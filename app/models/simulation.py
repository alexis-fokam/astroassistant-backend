"""Simulateur de télémétrie et mode démo jury (F15).

Toute donnée produite pendant une simulation porte ``sim_run_id`` :
supprimer un SimRun purge en cascade ses mesures, scores, alertes, paquets, etc.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_type, utcnow
from app.models.crew import CrewMember
from app.models.enums import HealthLevel, SimRunStatus


class SimScenario(TimestampMixin, Base):
    """Scénario rejouable (S1 à S6, §4.1) et réaction attendue du système (§13)."""

    __tablename__ = "sim_scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)  # « S1 » … « S6 »
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    expected_level: Mapped[HealthLevel | None] = mapped_column(enum_type(HealthLevel))
    expected_protocol_code: Mapped[str | None] = mapped_column(String(64))
    duration_seconds: Mapped[int]
    parameters: Mapped[dict[str, Any]] = mapped_column(default=dict)  # courbes, bruit, événements

    runs: Mapped[list[SimRun]] = relationship(back_populates="scenario")


class SimRun(Base):
    """Exécution d'un scénario, rejouable à l'identique grâce à la graine (F15.4)."""

    __tablename__ = "sim_runs"
    __table_args__ = (
        CheckConstraint("speed_factor BETWEEN 1 AND 1000", name="speed_range"),  # F15.2
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="chronology"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[int] = mapped_column(
        ForeignKey("sim_scenarios.id", ondelete="CASCADE"), index=True
    )
    crew_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="CASCADE"), index=True
    )  # NULL = tout l'équipage (ex. S3, événement solaire)
    status: Mapped[SimRunStatus] = mapped_column(
        enum_type(SimRunStatus), default=SimRunStatus.RUNNING
    )
    seed: Mapped[int] = mapped_column(default=42)
    speed_factor: Mapped[float] = mapped_column(default=1.0)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    ended_at: Mapped[datetime | None]

    scenario: Mapped[SimScenario] = relationship(back_populates="runs")
    crew_member: Mapped[CrewMember | None] = relationship()
