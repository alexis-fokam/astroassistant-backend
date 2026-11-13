"""Synchronisation différée avec la Terre, en « store-and-forward » (F10, §9 ``sync_packet``)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, enum_type, utcnow
from app.models.enums import SyncPacketKind, SyncPacketStatus

# Priorités d'export : les alertes CRITICAL passent en tête de file (F10.2).
PRIORITY_CRITICAL = 0
PRIORITY_HIGH = 1
PRIORITY_NORMAL = 2
PRIORITY_LOW = 3


class SyncPacket(Base):
    """Paquet de la file d'export persistante : JSON compressé (gzip) et horodaté (F10.1).

    La file se lit par ``status = 'queued'`` puis ``priority`` croissante puis ancienneté.
    ``sha256`` est l'empreinte du contenu compressé (F10.5).
    """

    __tablename__ = "sync_packets"
    __table_args__ = (
        Index("ix_sync_packets_queue", "status", "priority", "created_at"),
        CheckConstraint(
            f"priority BETWEEN {PRIORITY_CRITICAL} AND {PRIORITY_LOW}", name="priority_range"
        ),
        CheckConstraint("size_bytes >= 0", name="size_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL"), index=True
    )  # NULL = paquet d'équipage
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[SyncPacketKind] = mapped_column(enum_type(SyncPacketKind))
    priority: Mapped[int] = mapped_column(SmallInteger, default=PRIORITY_NORMAL)
    status: Mapped[SyncPacketStatus] = mapped_column(
        enum_type(SyncPacketStatus), default=SyncPacketStatus.QUEUED
    )
    payload_gz: Mapped[bytes]
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    sent_at: Mapped[datetime | None]
    acknowledged_at: Mapped[datetime | None]


class GroundMessage(Base):
    """Consigne renvoyée par le sol, affichée comme message du flight surgeon (F10.4)."""

    __tablename__ = "ground_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL"), index=True
    )  # NULL = toute l'équipe
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )
    author: Mapped[str] = mapped_column(String(120))  # ex. « Dr M. Reyes · Houston »
    subject: Mapped[str | None] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)  # intégrité de l'import
    sent_at: Mapped[datetime | None]  # horodatage d'émission au sol
    received_at: Mapped[datetime] = mapped_column(default=utcnow)
    read_at: Mapped[datetime | None]


class ContactWindow(Base):
    """Fenêtre de contact simulée avec latence configurable (F10.3)."""

    __tablename__ = "contact_windows"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="chronology"),
        CheckConstraint("one_way_latency_s >= 0", name="latency_positive"),
        CheckConstraint("bandwidth_kbps IS NULL OR bandwidth_kbps > 0", name="bandwidth_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True
    )
    starts_at: Mapped[datetime] = mapped_column(index=True)
    ends_at: Mapped[datetime]
    one_way_latency_s: Mapped[int]  # ex. 240 à 1 320 s vers Mars
    bandwidth_kbps: Mapped[float | None]
    notes: Mapped[str | None] = mapped_column(Text)
