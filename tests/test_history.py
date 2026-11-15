"""Historique de démo fictif : cohérence, déterminisme et intégrité."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Alert,
    AuditLog,
    Base,
    CrewMember,
    EmergencyEvent,
    RadiationDose,
    RiskScore,
    SyncPacket,
    VitalReading,
)
from app.models.audit import GENESIS_HASH
from app.models.enums import AlertStatus, EmergencyStatus, HealthLevel, RiskDomain
from app.seed import seed
from app.sim.history import DEMO_NOW, FINAL_GLOBAL


def _latest_global(db: Session) -> dict[str, tuple[float, HealthLevel]]:
    out = {}
    for member in db.scalars(select(CrewMember)):
        score = db.scalars(
            select(RiskScore)
            .where(RiskScore.crew_member_id == member.id, RiskScore.domain == RiskDomain.GLOBAL)
            .order_by(RiskScore.computed_at.desc())
        ).first()
        out[member.code] = (score.score, score.level)
    return out


def test_every_table_is_filled(db: Session) -> None:
    seed(db)
    empty = [
        t.name
        for t in Base.metadata.sorted_tables
        if not db.scalar(select(func.count()).select_from(t))
    ]
    assert empty == []


def test_final_state_matches_the_frontend_story(db: Session) -> None:
    seed(db)
    latest = _latest_global(db)
    assert {code: score for code, (score, _) in latest.items()} == FINAL_GLOBAL
    assert latest["AV-03"][1] is HealthLevel.CRITICAL

    open_titles = set(db.scalars(select(Alert.title).where(Alert.status == AlertStatus.OPEN)))
    assert open_titles == {"VFC basse persistante", "Suspicion SANS", "Tachycardie et désaturation"}
    active = db.scalars(
        select(EmergencyEvent).where(EmergencyEvent.status == EmergencyStatus.ACTIVE)
    ).one()
    assert active.patient.code == "AV-03"


def test_history_ends_at_demo_clock(db: Session) -> None:
    seed(db)
    last = db.scalar(
        select(func.max(VitalReading.recorded_at)).where(VitalReading.sim_run_id.is_(None))
    )
    assert last.replace(tzinfo=None) == DEMO_NOW.replace(tzinfo=None)


def test_radiation_doses_are_cumulative(db: Session) -> None:
    seed(db)
    for member in db.scalars(select(CrewMember)):
        doses = db.scalars(
            select(RadiationDose.mission_cumulative_msv)
            .where(RadiationDose.crew_member_id == member.id)
            .order_by(RadiationDose.recorded_at)
        ).all()
        assert doses == sorted(doses)
        assert 150 < doses[-1] < member.career_dose_limit_msv


def test_audit_chain_verifies_after_reload(db: Session) -> None:
    seed(db)
    db.expire_all()
    prev = GENESIS_HASH
    entries = db.scalars(select(AuditLog).order_by(AuditLog.id)).all()
    assert len(entries) > 50
    for entry in entries:
        assert entry.prev_hash == prev
        assert entry.entry_hash == AuditLog.compute_hash(
            prev,
            at=entry.at,
            actor_label=entry.actor_label,
            action=entry.action,
            entity_type=entry.entity_type,
            entity_id=entry.entity_id,
            details=entry.details,
        )
        prev = entry.entry_hash
    assert [e.at for e in entries] == sorted(e.at for e in entries)


def test_sync_packets_are_real_gzip_with_matching_hash(db: Session) -> None:
    import gzip
    import hashlib
    import json

    seed(db)
    for packet in db.scalars(select(SyncPacket)):
        assert hashlib.sha256(packet.payload_gz).hexdigest() == packet.sha256
        assert packet.size_bytes == len(packet.payload_gz)
        json.loads(gzip.decompress(packet.payload_gz))


def test_history_is_deterministic(db: Session) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as OrmSession

    seed(db)
    other = create_engine("sqlite://")
    Base.metadata.create_all(other)
    with OrmSession(other) as second:
        seed(second)
        query = select(func.sum(VitalReading.value))
        assert db.scalar(query) == second.scalar(query)
        hashes = select(AuditLog.entry_hash).order_by(AuditLog.id.desc()).limit(1)
        assert db.scalar(hashes) == second.scalar(hashes)
