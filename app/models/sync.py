"""Synchronisation différée avec la Terre, stockage puis envoi (F10, §9 sync_packet)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, enum_type, utcnow
from app.models.enums import SyncPacketKind, SyncPacketStatus

if TYPE_CHECKING:
    from app.models.mission import Mission

# Priorités d'export : les alertes CRITICAL partent en premier (F10.2).
PRIORITY_CRITICAL = 0
PRIORITY_HIGH = 1
PRIORITY_NORMAL = 2
PRIORITY_LOW = 3


class SyncPacket(Base):
    """Paquet de la file d'export : JSON compressé gzip, horodaté et signé SHA-256 (F10.1, F10.5).

    La file se lit par statut « queued », puis priorité croissante, puis ancienneté.
    """

    __tablename__ = "sync_packets"
    __table_args__ = (
        Index("ix_sync_packets_queue", "status", "priority", "created_at"),
        CheckConstraint(
            f"priority BETWEEN {PRIORITY_CRITICAL} AND {PRIORITY_LOW}", name="priority_range"
        ),
        CheckConstraint("size_bytes >= 0", name="size_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    crew_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL"),
        index=True,
        comment="Membre concerné (vide pour un paquet d'équipage)",
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True, comment="Simulation d'origine"
    )
    kind: Mapped[SyncPacketKind] = mapped_column(
        enum_type(SyncPacketKind), comment="Nature du contenu"
    )
    priority: Mapped[int] = mapped_column(
        SmallInteger,
        default=PRIORITY_NORMAL,
        comment="Priorité d'envoi : 0 critique, 1 haute, 2 normale, 3 basse",
    )
    status: Mapped[SyncPacketStatus] = mapped_column(
        enum_type(SyncPacketStatus),
        default=SyncPacketStatus.QUEUED,
        comment="En file, envoyé, acquitté ou échoué",
    )
    payload_gz: Mapped[bytes] = mapped_column(comment="Contenu JSON compressé (gzip)")
    size_bytes: Mapped[int] = mapped_column(comment="Taille compressée en octets")
    sha256: Mapped[str] = mapped_column(
        String(64), unique=True, comment="Empreinte SHA-256 du contenu compressé"
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow, comment="Création du paquet (UTC)")
    sent_at: Mapped[datetime | None] = mapped_column(comment="Envoi vers le sol (UTC)")
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        comment="Accusé de réception du sol (UTC)"
    )


class GroundMessage(Base):
    """Consigne renvoyée par le sol, affichée comme message du flight surgeon (F10.4)."""

    __tablename__ = "ground_messages"

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    crew_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL"),
        index=True,
        comment="Destinataire (vide pour tout l'équipage)",
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True, comment="Simulation d'origine"
    )
    author: Mapped[str] = mapped_column(
        String(120), comment="Auteur au sol (ex. Dr M. Reyes · Houston)"
    )
    subject: Mapped[str | None] = mapped_column(String(160), comment="Objet")
    body: Mapped[str] = mapped_column(Text, comment="Texte de la consigne")
    is_instruction: Mapped[bool] = mapped_column(
        default=False, comment="Consigne médicale à appliquer"
    )
    sha256: Mapped[str] = mapped_column(
        String(64), unique=True, comment="Empreinte d'intégrité de l'import"
    )
    sent_at: Mapped[datetime | None] = mapped_column(comment="Émission au sol (UTC)")
    received_at: Mapped[datetime] = mapped_column(default=utcnow, comment="Réception à bord (UTC)")
    read_at: Mapped[datetime | None] = mapped_column(comment="Lecture par le destinataire (UTC)")


class ContactWindow(Base):
    """Fenêtre de contact avec la Terre et latence associée (F10.3)."""

    __tablename__ = "contact_windows"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="chronology"),
        CheckConstraint("one_way_latency_s >= 0", name="latency_positive"),
        CheckConstraint("bandwidth_kbps IS NULL OR bandwidth_kbps > 0", name="bandwidth_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, comment="Identifiant technique")
    mission_id: Mapped[int] = mapped_column(
        ForeignKey("missions.id", ondelete="CASCADE"), index=True, comment="Mission concernée"
    )
    sim_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sim_runs.id", ondelete="CASCADE"), index=True, comment="Simulation d'origine"
    )
    starts_at: Mapped[datetime] = mapped_column(index=True, comment="Ouverture de la fenêtre (UTC)")
    ends_at: Mapped[datetime] = mapped_column(comment="Fermeture de la fenêtre (UTC)")
    one_way_latency_s: Mapped[int] = mapped_column(comment="Latence aller simple en secondes")
    bandwidth_kbps: Mapped[float | None] = mapped_column(comment="Débit estimé (kb/s)")
    notes: Mapped[str | None] = mapped_column(Text, comment="Remarque")

    mission: Mapped[Mission] = relationship()
