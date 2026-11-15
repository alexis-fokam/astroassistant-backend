"""Liaison sol, simulateur, journal d'audit et jeux ouverts (F10, F14, F15, §12)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentCmo, CurrentMember, DbSession, get_crew_member, is_cmo
from app.models import (
    AuditLog,
    ContactWindow,
    CrewMember,
    DatasetSource,
    GroundMessage,
    SimRun,
    SimScenario,
    SyncPacket,
)
from app.models.enums import SimRunStatus
from app.models.sync import PRIORITY_NORMAL
from app.schemas.ground import (
    AuditOut,
    AuditVerifyOut,
    ContactWindowOut,
    DatasetOut,
    ExportOut,
    ExportRequest,
    GroundMessageOut,
    ImportRequest,
    InjectIn,
    InstructionIn,
    PacketOut,
    ScenarioOut,
    ScenarioStart,
    SimRunOut,
    SpeedIn,
)
from app.services import audit
from app.services.sync import export_queue, queue_packet
from app.services.views import (
    crew_summary,
    message_out,
    mission_latency,
    mission_now,
    packet_out,
    sim_run_out,
)
from app.sim import live
from app.sim.controller import controller

router = APIRouter()


# --------------------------------------------------------------------- ground link
@router.post(
    "/sync/export", response_model=ExportOut, status_code=status.HTTP_201_CREATED, tags=["sync"]
)
def export(body: ExportRequest, db: DbSession, viewer: CurrentMember) -> ExportOut:
    """Construire le paquet de synthèse du jour et renvoyer la file d'export (F10.1, F10.2)."""
    members = (
        [get_crew_member(db, body.crew_code)]
        if body.crew_code
        else list(
            db.scalars(
                select(CrewMember).where(CrewMember.is_active.is_(True)).order_by(CrewMember.code)
            )
        )
    )
    content = {
        "mission_time": mission_now(db).isoformat(),
        "crew": {m.code: crew_summary(db, m).model_dump(mode="json") for m in members},
    }
    packet = queue_packet(
        db,
        kind="daily_summary",
        priority=PRIORITY_NORMAL,
        content=content,
        member=members[0] if body.crew_code else None,
    )
    audit.record(db, "sync.export", actor=viewer, entity=packet, bytes=packet.size_bytes)
    db.commit()
    return ExportOut(
        packet=packet_out(db, packet),
        content=content,
        queue=[packet_out(db, p) for p in export_queue(db)],
    )


@router.get("/sync/packets", response_model=list[PacketOut], tags=["sync"])
def packets(
    db: DbSession,
    _: CurrentMember,
    queued_only: bool = True,
    limit: int = Query(default=50, le=500),
) -> list[PacketOut]:
    if queued_only:
        return [packet_out(db, p) for p in export_queue(db)[:limit]]
    rows = db.scalars(select(SyncPacket).order_by(SyncPacket.created_at.desc()).limit(limit))
    return [packet_out(db, p) for p in rows]


