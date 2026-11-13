"""Médecine de bord : notes de consultation du CMO (F9.3) et pharmacie (F11)."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, utcnow

if TYPE_CHECKING:
    from app.models.crew import CrewMember


class ConsultationNote(Base):
    """Note de consultation du journal médical d'un astronaute (F9.3)."""

    __tablename__ = "consultation_notes"
    __table_args__ = (Index("ix_consultation_notes_patient_time", "patient_id", "written_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("crew_members.id", ondelete="CASCADE"))
    author_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL")
    )
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id", ondelete="SET NULL"))
    written_at: Mapped[datetime] = mapped_column(default=utcnow)
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)

    patient: Mapped[CrewMember] = relationship(foreign_keys=[patient_id])
    author: Mapped[CrewMember | None] = relationship(foreign_keys=[author_id])


class InventoryItem(TimestampMixin, Base):
    """Article du kit médical de bord (F11.1, §9 ``med_inventory``)."""

    __tablename__ = "inventory_items"
    __table_args__ = (
        CheckConstraint("quantity >= 0 AND min_quantity >= 0", name="quantities_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)  # ex. « MED-PARA-500 »
    name: Mapped[str] = mapped_column(String(160))
    category: Mapped[str | None] = mapped_column(String(64))  # médicament, matériel, consommable
    unit: Mapped[str] = mapped_column(String(32))  # cp, flacon, unité…
    quantity: Mapped[float]
    min_quantity: Mapped[float] = mapped_column(default=0)  # seuil d'alerte de stock bas
    expires_on: Mapped[date | None] = mapped_column(index=True)
    location: Mapped[str | None] = mapped_column(String(64))  # ex. « Module B · tiroir 1 »

    usages: Mapped[list[InventoryUsage]] = relationship(back_populates="item")

    @property
    def is_low_stock(self) -> bool:
        return self.quantity <= self.min_quantity


class InventoryUsage(Base):
    """Registre des usages de la pharmacie, saisi par le CMO uniquement (F11.3)."""

    __tablename__ = "inventory_usages"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT"), index=True
    )
    patient_id: Mapped[int | None] = mapped_column(
        ForeignKey("crew_members.id", ondelete="SET NULL")
    )
    recorded_by_id: Mapped[int] = mapped_column(ForeignKey("crew_members.id", ondelete="RESTRICT"))
    protocol_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("protocol_runs.id", ondelete="SET NULL")
    )
    quantity: Mapped[float]
    used_at: Mapped[datetime] = mapped_column(default=utcnow)
    note: Mapped[str | None] = mapped_column(Text)

    item: Mapped[InventoryItem] = relationship(back_populates="usages")
    patient: Mapped[CrewMember | None] = relationship(foreign_keys=[patient_id])
    recorded_by: Mapped[CrewMember] = relationship(foreign_keys=[recorded_by_id])
