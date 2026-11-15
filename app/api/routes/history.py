"""Per-member history lists for the dashboards: check-ins, sleep, exercise, PVT.

Design from @gazonsn-del's PR #8 (pagination, newest first), integrated with the shared
access rule: an astronaut reads their own history, the CMO reads the whole crew (spec §7).
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