@router.post(
    "/sync/import",
    response_model=GroundMessageOut,
    status_code=status.HTTP_201_CREATED,
    tags=["sync"],
)
def import_message(body: ImportRequest, db: DbSession, viewer: CurrentMember) -> GroundMessageOut:
    """Importer une consigne du sol ; son SHA-256 est vérifié s'il est fourni (F10.4)."""
    digest = hashlib.sha256(body.body.encode()).hexdigest()
    if body.sha256 and body.sha256.lower() != digest:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Empreinte SHA-256 invalide : message altéré"
        )
    if db.scalars(select(GroundMessage).where(GroundMessage.sha256 == digest)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Message déjà importé")
    recipient = get_crew_member(db, body.crew_code) if body.crew_code else None
    message = GroundMessage(
        crew_member_id=recipient.id if recipient else None,
        author=body.author,
        subject=body.subject,
        body=body.body,
        is_instruction=body.is_instruction,
        sha256=digest,
        sent_at=body.sent_at,
        received_at=mission_now(db),  # importée à bord : elle est arrivée
    )
    db.add(message)
    audit.record(db, "ground.import", actor=viewer, entity=message, subject=body.subject)
    db.commit()
    return message_out(db, message)


@router.get("/sync/messages", response_model=list[GroundMessageOut], tags=["sync"])
def messages(db: DbSession, viewer: CurrentMember) -> list[GroundMessageOut]:
    """Messages du sol : ceux de tout l'équipage et ceux du lecteur (tous pour le CMO)."""
    query = select(GroundMessage).order_by(GroundMessage.received_at.desc())
    # Les messages encore en route depuis la Terre ne sont pas à bord (délai de communication).
    query = query.where(GroundMessage.received_at <= mission_now(db))
    if not is_cmo(viewer):
        query = query.where(
            (GroundMessage.crew_member_id.is_(None)) | (GroundMessage.crew_member_id == viewer.id)
        )
    return [message_out(db, m) for m in db.scalars(query)]


@router.post("/sync/messages/{message_id}/read", response_model=GroundMessageOut, tags=["sync"])
def mark_read(message_id: int, db: DbSession, viewer: CurrentMember) -> GroundMessageOut:
    message = db.get(GroundMessage, message_id)
    if message is None or (message.crew_member_id not in (None, viewer.id) and not is_cmo(viewer)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message introuvable")
    message.read_at = message.read_at or datetime.now(UTC)
    db.commit()
    return message_out(db, message)


@router.post(
    "/ground/instructions",
    response_model=GroundMessageOut,
    status_code=status.HTTP_201_CREATED,
    tags=["ground"],
)
def send_instruction(body: InstructionIn, db: DbSession, viewer: CurrentMember) -> GroundMessageOut:
    """Tableau de bord sol : envoyer une consigne ; elle arrive après le délai aller."""
    recipient = get_crew_member(db, body.crew_code) if body.crew_code else None
    sent = mission_now(db)
    message = GroundMessage(
        crew_member_id=recipient.id if recipient else None,
        author=body.author,
        subject=body.subject,
        body=body.body,
        is_instruction=True,
        sha256=hashlib.sha256(f"{body.body}|{sent.isoformat()}".encode()).hexdigest(),
        sent_at=sent,
        received_at=sent + mission_latency(db),
    )
    db.add(message)
    audit.record(db, "ground.send", actor=viewer, entity=message, subject=body.subject)
    db.commit()
    return message_out(db, message)


@router.get("/ground/instructions", response_model=list[GroundMessageOut], tags=["ground"])
def ground_instructions(db: DbSession, _: CurrentMember) -> list[GroundMessageOut]:
    """Vue sol : toutes les consignes, y compris celles encore en transit."""
    query = select(GroundMessage).order_by(GroundMessage.sent_at.desc())
    return [message_out(db, m) for m in db.scalars(query)]


@router.get("/sync/windows", response_model=list[ContactWindowOut], tags=["sync"])
def windows(
    db: DbSession, _: CurrentMember, upcoming: int = Query(default=6, ge=1, le=50)
) -> list[ContactWindow]:
    now = mission_now(db)
    return list(
        db.scalars(
            select(ContactWindow)
            .where(ContactWindow.ends_at >= now, ContactWindow.sim_run_id.is_(None))
            .order_by(ContactWindow.starts_at)
            .limit(upcoming)
        )
    )


# --------------------------------------------------------------------- simulator
@router.get("/sim/scenarios", response_model=list[ScenarioOut], tags=["simulation"])
def scenarios(db: DbSession, _: CurrentMember) -> list[SimScenario]:
    return list(db.scalars(select(SimScenario).order_by(SimScenario.code)))


@router.post(
    "/sim/scenario",
    response_model=SimRunOut,
    status_code=status.HTTP_201_CREATED,
    tags=["simulation"],
)
async def start_scenario(body: ScenarioStart, db: DbSession, viewer: CurrentMember) -> SimRunOut:
    """Lancer une démo en direct de S1-S6 (F15) : mesures toutes les 2 s, analysées par l'IA."""
    scenario = db.scalars(select(SimScenario).where(SimScenario.code == body.code)).first()
    if scenario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Scénario {body.code} inconnu")
    crew_code = body.crew_code or scenario.parameters.get("crew")
    member = get_crew_member(db, crew_code) if crew_code and crew_code != "all" else None
    for running in db.scalars(select(SimRun).where(SimRun.status == SimRunStatus.RUNNING)):
        running.status, running.ended_at = SimRunStatus.ABORTED, datetime.now(UTC)
    run = SimRun(
        scenario_id=scenario.id,
        crew_member_id=member.id if member else None,
        seed=body.seed,
        speed_factor=body.speed_factor,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    audit.record(
        db, "sim.start", actor=viewer, entity=run, scenario=scenario.code, speed=body.speed_factor
    )
    db.commit()
    await controller.stop()
    controller.reset()
    live.start(
        db,
        controller.state,
        run.id,
        scenario.code,
        body.speed_factor,
        body.seed,
        member.code if member else None,
    )
    controller.launch()
    return sim_run_out(run)


@router.post("/sim/speed", response_model=SimRunOut, tags=["simulation"])
def set_speed(body: SpeedIn, db: DbSession, viewer: CurrentMember) -> SimRunOut:
    run = db.get(SimRun, body.run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exécution introuvable")
    if run.status is not SimRunStatus.RUNNING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Simulation terminée")
    run.speed_factor = body.speed_factor
    if controller.state.run_id == run.id:
        controller.state.speed = body.speed_factor
    audit.record(db, "sim.speed", actor=viewer, entity=run, speed=body.speed_factor)
    db.commit()
    return sim_run_out(run)


@router.post("/sim/runs/{run_id}/stop", response_model=SimRunOut, tags=["simulation"])
async def stop_run(run_id: int, db: DbSession, viewer: CurrentMember) -> SimRunOut:
    run = db.get(SimRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Exécution introuvable")
    if controller.state.run_id == run.id:
        await controller.stop()
    if run.status is SimRunStatus.RUNNING:
        run.status, run.ended_at = SimRunStatus.COMPLETED, datetime.now(UTC)
        audit.record(db, "sim.stop", actor=viewer, entity=run)
        db.commit()
    return sim_run_out(run)


@router.get("/sim/anomalies", tags=["simulation"])
def anomalies(_: CurrentMember) -> list[dict]:
    """Anomalies que le jury peut injecter, avec les règles que le moteur doit lever."""
    return [
        {
            "code": a.code,
            "label": a.label,
            "description": a.description,
            "expected_rules": list(a.expected_rules),
        }
        for a in live.ANOMALIES.values()
    ]


@router.get("/sim/state", tags=["simulation"])
def sim_state(_: CurrentMember) -> dict:
    """Exécution en cours : horloge simulée, vitesse, anomalies actives et journal."""
    return live.snapshot(controller.state, controller.running)


@router.post("/sim/inject", tags=["simulation"])
def inject(body: InjectIn, db: DbSession, _: CurrentMember) -> dict:
    """Injecter une anomalie dans la simulation en cours (lancer d'abord un scénario)."""
    if controller.state.run_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Lancez d'abord un scénario (POST /sim/scenario)"
        )
    try:
        live.inject(db, controller.state, body.anomaly, body.crew_code)
    except ValueError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(error)) from error
    return live.snapshot(controller.state, controller.running)


@router.post("/sim/tick", tags=["simulation"])
def sim_tick(db: DbSession, _: CurrentMember, count: int = Query(default=1, ge=1, le=60)) -> dict:
    """Avancer la simulation de ``count`` pas maintenant (étape de démo, tests)."""
    if controller.state.run_id is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Lancez d'abord un scénario (POST /sim/scenario)"
        )
    for _ in range(count):
        live.tick(db, controller.state)
    return live.snapshot(controller.state, controller.running)


@router.get("/sim/runs", response_model=list[SimRunOut], tags=["simulation"])
def sim_runs(db: DbSession, _: CurrentMember) -> list[SimRunOut]:
    return [sim_run_out(r) for r in db.scalars(select(SimRun).order_by(SimRun.started_at.desc()))]


# --------------------------------------------------------------------- audit & datasets
@router.get("/audit", response_model=list[AuditOut], tags=["audit"])
def audit_trail(
    db: DbSession,
    _: CurrentCmo,
    action: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> list[AuditLog]:
    """Entrées les plus récentes d'abord (CMO uniquement)."""
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        query = query.where(AuditLog.action.startswith(action))
    return list(db.scalars(query))


@router.get("/audit/verify", response_model=AuditVerifyOut, tags=["audit"])
def audit_verify(db: DbSession, _: CurrentCmo) -> AuditVerifyOut:
    """Recalculer la chaîne SHA-256 pour prouver que le journal n'a pas été modifié."""
    valid, entries, broken_at = audit.verify(db)
    return AuditVerifyOut(valid=valid, entries=entries, broken_at=broken_at)


@router.get("/datasets", response_model=list[DatasetOut], tags=["datasets"])
def datasets(db: DbSession) -> list[DatasetSource]:
    """Jeux de données ouverts utilisés par le projet, avec leur origine (public, §12)."""
    return list(db.scalars(select(DatasetSource).order_by(DatasetSource.code)))
