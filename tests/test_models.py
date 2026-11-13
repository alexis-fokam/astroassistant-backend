import gzip
import hashlib
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Alert,
    AuditLog,
    Checkin,
    CrewMember,
    InventoryItem,
    Protocol,
    ProtocolRun,
    RadiationDose,
    RiskScore,
    SimRun,
    SimScenario,
    SyncPacket,
    VitalReading,
)
from app.models.audit import GENESIS_HASH
from app.models.enums import (
    AccessRole,
    AlertLevel,
    AlertStatus,
    CrewRole,
    DataSource,
    DetectionMethod,
    HealthLevel,
    Metric,
    ProtocolRunStatus,
    RiskDomain,
    SyncPacketKind,
)
from app.models.sync import PRIORITY_CRITICAL, PRIORITY_LOW

NOW = datetime(2026, 10, 13, 14, 5, tzinfo=UTC)


def _crew(db: Session, code: str = "AV-02", access: AccessRole = AccessRole.ASTRONAUT):
    crew = CrewMember(
        code=code,
        first_name="Léo",
        last_name="Martin",
        crew_role=CrewRole.FLIGHT_ENGINEER,
        access_role=access,
        pin_hash="pbkdf2$fake",
        mission_start_date=date(2026, 5, 24),
    )
    db.add(crew)
    db.flush()
    return crew


def _protocol(db: Session) -> Protocol:
    protocol = Protocol(
        code="PRT-STRESS-01",
        version="1.3",
        title="Respiration guidée",
        domain=RiskDomain.BEHAVIORAL,
        severity=AlertLevel.WARNING,
        file_path="app/protocols/stress.yaml",
        checksum="0" * 64,
    )
    db.add(protocol)
    db.flush()
    return protocol


def _packet(priority: int, created_at: datetime, **kw) -> SyncPacket:
    payload = gzip.compress(f'{{"p": {priority}, "t": "{created_at}"}}'.encode())
    return SyncPacket(
        kind=SyncPacketKind.ALERT,
        priority=priority,
        payload_gz=payload,
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        created_at=created_at,
        **kw,
    )


def test_schema_covers_specification_tables(db: Session) -> None:
    tables = set(inspect(db.get_bind()).get_table_names())
    # §9 du cahier des charges, puis tables ajoutées pour F5, F9.3, F10, F11, F12, F13, F15.
    assert {
        "crew_members",
        "vital_readings",
        "baselines",
        "radiation_doses",
        "checkins",
        "exercise_sessions",
        "sleep_sessions",
        "pvt_results",
        "risk_scores",
        "alerts",
        "protocol_runs",
        "inventory_items",
        "sync_packets",
        "audit_logs",
    } <= tables
    assert {
        "space_weather_events",
        "consultation_notes",
        "inventory_usages",
        "protocol_requirements",
        "ground_messages",
        "contact_windows",
        "emergency_events",
        "intake_logs",
        "sim_scenarios",
        "sim_runs",
    } <= tables


def test_scenario_s2_score_alert_protocol_roundtrip(db: Session) -> None:
    crew = _crew(db)
    cmo = _crew(db, code="AV-04", access=AccessRole.CMO)
    protocol = _protocol(db)
    db.add(VitalReading(crew_member_id=crew.id, metric=Metric.HRV_RMSSD, value=31, recorded_at=NOW))
    score = RiskScore(
        crew_member_id=crew.id,
        domain=RiskDomain.GLOBAL,
        score=54,
        level=HealthLevel.WARNING,
        factors=[{"feature": "hrv_rmssd", "value": 31, "baseline": 48, "contribution": 0.42}],
    )
    db.add(score)
    db.flush()
    alert = Alert(
        crew_member_id=crew.id,
        risk_score_id=score.id,
        recommended_protocol_id=protocol.id,
        level=AlertLevel.WARNING,
        domain=RiskDomain.BEHAVIORAL,
        method=DetectionMethod.ROBUST_ZSCORE,
        rule_code="HRV-01",
        title="VFC basse persistante",
        message="VFC à 65 % de la baseline et dette de sommeil de 5,5 h",
        metric=Metric.HRV_RMSSD,
        observed_value=31,
        threshold=38.4,
    )
    db.add(alert)
    db.flush()
    db.add(ProtocolRun(protocol_id=protocol.id, alert_id=alert.id, crew_member_id=crew.id))
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = NOW
    alert.acknowledged_by_id = cmo.id
    alert.ack_comment = "Vu, revoir J+144"
    db.commit()

    stored = db.scalars(select(Alert)).one()
    assert stored.crew_member.code == "AV-02"
    assert stored.acknowledged_by.access_role is AccessRole.CMO
    assert stored.risk_score.factors[0]["feature"] == "hrv_rmssd"
    assert stored.protocol_runs[0].status is ProtocolRunStatus.IN_PROGRESS
    assert db.scalars(select(VitalReading)).one().source is DataSource.SENSOR


