"""Équipage (profils locaux protégés par PIN), capteurs et références individuelles."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, enum_type, utcnow
from app.models.enums import AccessRole, CrewRole, DeviceKind, Metric, Sex

if TYPE_CHECKING:
    from app.models.alerts import Alert
    from app.models.mission import Mission
    from app.models.vitals import Checkin, VitalReading


class CrewMember(TimestampMixin, Base):
    """Membre d'équipage = profil local de l'application, déverrouillé par PIN (§7, §9 crew_member).

    Un profil n'est jamais supprimé (journal d'audit) : il est désactivé.
    """

    __tablename__ = "crew_members"
    __table_args__ = (
        CheckConstraint("mass_kg IS NULL OR mass_kg > 0", name="mass_positive"),
        CheckConstraint("height_cm IS NULL OR height_cm > 0", name="height_positive"),
        CheckConstraint(
            "career_dose_limit_msv > 0 AND prior_career_dose_msv >= 0", name="dose_limits"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    mission_id: Mapped[int] = mapped_column(
        ForeignKey("missions.id", ondelete="RESTRICT"),
        index=True,
        comment="Mission à laquelle appartient le membre",
    )
    code: Mapped[str] = mapped_column(
        String(16), unique=True, comment="Identifiant d'équipage (ex. AV-02)"
    )
    first_name: Mapped[str] = mapped_column(String(80), comment="Prénom")
    last_name: Mapped[str] = mapped_column(String(80), comment="Nom")
    crew_role: Mapped[CrewRole] = mapped_column(enum_type(CrewRole), comment="Fonction à bord")
    access_role: Mapped[AccessRole] = mapped_column(
        enum_type(AccessRole),
        default=AccessRole.ASTRONAUT,
        comment="Droits : astronaute (ses données) ou médecin de bord (tout l'équipage)",
    )
    pin_hash: Mapped[str] = mapped_column(
        String(255), comment="Empreinte PBKDF2-SHA256 du PIN, jamais le PIN en clair"
    )
    avatar: Mapped[str | None] = mapped_column(
        String(64), comment="Couleur ou identifiant d'avatar"
    )
    sex: Mapped[Sex | None] = mapped_column(
        enum_type(Sex), comment="Sexe (sert aux références physiologiques)"
    )
    birth_date: Mapped[date | None] = mapped_column(comment="Date de naissance")
    height_cm: Mapped[float | None] = mapped_column(comment="Taille en centimètres")
    mass_kg: Mapped[float | None] = mapped_column(comment="Masse en kilogrammes")
    mission_start_date: Mapped[date] = mapped_column(comment="Date d'entrée en mission du membre")
    career_dose_limit_msv: Mapped[float] = mapped_column(
        default=600.0, comment="Limite de dose de carrière (NASA-STD-3001), en mSv"
    )
    prior_career_dose_msv: Mapped[float] = mapped_column(
        default=0.0, comment="Dose cumulée avant cette mission, en mSv"
    )
    is_active: Mapped[bool] = mapped_column(
        default=True, comment="Profil actif (faux = désactivé, jamais supprimé)"
    )

    mission: Mapped[Mission] = relationship(back_populates="crew")
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

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    crew_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL"),
        index=True,
        comment="Porteur du capteur (vide pour un capteur cabine)",
    )
    kind: Mapped[DeviceKind] = mapped_column(enum_type(DeviceKind), comment="Type de capteur")
    serial_number: Mapped[str] = mapped_column(String(64), unique=True, comment="Numéro de série")
    firmware_version: Mapped[str | None] = mapped_column(
        String(32), comment="Version du micrologiciel"
    )
    is_active: Mapped[bool] = mapped_column(default=True, comment="Capteur en service")
    last_seen_at: Mapped[datetime | None] = mapped_column(comment="Dernière mesure reçue (UTC)")

    crew_member: Mapped[CrewMember | None] = relationship(back_populates="devices")


class Baseline(Base):
    """Ligne de base individuelle d'une métrique (F2.1) : moyenne, écart-type, médiane, MAD."""

    __tablename__ = "baselines"
    __table_args__ = (
        UniqueConstraint("crew_member_id", "metric"),
        CheckConstraint("std >= 0 AND (mad IS NULL OR mad >= 0)", name="dispersion_positive"),
        CheckConstraint("sample_count >= 0", name="sample_count_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    crew_member_id: Mapped[int] = mapped_column(
        ForeignKey("crew_members.id", ondelete="CASCADE"), comment="Membre concerné"
    )
    metric: Mapped[Metric] = mapped_column(enum_type(Metric), comment="Métrique physiologique")
    mean: Mapped[float] = mapped_column(comment="Moyenne glissante")
    std: Mapped[float] = mapped_column(comment="Écart-type glissant")
    median: Mapped[float | None] = mapped_column(comment="Médiane (z-score robuste, F2.2)")
    mad: Mapped[float | None] = mapped_column(comment="Écart absolu médian (z-score robuste, F2.2)")
    sample_count: Mapped[int] = mapped_column(comment="Nombre de mesures utilisées")
    window_days: Mapped[int] = mapped_column(default=14, comment="Fenêtre de calcul en jours")
    computed_at: Mapped[datetime] = mapped_column(
        default=utcnow, onupdate=utcnow, comment="Date du dernier calcul (UTC)"
    )

    crew_member: Mapped[CrewMember] = relationship(back_populates="baselines")
