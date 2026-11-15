"""Constantes, radiation et données déclarées (F1, F3, F5, F6, F8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentMember, DbSession, subject_member, visible_member
from app.api.routes.ws import manager
from app.models import (
    Baseline,
    Checkin,
    Device,
    ExerciseSession,
    Mission,
    PvtResult,
    RadiationDose,
    VitalReading,
)
from app.models.enums import METRIC_UNITS, DataSource, Metric
from app.schemas.telemetry import (
    CheckinIn,
    CheckinOut,
    ExerciseIn,
    ExerciseOut,
    PvtIn,
    PvtOut,
    RadiationOut,
    RadiationPoint,
    VitalBatch,
    VitalBatchResult,
    VitalPoint,
    VitalSeries,
)
from app.services import audit
from app.services.views import as_utc, mission_now

router = APIRouter()


@router.post(
    "/vitals",
    response_model=VitalBatchResult,
    status_code=status.HTTP_201_CREATED,
    tags=["vitals"],
)
async def ingest_vitals(body: VitalBatch, db: DbSession, viewer: CurrentMember) -> VitalBatchResult:
    """Recevoir un lot de mesures pour un membre (capteur porté ou saisie manuelle)."""
    member = subject_member(db, viewer, body.crew_code)
    device = None
    if body.device_serial:
        device = db.scalars(
            select(Device).where(Device.serial_number == body.device_serial)
        ).first()
        if device is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Capteur inconnu")
    received = datetime.now(UTC)
    rows = [
        {
            "crew_member_id": member.id,
            "device_id": device.id if device else None,
            "metric": r.metric,
            "value": r.value,
            "quality": r.quality,
            "source": DataSource.SENSOR if device else DataSource.MANUAL,
            "recorded_at": r.recorded_at,
            "received_at": received,
        }
        for r in body.readings
    ]
    db.execute(VitalReading.__table__.insert(), rows)
    if device:
        device.last_seen_at = max(r.recorded_at for r in body.readings)
    db.commit()
    await manager.broadcast({"type": "vitals", "crew_id": member.code, "count": len(rows)})
    return VitalBatchResult(accepted=len(rows))


@router.get("/vitals/{code}", response_model=VitalSeries, tags=["vitals"])
def vital_series(
    code: str,
    db: DbSession,
    viewer: CurrentMember,
    metric: Metric = Query(alias="type"),
    start: datetime | None = Query(default=None, alias="from"),
    end: datetime | None = Query(default=None, alias="to"),
    include_artifacts: bool = False,
    limit: int = Query(default=2000, ge=1, le=20000),
) -> VitalSeries:
    """Série temporelle d'une mesure pour les graphes (défaut : 24 dernières h de mission)."""
    member = visible_member(db, viewer, code)
    end = end or mission_now(db)
    start = start or end - timedelta(hours=24)
    query = (
        select(VitalReading)
        .where(
            VitalReading.crew_member_id == member.id,
            VitalReading.metric == metric,
            VitalReading.sim_run_id.is_(None),
            VitalReading.recorded_at >= start,
            VitalReading.recorded_at <= end,
        )
        .order_by(VitalReading.recorded_at)
        .limit(limit)
    )
    if not include_artifacts:
        query = query.where(VitalReading.is_artifact.is_(False))
    baseline = db.scalars(
        select(Baseline).where(Baseline.crew_member_id == member.id, Baseline.metric == metric)
    ).first()
    return VitalSeries(
        crew_id=member.code,
        metric=metric,
        unit=METRIC_UNITS[metric],
        baseline_mean=baseline.mean if baseline else None,
        baseline_std=baseline.std if baseline else None,
        points=[
            VitalPoint(
                t=as_utc(r.recorded_at), value=r.value, quality=r.quality, is_artifact=r.is_artifact
            )
            for r in db.scalars(query)
        ],
    )


@router.get("/radiation/{code}", response_model=RadiationOut, tags=["radiation"])
def radiation(
    code: str,
    db: DbSession,
    viewer: CurrentMember,
    hours: int = Query(default=72, ge=1, le=24 * 30),
) -> RadiationOut:
    """Dose cumulée, débit actuel et projection jusqu'à la fin de la mission (F5)."""
    member = visible_member(db, viewer, code)
    doses = list(
        db.scalars(
            select(RadiationDose)
            .where(RadiationDose.crew_member_id == member.id, RadiationDose.sim_run_id.is_(None))
            .order_by(RadiationDose.recorded_at)
        )
    )
    mission = db.get(Mission, member.mission_id)
    last = doses[-1] if doses else None
    mission_dose = last.mission_cumulative_msv if last else 0.0
    career_dose = last.career_cumulative_msv if last else member.prior_career_dose_msv
    elapsed = (mission_now(db).date() - mission.start_date).days or 1
    daily = mission_dose / elapsed
    remaining = max(mission.planned_duration_days - elapsed, 0)
    since = as_utc(last.recorded_at) - timedelta(hours=hours) if last else None
    return RadiationOut(
        crew_id=member.code,
        recorded_at=as_utc(last.recorded_at) if last else None,
        dose_rate_msv_h=last.dose_rate_msv_h if last else None,
        neutron_fraction=last.neutron_fraction if last else None,
        mission_cumulative_msv=round(mission_dose, 2),
        career_cumulative_msv=round(career_dose, 2),
        career_limit_msv=member.career_dose_limit_msv,
        career_used_pct=round(100 * career_dose / member.career_dose_limit_msv, 1),
        daily_average_msv=round(daily, 3),
        projected_mission_end_msv=round(mission_dose + daily * remaining, 1),
        projected_career_end_msv=round(career_dose + daily * remaining, 1),
        history=[
            RadiationPoint(
                t=as_utc(d.recorded_at),
                dose_rate_msv_h=d.dose_rate_msv_h,
                mission_cumulative_msv=d.mission_cumulative_msv,
            )
            for d in doses
            if since and as_utc(d.recorded_at) >= since
        ],
    )


@router.post(
    "/checkins", response_model=CheckinOut, status_code=status.HTTP_201_CREATED, tags=["wellness"]
)
def submit_checkin(body: CheckinIn, db: DbSession, viewer: CurrentMember) -> Checkin:
    member = subject_member(db, viewer, body.crew_code)
    checkin = Checkin(crew_member_id=member.id, **body.model_dump(exclude={"crew_code"}))
    db.add(checkin)
    audit.record(db, "checkin.submit", actor=viewer, entity=checkin, crew=member.code)
    db.commit()
    return checkin


@router.post(
    "/exercises", response_model=ExerciseOut, status_code=status.HTTP_201_CREATED, tags=["wellness"]
)
def log_exercise(body: ExerciseIn, db: DbSession, viewer: CurrentMember) -> ExerciseSession:
    member = subject_member(db, viewer, body.crew_code)
    session = ExerciseSession(crew_member_id=member.id, **body.model_dump(exclude={"crew_code"}))
    if session.status == "completed" and session.duration_min is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Durée requise pour une séance réalisée"
        )
    db.add(session)
    db.commit()
    return session


@router.post("/pvt", response_model=PvtOut, status_code=status.HTTP_201_CREATED, tags=["wellness"])
def log_pvt(body: PvtIn, db: DbSession, viewer: CurrentMember) -> PvtResult:
    member = subject_member(db, viewer, body.crew_code)
    data = body.model_dump(exclude={"crew_code"}, exclude_none=True)
    result = PvtResult(crew_member_id=member.id, **data)
    db.add(result)
    db.commit()
    return result
