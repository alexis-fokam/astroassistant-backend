"""Ajouter des entrées au journal d'audit chaîné par SHA-256 (F14.1)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, CrewMember
from app.models.audit import GENESIS_HASH


def record(
    session: Session,
    action: str,
    *,
    actor: CrewMember | None = None,
    actor_label: str | None = None,
    entity: Any = None,
    at: datetime | None = None,
    **details: Any,
) -> AuditLog:
    """Chaîner une nouvelle entrée à la dernière. L'appelant fait le commit."""
    session.flush()  # l'entité a besoin de son id
    prev = (
        session.scalars(select(AuditLog.entry_hash).order_by(AuditLog.id.desc())).first()
        or GENESIS_HASH
    )
    entry = {
        "at": at or datetime.now(UTC),
        "actor_label": actor_label or (actor.code if actor else "Système"),
        "action": action,
        "entity_type": entity.__tablename__ if entity is not None else None,
        "entity_id": entity.id if entity is not None else None,
        "details": details,
    }
    log = AuditLog(
        actor_id=actor.id if actor else None,
        prev_hash=prev,
        entry_hash=AuditLog.compute_hash(prev, **entry),
        **entry,
    )
    session.add(log)
    return log


def verify(session: Session) -> tuple[bool, int, int | None]:
    """Recalculer toute la chaîne : (valide, entrées vérifiées, id de la 1re entrée cassée)."""
    prev, count = GENESIS_HASH, 0
    for entry in session.scalars(select(AuditLog).order_by(AuditLog.id)):
        expected = AuditLog.compute_hash(
            prev,
            at=entry.at,
            actor_label=entry.actor_label,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            details=entry.details,
        )
        if entry.prev_hash != prev or entry.entry_hash != expected:
            return False, count, entry.id
        prev, count = entry.entry_hash, count + 1
    return True, count, None
