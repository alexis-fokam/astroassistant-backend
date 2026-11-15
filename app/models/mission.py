"""Configuration de la mission (premier lancement A-03) : destination, durée, latence."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_type
from app.models.enums import MissionDestination

if TYPE_CHECKING:
    from app.models.crew import CrewMember


class Mission(TimestampMixin, Base):
    """Mission configurée sur l'appareil ; une seule mission active à la fois."""

    __tablename__ = "missions"
    __table_args__ = (
        CheckConstraint("planned_duration_days > 0", name="duration_positive"),
        CheckConstraint("one_way_latency_s >= 0", name="latency_positive"),
        CheckConstraint("day_length_min > 0", name="day_length_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    code: Mapped[str] = mapped_column(
        String(32), unique=True, comment="Code court de la mission (ex. ARTEMIS-M)"
    )
    name: Mapped[str] = mapped_column(String(120), comment="Nom affiché de la mission")
    destination: Mapped[MissionDestination] = mapped_column(
        enum_type(MissionDestination),
        comment="Profil de mission : orbite basse, Lune, transit ou surface de Mars",
    )
    start_date: Mapped[date] = mapped_column(comment="Date de début de la mission (J+0)")
    planned_duration_days: Mapped[int] = mapped_column(comment="Durée prévue en jours")
    flight_profile: Mapped[str] = mapped_column(
        String(120), comment="Profil de vol et blindage (sert à la projection de dose)"
    )
    one_way_latency_s: Mapped[int] = mapped_column(
        comment="Latence de communication aller simple avec la Terre, en secondes (F10.3)"
    )
    day_length_min: Mapped[int] = mapped_column(
        default=1440, comment="Durée d'un jour local en minutes (1477 pour un sol martien)"
    )
    is_active: Mapped[bool] = mapped_column(
        default=True, comment="Mission en cours sur cet appareil"
    )

    crew: Mapped[list[CrewMember]] = relationship(back_populates="mission")
