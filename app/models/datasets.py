"""Provenance of open datasets and the reference measurements imported from them (spec §12)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, utcnow


class DatasetSource(Base):
    """Jeu de données ouvert utilisé par le projet : origine, licence, date de récupération."""

    __tablename__ = "dataset_sources"

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    code: Mapped[str] = mapped_column(
        String(32), unique=True, comment="Code court (ex. nasa-donki)"
    )
    name: Mapped[str] = mapped_column(String(200), comment="Nom officiel du jeu de données")
    agency: Mapped[str] = mapped_column(String(80), comment="Agence ou organisme producteur")
    url: Mapped[str] = mapped_column(
        String(300), comment="Adresse de téléchargement ou de documentation"
    )
    licence: Mapped[str] = mapped_column(String(120), comment="Licence d'utilisation")
    usage: Mapped[str] = mapped_column(Text, comment="Usage dans Astro Assistant")
    bundled: Mapped[bool] = mapped_column(
        comment=(
            "Vrai si un extrait est versionné dans le dépôt "
            "(data/nasa), faux s'il est téléchargé à la demande"
        )
    )
    retrieved_at: Mapped[datetime | None] = mapped_column(
        comment="Date de la dernière récupération (UTC)"
    )
    record_count: Mapped[int] = mapped_column(
        default=0, comment="Nombre de lignes importées en base"
    )

    dose_samples: Mapped[list[CruiseDoseSample]] = relationship(back_populates="source")


class CruiseDoseSample(Base):
    """Débit de dose réel mesuré par Curiosity RAD pendant le transit vers Mars (référence F5)."""

    __tablename__ = "cruise_dose_samples"
    __table_args__ = (
        CheckConstraint("dose_rate_b_ugy_h > 0 AND dose_rate_e_ugy_h > 0", name="dose_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    source_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_sources.id", ondelete="CASCADE"),
        index=True,
        comment="Jeu de données d'origine",
    )
    measured_at: Mapped[datetime] = mapped_column(
        index=True, comment="Début de l'observation RAD (UTC)"
    )
    dose_rate_b_ugy_h: Mapped[float] = mapped_column(
        comment="Débit de dose absorbée, détecteur silicium B (µGy/h)"
    )
    dose_rate_e_ugy_h: Mapped[float] = mapped_column(
        comment="Débit de dose absorbée, scintillateur E proche du tissu humain (µGy/h)"
    )
    dose_equivalent_usv_h: Mapped[float] = mapped_column(
        comment="Équivalent de dose estimé avec un facteur de qualité de 3,8 (µSv/h)"
    )

    source: Mapped[DatasetSource] = relationship(back_populates="dose_samples")


class ProtonFluxReading(Base):
    """Flux de protons intégral mesuré par les satellites GOES de la NOAA (alerte précoce F5.4)."""

    __tablename__ = "proton_flux_readings"
    __table_args__ = (
        Index("ix_proton_flux_readings_energy_time", "energy_band", "measured_at"),
        CheckConstraint("flux_pfu >= 0", name="flux_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    source_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_sources.id", ondelete="CASCADE"),
        index=True,
        comment="Jeu de données d'origine",
    )
    measured_at: Mapped[datetime] = mapped_column(comment="Instant de la mesure (UTC)")
    satellite: Mapped[int] = mapped_column(comment="Numéro du satellite GOES")
    energy_band: Mapped[str] = mapped_column(String(16), comment="Seuil d'énergie (ex. >=10 MeV)")
    flux_pfu: Mapped[float] = mapped_column(comment="Flux de protons (pfu, particules/cm²·s·sr)")
    imported_at: Mapped[datetime] = mapped_column(
        default=utcnow, comment="Date d'import en base (UTC)"
    )