@pytest.mark.parametrize(
    "model, kwargs",
    [
        (RiskScore, {"domain": RiskDomain.CARDIO, "score": 150, "level": HealthLevel.CRITICAL}),
        (Checkin, {"vision_change": 4}),  # gravité 0..3
        (Checkin, {"stress": 11}),  # échelle 0..10
        (
            RadiationDose,
            {
                "recorded_at": NOW,
                "dose_rate_msv_h": 0.02,
                "mission_cumulative_msv": 90,
                "career_cumulative_msv": 80,  # le cumul carrière inclut la mission
            },
        ),
    ],
)
def test_out_of_range_values_rejected(db: Session, model, kwargs) -> None:
    crew = _crew(db)
    db.add(model(crew_member_id=crew.id, **kwargs))
    with pytest.raises(IntegrityError):
        db.flush()


def test_acknowledged_alert_requires_timestamp(db: Session) -> None:
    crew = _crew(db)
    db.add(
        Alert(
            crew_member_id=crew.id,
            level=AlertLevel.CRITICAL,
            domain=RiskDomain.RADIATION,
            method=DetectionMethod.THRESHOLD,
            status=AlertStatus.ACKNOWLEDGED,
            title="SPE",
            message="Débit de dose anormal",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_deleting_sim_run_purges_its_data(db: Session) -> None:
    crew = _crew(db)
    run = SimRun(scenario=SimScenario(code="S3", name="SPE", duration_seconds=600), seed=42)
    db.add(run)
    db.flush()
    db.add_all(
        [
            VitalReading(
                crew_member_id=crew.id,
                sim_run_id=run.id,
                metric=Metric.SPO2,
                value=88,
                source=DataSource.SIMULATOR,
                recorded_at=NOW,
            ),
            VitalReading(crew_member_id=crew.id, metric=Metric.SPO2, value=98, recorded_at=NOW),
            Checkin(crew_member_id=crew.id, sim_run_id=run.id, stress=7),
            RadiationDose(
                crew_member_id=crew.id,
                sim_run_id=run.id,
                recorded_at=NOW,
                dose_rate_msv_h=1.82,
                mission_cumulative_msv=89.1,
                career_cumulative_msv=189.1,
            ),
            _packet(PRIORITY_CRITICAL, NOW, sim_run_id=run.id),
        ]
    )
    db.commit()

    db.delete(run)
    db.commit()
    assert [r.value for r in db.scalars(select(VitalReading))] == [98]
    for model in (Checkin, RadiationDose, SyncPacket):
        assert db.scalars(select(model)).all() == []


def test_sim_speed_limited_to_x1000(db: Session) -> None:
    db.add(
        SimRun(
            scenario=SimScenario(code="S1", name="Nominal", duration_seconds=60), speed_factor=2000
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_sync_queue_puts_critical_first(db: Session) -> None:
    db.add_all(
        [
            _packet(PRIORITY_LOW, NOW - timedelta(hours=2)),
            _packet(PRIORITY_CRITICAL, NOW),
            _packet(PRIORITY_LOW, NOW - timedelta(hours=1)),
        ]
    )
    db.commit()
    queue = db.scalars(
        select(SyncPacket)
        .where(SyncPacket.status == "queued")
        .order_by(SyncPacket.priority, SyncPacket.created_at)
    ).all()
    assert [p.priority for p in queue] == [PRIORITY_CRITICAL, PRIORITY_LOW, PRIORITY_LOW]
    assert gzip.decompress(queue[0].payload_gz).startswith(b'{"p": 0')


def test_inventory_quantity_cannot_go_negative(db: Session) -> None:
    item = InventoryItem(
        code="MED-PROM-25", name="Prométhazine 25 mg", unit="cp", quantity=6, min_quantity=10
    )
    db.add(item)
    db.flush()
    assert item.is_low_stock
    item.quantity = -1
    with pytest.raises(IntegrityError):
        db.flush()


def test_audit_log_is_append_only_and_chained(db: Session) -> None:
    entry = {
        "at": NOW,
        "actor_label": "Moteur IA",
        "action": "alert.create",
        "entity_type": "alert",
        "entity_id": 1,
        "details": {"rule": "HRV-01"},
    }
    first_hash = AuditLog.compute_hash(GENESIS_HASH, **entry)
    db.add(AuditLog(prev_hash=GENESIS_HASH, entry_hash=first_hash, **entry))
    db.commit()

    second = {**entry, "action": "alert.acknowledge"}
    second_hash = AuditLog.compute_hash(first_hash, **second)
    assert second_hash != AuditLog.compute_hash(GENESIS_HASH, **second)  # dépend du maillon

    for statement in ("UPDATE audit_logs SET action = 'tampered'", "DELETE FROM audit_logs"):
        with pytest.raises(IntegrityError, match="append-only"):
            db.execute(text(statement))
        db.rollback()
    assert db.scalars(select(AuditLog.action)).one() == "alert.create"
