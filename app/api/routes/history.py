from fastapi import APIRouter, Query

from app.api.deps import CurrentMember, DbSession
from app.models import Checkin, ExerciseSession, PvtResult, SleepSession
from app.schemas.history import (
    CheckinDetailOut,
    ExerciseDetailOut,
    PaginatedOut,
    PvtDetailOut,
    SleepOut,
)
from app.services.history import paginate_member_history, resolve_authorized_member

router = APIRouter(tags=["history"])


@router.get("/checkins/{code}", response_model=PaginatedOut[CheckinDetailOut])
def list_checkins(
    code: str,
    db: DbSession,
    current: CurrentMember,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedOut[CheckinDetailOut]:
    target = resolve_authorized_member(db, current, code)
    rows, total = paginate_member_history(
        db, Checkin, target.id, Checkin.submitted_at, limit, offset
    )
    return PaginatedOut(
        items=[CheckinDetailOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/sleep/{code}", response_model=PaginatedOut[SleepOut])
def list_sleep_sessions(
    code: str,
    db: DbSession,
    current: CurrentMember,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedOut[SleepOut]:
    target = resolve_authorized_member(db, current, code)
    rows, total = paginate_member_history(
        db, SleepSession, target.id, SleepSession.started_at, limit, offset
    )
    return PaginatedOut(
        items=[SleepOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/exercises/{code}", response_model=PaginatedOut[ExerciseDetailOut])
def list_exercise_sessions(
    code: str,
    db: DbSession,
    current: CurrentMember,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedOut[ExerciseDetailOut]:
    target = resolve_authorized_member(db, current, code)
    rows, total = paginate_member_history(
        db, ExerciseSession, target.id, ExerciseSession.scheduled_at, limit, offset
    )
    return PaginatedOut(
        items=[ExerciseDetailOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/pvt/{code}", response_model=PaginatedOut[PvtDetailOut])
def list_pvt_results(
    code: str,
    db: DbSession,
    current: CurrentMember,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PaginatedOut[PvtDetailOut]:
    target = resolve_authorized_member(db, current, code)
    rows, total = paginate_member_history(
        db, PvtResult, target.id, PvtResult.taken_at, limit, offset
    )
    return PaginatedOut(
        items=[PvtDetailOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )

