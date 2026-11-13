"""Équipage (profils locaux protégés par PIN), capteurs et baselines individuelles."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_type, utcnow
from app.models.enums import AccessRole, CrewRole, DeviceKind, Metric, Sex

if TYPE_CHECKING:
    from app.models.alerts import Alert
    from app.models.vitals import Checkin, VitalReading


class CrewMember(TimestampMixin, Base):
    """Membre d'équipage = profil local de l'application (§7, §9 ``crew_member``).

    Pas de compte distant : chaque profil se déverrouille par PIN sur le poste.
    Un profil n'est jamais supprimé (journal d'audit) : on le désactive.
    """

    __tablename__ = "crew_members"
    __table_args__ = (
        CheckConstraint("mass_kg IS NULL OR mass_kg > 0", name="mass_positive"),
        CheckConstraint("height_cm IS NULL OR height_cm > 0", name="height_positive"),
        CheckConstraint(
            "career_dose_limit_msv > 0 AND prior_career_dose_msv >= 0", name="dose_limits"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)  # ex. « AV-02 »
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    crew_role: Mapped[CrewRole] = mapped_column(enum_type(CrewRole))
    access_role: Mapped[AccessRole] = mapped_column(
        enum_type(AccessRole), default=AccessRole.ASTRONAUT
    )
    pin_hash: Mapped[str] = mapped_column(String(255))
    avatar: Mapped[str | None] = mapped_column(String(64))

    sex: Mapped[Sex | None] = mapped_column(enum_type(Sex))
    birth_date: Mapped[date | None]
    height_cm: Mapped[float | None]
    mass_kg: Mapped[float | None]
    mission_start_date: Mapped[date]
    # Limite de carrière de référence (NASA-STD-3001) et dose accumulée avant la mission (F5.1).
    career_dose_limit_msv: Mapped[float] = mapped_column(default=600.0)
    prior_career_dose_msv: Mapped[float] = mapped_column(default=0.0)
    is_active: Mapped[bool] = mapped_column(default=True)

    devices: Mapped[list[Device]] = relationship(back_populates="crew_member")
    baselines: Mapped[list[Baseline]] = relationship(
        back_populates="crew_member", cascade="all, delete-orphan", passive_deletes=True
    )
    readings: Mapped[list[VitalReading]] = relationship(
        back_populates="crew_member", cascade="all, delete-orphan", passive_deletes=True
    )
    checkins: Mapped[list[Checkin]] = relationship(
        back_populates="crew_member", cascade="all, delete-orphan", passive_deletes=True
    )
    alerts: Mapped[list[Alert]] = relationship(
        back_populates="crew_member",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="Alert.crew_member_id",
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class Device(TimestampMixin, Base):
    """Capteur porté, capteur cabine ou générateur du simulateur qui produit des mesures."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[DeviceKind] = mapped_column(enum_type(DeviceKind))
    serial_number: Mapped[str] = mapped_column(String(64), unique=True)
    firmware_version: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(default=True)
    last_seen_at: Mapped[datetime | None]

    crew_member: Mapped[CrewMember | None] = relationship(back_populates="devices")


class Baseline(Base):
    """Ligne de base individuelle d'une métrique (F2.1, §9 ``baseline``).

    Moyenne / écart-type glissants, plus médiane / MAD pour le z-score robuste (F2.2).
    """

    __tablename__ = "baselines"
    __table_args__ = (
        UniqueConstraint("crew_member_id", "metric"),
        CheckConstraint("std >= 0 AND (mad IS NULL OR mad >= 0)", name="dispersion_positive"),
        CheckConstraint("sample_count >= 0", name="sample_count_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_member_id: Mapped[int] = mapped_column(ForeignKey("crew_members.id", ondelete="CASCADE"))
    metric: Mapped[Metric] = mapped_column(enum_type(Metric))
    mean: Mapped[float]
    std: Mapped[float]
    median: Mapped[float | None]
    mad: Mapped[float | None]
    sample_count: Mapped[int]
    window_days: Mapped[int] = mapped_column(default=14)
    computed_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    crew_member: Mapped[CrewMember] = relationship(back_populates="baselines")
