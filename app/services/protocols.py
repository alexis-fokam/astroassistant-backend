"""Protocol library: YAML content of a loaded version and material availability (F4, F11.2)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import BASE_DIR
from app.models import CrewMember, Protocol, ProtocolRun
from app.models.enums import ProtocolRunStatus
from app.schemas.care import ProtocolMaterialOut, ProtocolOut, ProtocolStepOut, RunOut


@lru_cache(maxsize=64)
def _read_yaml(path: str, checksum: str) -> dict[str, Any]:
    # The checksum is part of the cache key: a reloaded version is read again.
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

def run_out(run: ProtocolRun) -> RunOut:
    """Sérialise un ProtocolRun et calcule la prochaine étape à valider."""
    next_step: str | None = None
    if run.status is ProtocolRunStatus.IN_PROGRESS:
        done_codes = {
            s["code"] for s in (run.steps or []) if isinstance(s, dict) and "code" in s
        }
        next_step = next(
            (code for code in step_codes(run.protocol) if code not in done_codes),
            None,
        )

    return RunOut(
        id=run.id,
        protocol_code=run.protocol.code,
        crew_code=run.crew_member.code,
        alert_id=run.alert_id,
        status=run.status,
        steps=run.steps,
        next_step=next_step,
        started_at=run.started_at,
        ended_at=run.ended_at,
        efficacy=run.efficacy,
    )


def list_protocol_runs(
    db: Session,
    current: CrewMember,
    crew_code: str | None = None,
    run_status: ProtocolRunStatus | None = None,
) -> list[RunOut]:

    stmt = (
        select(ProtocolRun)
        .options(
            joinedload(ProtocolRun.protocol),
            joinedload(ProtocolRun.crew_member),
        )
        .order_by(ProtocolRun.started_at.desc())
    )

    if crew_code:
        if crew_code != current.code:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Accès refusé aux exécutions d'un autre membre d'équipage",
            )
        target = db.scalars(
            select(CrewMember).where(
                CrewMember.code == crew_code, CrewMember.is_active.is_(True)
            )
        ).first()
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Membre d'équipage '{crew_code}' introuvable",
            )
        stmt = stmt.where(ProtocolRun.crew_member_id == target.id)

    if run_status is not None:
        stmt = stmt.where(ProtocolRun.status == run_status)

    runs = db.scalars(stmt).all()
    return [run_out(r) for r in runs]
