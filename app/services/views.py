"""Aides de lecture : horloge de mission, statut de l'équipage et conversions ORM → schéma."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Alert,
    CrewMember,
    EmergencyEvent,
    GroundMessage,
    ProtocolRun,
    RiskScore,
    SimRun,
    SyncPacket,
    VitalReading,
)
from app.models.enums import AccessRole, AlertLevel, AlertStatus, RiskDomain
from app.schemas.alerts import AlertOut, EmergencyOut
from app.schemas.care import RunOut
from app.schemas.crew import CrewProfile, CrewStatus, CrewSummary, Factor
from app.schemas.ground import GroundMessageOut, PacketOut, SimRunOut

LEVEL_ORDER = {AlertLevel.CRITICAL: 0, AlertLevel.WARNING: 1, AlertLevel.INFO: 2}


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite renvoie des dates naïves ; chaque date stockée est en UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def mission_now(db: Session) -> datetime:
    """Horloge de mission : heure de la dernière mesure de mission, sinon l'heure réelle.

    La base de démo contient un historique fixe (J+142) ; partir de sa dernière mesure garde
    toutes les valeurs relatives (jour de mission, « depuis », projections) cohérentes.
    """
    latest = db.scalar(
        select(func.max(VitalReading.recorded_at)).where(VitalReading.sim_run_id.is_(None))
    )
    return as_utc(latest) or datetime.now(UTC)


def mission_latency(db: Session) -> timedelta:
    """Délai aller Terre-équipage de la mission active (cahier des charges : 4-24 min pour Mars)."""
    from app.models import Mission

    seconds = db.scalar(select(Mission.one_way_latency_s).where(Mission.is_active.is_(True)))
    return timedelta(seconds=seconds or 0)


def latest_scores(db: Session, member: CrewMember) -> dict[RiskDomain, RiskScore]:
    """Score de mission le plus récent de chaque domaine."""
    newest = db.scalar(
        select(func.max(RiskScore.computed_at)).where(
            RiskScore.crew_member_id == member.id, RiskScore.sim_run_id.is_(None)
        )
    )
    if newest is None:
        return {}
    rows = db.scalars(
        select(RiskScore).where(
            RiskScore.crew_member_id == member.id,
            RiskScore.sim_run_id.is_(None),
            RiskScore.computed_at == newest,
        )
    )
    return {r.domain: r for r in rows}


def active_alerts(db: Session, member: CrewMember | None = None) -> list[Alert]:
    query = select(Alert).where(Alert.status != AlertStatus.RESOLVED)
    if member is not None:
        query = query.where(Alert.crew_member_id == member.id)
    alerts = list(db.scalars(query))
    alerts.sort(key=lambda a: (LEVEL_ORDER[a.level], a.triggered_at))
    return alerts


def alert_out(alert: Alert, latency: timedelta | None = None) -> AlertOut:
    """``latency`` ajoute l'heure d'arrivée de l'alerte au sol (tableau de bord sol M4)."""
    return AlertOut.model_validate(
        {
            **{c: getattr(alert, c) for c in AlertOut.model_fields if hasattr(alert, c)},
            "crew_code": alert.crew_member.code,
            "recommended_protocol": alert.recommended_protocol.code
            if alert.recommended_protocol
            else None,
            "acknowledged_by": alert.acknowledged_by.code if alert.acknowledged_by else None,
            "triggered_at": as_utc(alert.triggered_at),
            "ground_received_at": as_utc(alert.triggered_at) + latency if latency else None,
            "acknowledged_at": as_utc(alert.acknowledged_at),
            "resolved_at": as_utc(alert.resolved_at),
        }
    )


def crew_summary(db: Session, member: CrewMember) -> CrewSummary:
    scores = latest_scores(db, member)
    overall = scores.get(RiskDomain.GLOBAL)
    alerts = active_alerts(db, member)
    return CrewSummary(
        code=member.code,
        first_name=member.first_name,
        last_name=member.last_name,
        crew_role=member.crew_role,
        is_cmo=member.access_role is AccessRole.CMO,
        status=overall.level if overall else None,
        global_score=overall.score if overall else None,
        top_alert=alerts[0].title if alerts else None,
    )


