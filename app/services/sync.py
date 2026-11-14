"""Store-and-forward export queue (spec F10): gzip JSON packets signed with SHA-256."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CrewMember, SyncPacket
from app.models.enums import SyncPacketKind, SyncPacketStatus


def encode(content: dict[str, Any]) -> bytes:
    # mtime=0 makes the archive, and therefore its hash, depend on the content only.
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str).encode()
    return gzip.compress(raw, mtime=0)


def queue_packet(
    db: Session,
    *,
    kind: str,
    priority: int,
    content: dict[str, Any],
    member: CrewMember | None = None,
) -> SyncPacket:
    now = datetime.now(UTC)
    content = {"generated_at": now.isoformat(), **content}
    payload = encode(content)
    packet = SyncPacket(
        crew_member_id=member.id if member else None,
        kind=SyncPacketKind(kind),
        priority=priority,
        status=SyncPacketStatus.QUEUED,
        payload_gz=payload,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        created_at=now,
    )
    db.add(packet)
    db.flush()
    return packet


def export_queue(db: Session) -> list[SyncPacket]:
    """Packets waiting for the next contact window: priority first, then age (F10.2)."""
    return list(
        db.scalars(
            select(SyncPacket)
            .where(SyncPacket.status == SyncPacketStatus.QUEUED)
            .order_by(SyncPacket.priority, SyncPacket.created_at)
        )
    )
