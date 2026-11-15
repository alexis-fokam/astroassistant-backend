"""Historiques par membre pour les tableaux de bord : check-ins, sommeil, exercice, PVT.

Conception reprise de la PR #8 de @gazonsn-del (pagination, plus récents d'abord), avec la
règle d'accès commune : un astronaute lit son historique, le CMO celui de tout l'équipage (§7).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentMember, DbSession, visible_member
from app.models import Checkin, ExerciseSession, PvtResult, SleepSession
from app.schemas.history import CheckinDetailOut, ExerciseDetailOut, Page, PvtDetailOut, SleepOut

router = APIRouter(tags=["history"])

Limit = Query(default=20, ge=1, le=200)
Offset = Query(default=0, ge=0)


def _page(db: Session, model: Any, member_id: int, order: Any, limit: int, offset: int):
    where = model.crew_member_id == member_id
    total = db.scalar(select(func.count()).select_from(model).where(where)) or 0
    rows = db.scalars(select(model).where(where).order_by(order.desc()).offset(offset).limit(limit))
    return list(rows), total


@router.get("/checkins/{code}", response_model=Page[CheckinDetailOut])
def list_checkins(
    code: str, db: DbSession, viewer: CurrentMember, limit: int = Limit, offset: int = Offset
) -> Page[CheckinDetailOut]:
    member = visible_member(db, viewer, code)
    rows, total = _page(db, Checkin, member.id, Checkin.submitted_at, limit, offset)
    return Page(items=rows, total=total, limit=limit, offset=offset)


@router.get("/sleep/{code}", response_model=Page[SleepOut])
def list_sleep(
    code: str, db: DbSession, viewer: CurrentMember, limit: int = Limit, offset: int = Offset
) -> Page[SleepOut]:
    member = visible_member(db, viewer, code)
    rows, total = _page(db, SleepSession, member.id, SleepSession.started_at, limit, offset)
    return Page(items=rows, total=total, limit=limit, offset=offset)


@router.get("/exercises/{code}", response_model=Page[ExerciseDetailOut])
def list_exercises(
    code: str, db: DbSession, viewer: CurrentMember, limit: int = Limit, offset: int = Offset
) -> Page[ExerciseDetailOut]:
    member = visible_member(db, viewer, code)
    rows, total = _page(db, ExerciseSession, member.id, ExerciseSession.scheduled_at, limit, offset)
    return Page(items=rows, total=total, limit=limit, offset=offset)


@router.get("/pvt/{code}", response_model=Page[PvtDetailOut])
def list_pvt(
    code: str, db: DbSession, viewer: CurrentMember, limit: int = Limit, offset: int = Offset
) -> Page[PvtDetailOut]:
    member = visible_member(db, viewer, code)
    rows, total = _page(db, PvtResult, member.id, PvtResult.taken_at, limit, offset)
    return Page(items=rows, total=total, limit=limit, offset=offset)