def crew_status(db: Session, member: CrewMember) -> CrewStatus:
    scores = latest_scores(db, member)
    overall = scores.get(RiskDomain.GLOBAL)
    domains = {d.value: s.score for d, s in scores.items() if d is not RiskDomain.GLOBAL}
    factors = [
        Factor(**f)
        for s in sorted(scores.values(), key=lambda s: -s.score)
        if s.domain is not RiskDomain.GLOBAL
        for f in s.factors
    ]
    factors.sort(key=lambda f: -f.contribution)
    alerts = active_alerts(db, member)
    protocol = next((a.recommended_protocol.code for a in alerts if a.recommended_protocol), None)
    return CrewStatus(
        crew_id=member.code,
        timestamp=as_utc(overall.computed_at) if overall else None,
        status=overall.level if overall else None,
        global_score=overall.score if overall else None,
        domains=domains,
        top_factors=factors[:3],
        recommended_protocol=protocol,
        active_alerts=[alert_out(a) for a in alerts],
    )


def crew_profiles(db: Session) -> list[CrewProfile]:
    members = db.scalars(
        select(CrewMember).where(CrewMember.is_active.is_(True)).order_by(CrewMember.code)
    ).all()

    profiles: list[CrewProfile] = []
    for member in members:
        profiles.append(
            CrewProfile(
                code=member.code,
                first_name=member.first_name,
                last_name=member.last_name,
                crew_role=member.crew_role,
                is_cmo=member.access_role is AccessRole.CMO,
            )
        )
    return profiles


def run_out(run: ProtocolRun, step_codes: list[str]) -> RunOut:
    done = {s["code"] for s in run.steps}
    return RunOut(
        id=run.id,
        protocol_code=run.protocol.code,
        crew_code=run.crew_member.code,
        alert_id=run.alert_id,
        status=run.status,
        steps=run.steps,
        next_step=next((c for c in step_codes if c not in done), None),
        started_at=as_utc(run.started_at),
        ended_at=as_utc(run.ended_at),
        efficacy=run.efficacy,
    )


def _code(db: Session, member_id: int | None) -> str | None:
    if member_id is None:
        return None
    member = db.get(CrewMember, member_id)
    return member.code if member else None


def emergency_out(db: Session, event: EmergencyEvent) -> EmergencyOut:
    return EmergencyOut(
        id=event.id,
        patient_code=event.patient.code if event.patient else None,
        triggered_by_code=event.triggered_by.code if event.triggered_by else None,
        status=event.status,
        triggered_at=as_utc(event.triggered_at),
        steps=event.steps,
        outcome=event.outcome,
        closed_at=as_utc(event.closed_at),
        summary=event.summary,
    )


def packet_out(db: Session, packet: SyncPacket) -> PacketOut:
    sent = as_utc(packet.sent_at)
    arrival = sent + mission_latency(db) if sent else None
    return PacketOut(
        id=packet.id,
        crew_code=_code(db, packet.crew_member_id),
        kind=packet.kind,
        priority=packet.priority,
        status=packet.status,
        size_bytes=packet.size_bytes,
        sha256=packet.sha256,
        created_at=as_utc(packet.created_at),
        sent_at=as_utc(packet.sent_at),
        acknowledged_at=as_utc(packet.acknowledged_at),
        received_at_ground=arrival,
        in_transit=arrival is not None and arrival > mission_now(db),
    )


def message_out(db: Session, message: GroundMessage) -> GroundMessageOut:
    return GroundMessageOut(
        id=message.id,
        crew_code=_code(db, message.crew_member_id),
        author=message.author,
        subject=message.subject,
        body=message.body,
        is_instruction=message.is_instruction,
        sha256=message.sha256,
        sent_at=as_utc(message.sent_at),
        received_at=as_utc(message.received_at),
        read_at=as_utc(message.read_at),
        in_transit=as_utc(message.received_at) > mission_now(db),
    )


def sim_run_out(run: SimRun) -> SimRunOut:
    return SimRunOut(
        id=run.id,
        scenario_code=run.scenario.code,
        crew_code=run.crew_member.code if run.crew_member else None,
        status=run.status,
        seed=run.seed,
        speed_factor=run.speed_factor,
        started_at=as_utc(run.started_at),
        ended_at=as_utc(run.ended_at),
    )
