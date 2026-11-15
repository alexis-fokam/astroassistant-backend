"""Alerts, protocols, pharmacy, emergency and reports (spec F2, F4, F9, F11, F12)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import (
    CurrentCmo,
    CurrentMember,
    DbSession,
    get_crew_member,
    is_cmo,
    subject_member,
    visible_member,
)
from app.api.routes.ws import manager
from app.models import (
    Alert,
    Checkin,
    EmergencyEvent,
    ExerciseSession,
    InventoryItem,
    InventoryUsage,
    Protocol,
    ProtocolRun,
    PvtResult,
    RadiationDose,
    SleepSession,
    VitalReading,
)
from app.models.enums import AlertStatus, EmergencyStatus, Metric, ProtocolRunStatus, SessionStatus
from app.models.sync import PRIORITY_CRITICAL
from app.schemas.alerts import AlertOut, AlertPatch, EmergencyClose, EmergencyIn, EmergencyOut
from app.schemas.care import (
    InventoryItemOut,
    ProtocolOut,
    ProtocolSummary,
    ReportOut,
    RunCreate,
    RunListItem,
    RunOut,
    RunPatch,
    UsageIn,
    UsageOut,
)
from app.services import audit
from app.services import protocols as library
from app.services.sync import queue_packet
from app.services.views import (
    active_alerts,
    alert_out,
    as_utc,
    crew_status,
    emergency_out,
    mission_now,
    run_out,
)

router = APIRouter()


# --------------------------------------------------------------------- alerts
@router.get("/alerts", response_model=list[AlertOut], tags=["alerts"])
def list_alerts(
    db: DbSession,
    viewer: CurrentMember,
    status_filter: Literal["active", "open", "acknowledged", "resolved", "all"] = Query(
        default="active", alias="status"
    ),
    crew: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AlertOut]:
    """CMO queue, sorted by severity then age (F9.2). An astronaut sees only their own."""
    member = visible_member(db, viewer, crew) if crew else None
    if member is None and not is_cmo(viewer):
        member = viewer
    if status_filter == "active":
        alerts = active_alerts(db, member)
    else:
        query = select(Alert).order_by(Alert.triggered_at.desc())
        if status_filter != "all":
            query = query.where(Alert.status == AlertStatus(status_filter))
        if member is not None:
            query = query.where(Alert.crew_member_id == member.id)
        alerts = list(db.scalars(query))
    return [alert_out(a) for a in alerts[:limit]]


@router.get("/alerts/{alert_id}", response_model=AlertOut, tags=["alerts"])
def get_alert(alert_id: int, db: DbSession, viewer: CurrentMember) -> AlertOut:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alerte introuvable")
    visible_member(db, viewer, alert.crew_member.code)
    return alert_out(alert)


@router.patch("/alerts/{alert_id}", response_model=AlertOut, tags=["alerts"])
async def update_alert(alert_id: int, body: AlertPatch, db: DbSession, cmo: CurrentCmo) -> AlertOut:
    """Acknowledge with a comment, or resolve (CMO only)."""
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alerte introuvable")
    now = datetime.now(UTC)
    if body.status == "acknowledged":
        if alert.status is not AlertStatus.OPEN:
            raise HTTPException(status.HTTP_409_CONFLICT, "Alerte déjà prise en charge")
        alert.status, alert.acknowledged_at = AlertStatus.ACKNOWLEDGED, now
        alert.acknowledged_by_id, alert.ack_comment = cmo.id, body.comment
    else:
        if alert.status is AlertStatus.RESOLVED:
            raise HTTPException(status.HTTP_409_CONFLICT, "Alerte déjà résolue")
        if alert.acknowledged_at is None:
            alert.acknowledged_at, alert.acknowledged_by_id = now, cmo.id
            alert.ack_comment = body.comment
        alert.status, alert.resolved_at = AlertStatus.RESOLVED, now
    audit.record(db, f"alert.{body.status}", actor=cmo, entity=alert, comment=body.comment)
    db.commit()
    out = alert_out(alert)
    await manager.broadcast({"type": "alert", "alert": out.model_dump(mode="json")})
    return out


# --------------------------------------------------------------------- protocols
def _protocol_or_404(db: DbSession, code: str) -> Protocol:
    protocol = library.active_protocol(db, code)
    if protocol is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Protocole {code} introuvable")
    return protocol


@router.get("/protocols", response_model=list[ProtocolSummary], tags=["protocols"])
def list_protocols(db: DbSession, _: CurrentMember) -> list[Protocol]:
    return list(
        db.scalars(select(Protocol).where(Protocol.is_active.is_(True)).order_by(Protocol.code))
    )


@router.get("/protocols/runs", response_model=list[RunListItem], tags=["protocols"])
def list_runs(
    db: DbSession,
    viewer: CurrentMember,
    crew: str | None = None,
    status_filter: Literal["in_progress", "completed", "aborted", "all"] = Query(
        default="all", alias="status"
    ),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RunListItem]:
    """Protocol executions, most recent first. An astronaut only sees their own (spec §7)."""
    member = visible_member(db, viewer, crew) if crew else (None if is_cmo(viewer) else viewer)
    query = select(ProtocolRun).order_by(ProtocolRun.started_at.desc()).limit(limit)
    if member is not None:
        query = query.where(ProtocolRun.crew_member_id == member.id)
    if status_filter != "all":
        query = query.where(ProtocolRun.status == ProtocolRunStatus(status_filter))
    items = []
    for run in db.scalars(query):
        codes = library.step_codes(run.protocol)
        trigger = (
            f"{run.alert.rule_code or run.alert.method.value} · {run.alert.title}"
            if run.alert
            else None
        )
        items.append(
            RunListItem(
                **run_out(run, codes).model_dump(),
                protocol_title=run.protocol.title,
                severity=run.protocol.severity,
                expected_duration_min=run.protocol.expected_duration_min,
                total_steps=len(codes),
                trigger=trigger,
            )
        )
    return items


@router.get("/protocols/{code}", response_model=ProtocolOut, tags=["protocols"])
def get_protocol(code: str, db: DbSession, _: CurrentMember) -> ProtocolOut:
    """Steps, exit criterion and material availability of the active version."""
    return library.protocol_out(_protocol_or_404(db, code))


@router.post(
    "/protocols/{code}/runs",
    response_model=RunOut,
    status_code=status.HTTP_201_CREATED,
    tags=["protocols"],
)
def start_run(code: str, body: RunCreate, db: DbSession, viewer: CurrentMember) -> RunOut:
    protocol = _protocol_or_404(db, code)
    member = subject_member(db, viewer, body.crew_code)
    if body.alert_id is not None:
        alert = db.get(Alert, body.alert_id)
        if alert is None or alert.crew_member_id != member.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Alerte sans rapport avec ce membre"
            )
    run = ProtocolRun(
        protocol_id=protocol.id,
        alert_id=body.alert_id,
        crew_member_id=member.id,
        steps=[],
        started_at=datetime.now(UTC),
    )
    db.add(run)
    audit.record(db, "protocol.start", actor=viewer, entity=run, protocol=code, crew=member.code)
    db.commit()
    return run_out(run, library.step_codes(protocol))


@router.patch("/protocols/runs/{run_id}", response_model=RunOut, tags=["protocols"])
def update_run(run_id: int, body: RunPatch, db: DbSession, viewer: CurrentMember) -> RunOut:
    """Validate a step (in order), then complete or abort the run (F4.5)."""
    run = db.get(ProtocolRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exécution introuvable")
    visible_member(db, viewer, run.crew_member.code)
    if run.status is not ProtocolRunStatus.IN_PROGRESS:
        raise HTTPException(status.HTTP_409_CONFLICT, "Exécution déjà clôturée")
    codes = library.step_codes(run.protocol)
    now = datetime.now(UTC)
    if body.step_code is not None:
        expected = run_out(run, codes).next_step
        if body.step_code != expected:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"Étape attendue : {expected}"
            )
        run.steps = [*run.steps, {"code": body.step_code, "validated_at": now.isoformat()}]
    if body.status is not None:
        if body.status == "completed" and len(run.steps) < len(codes):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Toutes les étapes ne sont pas validées"
            )
        run.status, run.ended_at = ProtocolRunStatus(body.status), now
        run.efficacy = body.efficacy
        audit.record(
            db, f"protocol.{body.status}", actor=viewer, entity=run, efficacy=body.efficacy
        )
    db.commit()
    return run_out(run, codes)


# --------------------------------------------------------------------- pharmacy
def _item_out(item: InventoryItem, today) -> InventoryItemOut:
    return InventoryItemOut(
        code=item.code,
        name=item.name,
        category=item.category,
        unit=item.unit,
        quantity=item.quantity,
        min_quantity=item.min_quantity,
        expires_on=item.expires_on,
        location=item.location,
        is_low_stock=item.is_low_stock,
        is_expired=item.expires_on is not None and item.expires_on < today,
    )


@router.get("/inventory", response_model=list[InventoryItemOut], tags=["inventory"])
def inventory(db: DbSession, _: CurrentMember) -> list[InventoryItemOut]:
    today = mission_now(db).date()
    return [
        _item_out(i, today) for i in db.scalars(select(InventoryItem).order_by(InventoryItem.code))
    ]


@router.post(
    "/inventory", response_model=UsageOut, status_code=status.HTTP_201_CREATED, tags=["inventory"]
)
def record_usage(body: UsageIn, db: DbSession, cmo: CurrentCmo) -> UsageOut:
    """Record a pharmacy use and decrement the stock (CMO only, F11.3)."""
    item = db.scalars(select(InventoryItem).where(InventoryItem.code == body.item_code)).first()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Article inconnu")
    if body.quantity > item.quantity:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Stock insuffisant ({item.quantity} {item.unit})"
        )
    patient = get_crew_member(db, body.patient_code) if body.patient_code else None
    usage = InventoryUsage(
        item_id=item.id,
        patient_id=patient.id if patient else None,
        recorded_by_id=cmo.id,
        protocol_run_id=body.protocol_run_id,
        emergency_id=body.emergency_id,
        quantity=body.quantity,
        used_at=datetime.now(UTC),
        note=body.note,
    )
    item.quantity -= body.quantity
    db.add(usage)
    audit.record(
        db, "inventory.use", actor=cmo, entity=usage, item=item.code, quantity=body.quantity
    )
    db.commit()
    return UsageOut(
        id=usage.id,
        item_code=item.code,
        quantity=usage.quantity,
        remaining=item.quantity,
        used_at=as_utc(usage.used_at),
    )


# --------------------------------------------------------------------- emergency
@router.post(
    "/emergency",
    response_model=EmergencyOut,
    status_code=status.HTTP_201_CREATED,
    tags=["emergency"],
)
async def trigger_emergency(
    body: EmergencyIn, db: DbSession, viewer: CurrentMember
) -> EmergencyOut:
    """Emergency mode (F12): any crew member can trigger it, for anyone on board."""
    patient = get_crew_member(db, body.patient_code) if body.patient_code else viewer
    event = EmergencyEvent(
        patient_id=patient.id,
        triggered_by_id=viewer.id,
        status=EmergencyStatus.ACTIVE,
        triggered_at=datetime.now(UTC),
        steps=[],
    )
    db.add(event)
    audit.record(db, "emergency.trigger", actor=viewer, entity=event, patient=patient.code)
    queue_packet(
        db,
        kind="emergency",
        priority=PRIORITY_CRITICAL,
        member=patient,
        content={
            "emergency_id": event.id,
            "patient": patient.code,
            **crew_status(db, patient).model_dump(mode="json"),
        },
    )
    db.commit()
    out = emergency_out(db, event)
    await manager.broadcast({"type": "emergency", "emergency": out.model_dump(mode="json")})
    return out


@router.get("/emergency", response_model=list[EmergencyOut], tags=["emergency"])
def list_emergencies(
    db: DbSession, _: CurrentMember, active_only: bool = True
) -> list[EmergencyOut]:
    query = select(EmergencyEvent).order_by(EmergencyEvent.triggered_at.desc())
    if active_only:
        query = query.where(EmergencyEvent.status == EmergencyStatus.ACTIVE)
    return [emergency_out(db, e) for e in db.scalars(query)]


@router.post("/emergency/{event_id}/steps", response_model=EmergencyOut, tags=["emergency"])
def emergency_step(event_id: int, code: str, db: DbSession, viewer: CurrentMember) -> EmergencyOut:
    event = _active_emergency(db, event_id)
    event.steps = [
        *event.steps,
        {"code": code, "validated_at": datetime.now(UTC).isoformat(), "by": viewer.code},
    ]
    db.commit()
    return emergency_out(db, event)


@router.post("/emergency/{event_id}/close", response_model=EmergencyOut, tags=["emergency"])
def close_emergency(
    event_id: int, body: EmergencyClose, db: DbSession, cmo: CurrentCmo
) -> EmergencyOut:
    """Close with an outcome and a summary (CMO only, U-04)."""
    event = _active_emergency(db, event_id)
    event.status, event.closed_at, event.closed_by_id = (
        EmergencyStatus.CLOSED,
        datetime.now(UTC),
        cmo.id,
    )
    event.outcome, event.summary = body.outcome, body.summary
    audit.record(db, "emergency.close", actor=cmo, entity=event, outcome=body.outcome)
    db.commit()
    return emergency_out(db, event)


def _active_emergency(db: DbSession, event_id: int) -> EmergencyEvent:
    event = db.get(EmergencyEvent, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Urgence introuvable")
    if event.status is not EmergencyStatus.ACTIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "Urgence déjà clôturée")
    return event


# --------------------------------------------------------------------- reports
@router.get("/reports/{code}", response_model=ReportOut, tags=["reports"])
def report(
    code: str,
    db: DbSession,
    viewer: CurrentMember,
    period: Literal["day", "week", "month"] = "week",
) -> ReportOut:
    """Synthesis of one member over a period, ending at the mission clock."""
    member = visible_member(db, viewer, code)
    end = mission_now(db)
    start = end - timedelta(days={"day": 1, "week": 7, "month": 30}[period])

    def window(column):
        return column >= start, column <= end

    vitals = {}
    for metric in (Metric.HEART_RATE, Metric.HRV_RMSSD, Metric.SPO2, Metric.RESPIRATORY_RATE):
        low, high, avg = db.execute(
            select(
                func.min(VitalReading.value),
                func.max(VitalReading.value),
                func.avg(VitalReading.value),
            ).where(
                VitalReading.crew_member_id == member.id,
                VitalReading.metric == metric,
                VitalReading.is_artifact.is_(False),
                VitalReading.sim_run_id.is_(None),
                *window(VitalReading.recorded_at),
            )
        ).one()
        if avg is not None:
            vitals[metric.value] = {"min": low, "max": high, "mean": round(avg, 1)}

    sleeps = db.scalars(
        select(SleepSession).where(
            SleepSession.crew_member_id == member.id, *window(SleepSession.started_at)
        )
    ).all()
    exercises = db.scalars(
        select(ExerciseSession).where(
            ExerciseSession.crew_member_id == member.id, *window(ExerciseSession.scheduled_at)
        )
    ).all()
    pvts = db.scalars(
        select(PvtResult).where(PvtResult.crew_member_id == member.id, *window(PvtResult.taken_at))
    ).all()
    doses = db.scalars(
        select(RadiationDose.mission_cumulative_msv)
        .where(RadiationDose.crew_member_id == member.id, *window(RadiationDose.recorded_at))
        .order_by(RadiationDose.recorded_at)
    ).all()
    alerts = db.scalars(
        select(Alert).where(Alert.crew_member_id == member.id, *window(Alert.triggered_at))
    ).all()
    current = crew_status(db, member)
    pvt_rts = sorted(p.median_rt_ms for p in pvts)
    return ReportOut(
        crew_id=member.code,
        period_start=start,
        period_end=end,
        status=current.status.value if current.status else None,
        global_score=current.global_score,
        vitals=vitals,
        sleep_hours_avg=round(
            sum((s.ended_at - s.started_at).total_seconds() for s in sleeps) / 3600 / len(sleeps), 2
        )
        if sleeps
        else None,
        exercise_completed=sum(e.status is SessionStatus.COMPLETED for e in exercises),
        exercise_missed=sum(e.status is SessionStatus.MISSED for e in exercises),
        pvt_median_rt_ms=pvt_rts[len(pvt_rts) // 2] if pvt_rts else None,
        pvt_lapses=sum(p.lapses for p in pvts),
        checkins=db.scalar(
            select(func.count())
            .select_from(Checkin)
            .where(Checkin.crew_member_id == member.id, *window(Checkin.submitted_at))
        ),
        dose_received_msv=round(doses[-1] - doses[0], 2) if len(doses) > 1 else 0.0,
        alerts={
            level: sum(a.level.value == level for a in alerts)
            for level in ("info", "warning", "critical")
        },
    )
