"""Bibliothèque de protocoles : YAML d'une version et matériel disponible (F4, F11.2)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BASE_DIR
from app.models import Protocol
from app.schemas.care import ProtocolMaterialOut, ProtocolOut, ProtocolStepOut


@lru_cache(maxsize=64)
def _read_yaml(path: str, checksum: str) -> dict[str, Any]:
    # L'empreinte fait partie de la clé de cache : une version rechargée est relue.
    return yaml.safe_load((BASE_DIR / path).read_text(encoding="utf-8")) or {}


def content(protocol: Protocol) -> dict[str, Any]:
    return _read_yaml(protocol.file_path, protocol.checksum)


def step_codes(protocol: Protocol) -> list[str]:
    return [s["code"] for s in content(protocol).get("steps", [])]


def active_protocol(db: Session, code: str) -> Protocol | None:
    return db.scalars(
        select(Protocol)
        .where(Protocol.code == code, Protocol.is_active.is_(True))
        .order_by(Protocol.loaded_at.desc())
    ).first()


def protocol_out(protocol: Protocol) -> ProtocolOut:
    spec = content(protocol)
    materials = [
        ProtocolMaterialOut(
            item_code=r.item.code,
            name=r.item.name,
            quantity=r.quantity,
            in_stock=r.item.quantity,
            available=r.item.quantity >= r.quantity,
            optional=r.is_optional,
        )
        for r in protocol.requirements
    ]
    return ProtocolOut(
        code=protocol.code,
        version=protocol.version,
        title=protocol.title,
        domain=protocol.domain,
        severity=protocol.severity,
        expected_duration_min=protocol.expected_duration_min,
        description=protocol.description,
        trigger=spec.get("trigger") or {},
        exit_criterion=spec.get("exit_criterion"),
        steps=[ProtocolStepOut(**s) for s in spec.get("steps", [])],
        materials=materials,
        ready=all(m.available for m in materials if not m.optional),
        checksum=protocol.checksum,
    )
