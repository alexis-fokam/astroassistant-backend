"""API REST (§10) testée sur une copie de la base de démo remplie."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import get_db
from app.main import app
from app.models import Base
from app.seed import DEMO_PINS, seed


def _engine(path: Path):
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, _record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


@pytest.fixture(scope="session")
def demo_db(tmp_path_factory) -> Path:
    """Remplir une fois, puis chaque test travaille sur sa propre copie du fichier."""
    path = tmp_path_factory.mktemp("demo") / "demo.db"
    engine = _engine(path)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed(session)
    engine.dispose()
    return path


@pytest.fixture
def client(demo_db: Path, tmp_path: Path) -> Iterator[TestClient]:
    copy = tmp_path / "test.db"
    shutil.copy(demo_db, copy)
    engine = _engine(copy)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _db() -> Iterator[Session]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


def login(client: TestClient, code: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"code": code, "pin": DEMO_PINS[code]})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def astronaut(client: TestClient) -> dict[str, str]:
    return login(client, "AV-02")


@pytest.fixture
def cmo(client: TestClient) -> dict[str, str]:
    return login(client, "AV-04")


# --------------------------------------------------------------------- auth & RBAC
def test_wrong_pin_is_rejected_and_audited(client: TestClient, cmo) -> None:
    response = client.post("/api/v1/auth/login", json={"code": "AV-02", "pin": "0000"})
    assert response.status_code == 401
    trail = client.get("/api/v1/audit", headers=cmo, params={"action": "auth"}).json()
    assert {e["action"] for e in trail} >= {"auth.failed", "auth.login"}


def test_routes_require_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/crew").status_code == 401
    bad = {"Authorization": "Bearer 1.9999999999.forged"}
    assert client.get("/api/v1/crew", headers=bad).status_code == 401


def test_astronaut_only_sees_own_data(client: TestClient, astronaut) -> None:
    crew = client.get("/api/v1/crew", headers=astronaut).json()
    assert [m["code"] for m in crew] == ["AV-02"]
    assert client.get("/api/v1/crew/AV-03/status", headers=astronaut).status_code == 403
    assert (
        client.get(
            "/api/v1/vitals/AV-03", headers=astronaut, params={"type": "heart_rate"}
        ).status_code
        == 403
    )
    alerts = client.get("/api/v1/alerts", headers=astronaut).json()
    assert {a["crew_code"] for a in alerts} == {"AV-02"}
    assert client.get("/api/v1/audit", headers=astronaut).status_code == 403


def test_cmo_sees_whole_crew(client: TestClient, cmo) -> None:
    crew = client.get("/api/v1/crew", headers=cmo).json()
    assert [m["code"] for m in crew] == ["AV-01", "AV-02", "AV-03", "AV-04"]
    assert {m["code"]: m["status"] for m in crew}["AV-03"] == "critical"


# --------------------------------------------------------------------- status & telemetry
def test_mission_clock_follows_demo_history(client: TestClient, astronaut) -> None:
    mission = client.get("/api/v1/mission", headers=astronaut).json()
    assert mission["code"] == "ARTEMIS-M"
    assert mission["mission_day"] == 142
    assert mission["next_contact_at"] is not None


def test_status_matches_spec_example(client: TestClient, astronaut) -> None:
    body = client.get("/api/v1/crew/AV-02/status", headers=astronaut).json()
    assert body["crew_id"] == "AV-02"
    assert body["status"] == "warning"
    assert body["global_score"] == 54
    assert body["domains"]["behavioral"] == 68
    assert body["top_factors"][0]["feature"] == "hrv_rmssd"
    assert body["recommended_protocol"] == "PRT-STRESS-01"
    assert body["active_alerts"][0]["title"] == "VFC basse persistante"


def test_vitals_ingest_then_read(client: TestClient, astronaut) -> None:
    series = client.get(
        "/api/v1/vitals/AV-02", headers=astronaut, params={"type": "hrv_rmssd"}
    ).json()
    assert series["unit"] == "ms" and len(series["points"]) > 24
    last = series["points"][-1]["t"]

    batch = {
        "readings": [{"metric": "hrv_rmssd", "value": 41, "recorded_at": "2026-10-13T14:10:00Z"}]
    }
    response = client.post("/api/v1/vitals", headers=astronaut, json=batch)
    assert response.status_code == 201 and response.json()["accepted"] == 1

    series = client.get(
        "/api/v1/vitals/AV-02",
        headers=astronaut,
        params={"type": "hrv_rmssd", "from": last, "to": "2026-10-13T15:00:00Z"},
    ).json()
    assert series["points"][-1]["value"] == 41


def test_invalid_vitals_are_rejected(client: TestClient, astronaut) -> None:
    batch = {"readings": [{"metric": "heart_rate", "value": 70, "recorded_at": "x"}]}
    assert client.post("/api/v1/vitals", headers=astronaut, json=batch).status_code == 422


def test_radiation_projection(client: TestClient, astronaut) -> None:
    body = client.get("/api/v1/radiation/AV-02", headers=astronaut).json()
    assert body["mission_cumulative_msv"] > 0
    assert body["career_cumulative_msv"] >= body["mission_cumulative_msv"]
    assert body["projected_mission_end_msv"] > body["mission_cumulative_msv"]
    assert 0 < body["career_used_pct"] < 100
    assert body["history"]


def test_self_reports(client: TestClient, astronaut) -> None:
    checkin = client.post("/api/v1/checkins", headers=astronaut, json={"stress": 6, "headache": 1})
    assert checkin.status_code == 201
    assert (
        client.post("/api/v1/checkins", headers=astronaut, json={"stress": 11}).status_code == 422
    )
    exercise = {"kind": "resistance", "scheduled_at": "2026-10-13T08:00:00Z", "duration_min": 45}
    assert client.post("/api/v1/exercises", headers=astronaut, json=exercise).status_code == 201
    pvt = {"stimuli_count": 30, "median_rt_ms": 270, "lapses": 1}
    assert client.post("/api/v1/pvt", headers=astronaut, json=pvt).status_code == 201


# --------------------------------------------------------------------- alerts & protocols
def test_alert_queue_and_acknowledgement(client: TestClient, astronaut, cmo) -> None:
    queue = client.get("/api/v1/alerts", headers=cmo).json()
    assert queue[0]["level"] == "critical" and queue[0]["crew_code"] == "AV-03"
    hrv = next(a for a in queue if a["title"] == "VFC basse persistante")

    patch = {"status": "acknowledged", "comment": "Respiration guidée lancée"}
    assert (
        client.patch(f"/api/v1/alerts/{hrv['id']}", headers=astronaut, json=patch).status_code
        == 403
    )
    acked = client.patch(f"/api/v1/alerts/{hrv['id']}", headers=cmo, json=patch).json()
    assert acked["status"] == "acknowledged" and acked["acknowledged_by"] == "AV-04"
    assert client.patch(f"/api/v1/alerts/{hrv['id']}", headers=cmo, json=patch).status_code == 409
    resolved = client.patch(
        f"/api/v1/alerts/{hrv['id']}", headers=cmo, json={"status": "resolved"}
    ).json()
    assert resolved["resolved_at"] is not None


def test_protocol_run_follows_steps_in_order(client: TestClient, astronaut) -> None:
    protocol = client.get("/api/v1/protocols/PRT-STRESS-01", headers=astronaut).json()
    codes = [s["code"] for s in protocol["steps"]]
    assert protocol["ready"] is True and codes[0] == "settle"

    run = client.post("/api/v1/protocols/PRT-STRESS-01/runs", headers=astronaut, json={}).json()
    assert run["next_step"] == "settle"
    url = f"/api/v1/protocols/runs/{run['id']}"
    assert client.patch(url, headers=astronaut, json={"step_code": codes[1]}).status_code == 422
    assert client.patch(url, headers=astronaut, json={"status": "completed"}).status_code == 422
    for code in codes:
        run = client.patch(url, headers=astronaut, json={"step_code": code}).json()
    assert run["next_step"] is None
    done = client.patch(
        url, headers=astronaut, json={"status": "completed", "efficacy": 0.8}
    ).json()
    assert done["status"] == "completed"


def test_protocol_runs_list_respects_rbac(client: TestClient, astronaut, cmo) -> None:
    mine = client.get("/api/v1/protocols/runs", headers=astronaut).json()
    assert mine and {r["crew_code"] for r in mine} == {"AV-02"}
    stress = next(r for r in mine if r["protocol_code"] == "PRT-STRESS-01")
    assert stress["trigger"].startswith("HRV-01") and stress["total_steps"] == 4
    assert stress["status"] == "in_progress" and stress["next_step"] == "hrv_check"
    everyone = client.get("/api/v1/protocols/runs", headers=cmo).json()
    assert {r["crew_code"] for r in everyone} == {"AV-01", "AV-02", "AV-03", "AV-04"}
    done = client.get("/api/v1/protocols/runs", headers=cmo, params={"status": "completed"}).json()
    assert done and all(r["status"] == "completed" for r in done)
    assert (
        client.get(
            "/api/v1/protocols/runs", headers=astronaut, params={"crew": "AV-03"}
        ).status_code
        == 403
    )
    # « runs » ne doit pas être pris pour un code de protocole.
    assert client.get("/api/v1/protocols/PRT-STRESS-01", headers=astronaut).status_code == 200


def test_protocol_materials_reflect_stock(client: TestClient, astronaut) -> None:
    emergency = client.get("/api/v1/protocols/EMRG-01", headers=astronaut).json()
    required = {m["item_code"] for m in emergency["materials"] if not m["optional"]}
    assert required == {"EQ-OXIMETER", "EQ-BP-CUFF", "EQ-O2-PORT"}


# --------------------------------------------------------------------- pharmacy & emergency
def test_only_cmo_records_pharmacy_use(client: TestClient, astronaut, cmo) -> None:
    items = {i["code"]: i for i in client.get("/api/v1/inventory", headers=astronaut).json()}
    assert items["CONS-BANDAGE"]["is_low_stock"] is True
    use = {"item_code": "MED-PARA-500", "quantity": 2, "patient_code": "AV-04"}
    assert client.post("/api/v1/inventory", headers=astronaut, json=use).status_code == 403
    response = client.post("/api/v1/inventory", headers=cmo, json=use).json()
    assert response["remaining"] == items["MED-PARA-500"]["quantity"] - 2
    too_much = {"item_code": "MED-PROM-25", "quantity": 999}
    assert client.post("/api/v1/inventory", headers=cmo, json=too_much).status_code == 409


def test_emergency_lifecycle_queues_critical_packet(client: TestClient, astronaut, cmo) -> None:
    event = client.post("/api/v1/emergency", headers=astronaut, json={}).json()
    assert event["status"] == "active" and event["patient_code"] == "AV-02"
    queue = client.get("/api/v1/sync/packets", headers=cmo).json()
    assert queue[0]["priority"] == 0 and queue[0]["kind"] in {"emergency", "alert"}

    client.post(
        f"/api/v1/emergency/{event['id']}/steps", headers=astronaut, params={"code": "secure"}
    )
    close = {"outcome": "stabilisée", "summary": "Malaise résolu."}
    assert (
        client.post(
            f"/api/v1/emergency/{event['id']}/close", headers=astronaut, json=close
        ).status_code
        == 403
    )
    closed = client.post(f"/api/v1/emergency/{event['id']}/close", headers=cmo, json=close).json()
    assert closed["status"] == "closed" and closed["steps"][0]["code"] == "secure"


# --------------------------------------------------------------------- reports, sync, sim, audit
def test_weekly_report(client: TestClient, astronaut) -> None:
    report = client.get(
        "/api/v1/reports/AV-02", headers=astronaut, params={"period": "week"}
    ).json()
    assert report["checkins"] == 7
    assert report["sleep_hours_avg"] < 7.5
    assert report["vitals"]["heart_rate"]["mean"] > 0
    assert report["alerts"]["warning"] >= 1


def test_export_packet_is_signed_and_queue_is_ordered(client: TestClient, astronaut) -> None:
    body = client.post("/api/v1/sync/export", headers=astronaut, json={}).json()
    assert set(body["content"]["crew"]) == {"AV-01", "AV-02", "AV-03", "AV-04"}
    assert len(body["packet"]["sha256"]) == 64
    priorities = [p["priority"] for p in body["queue"]]
    assert priorities == sorted(priorities)


def test_ground_import_checks_integrity(client: TestClient, astronaut) -> None:
    text = "Boire 500 ml d'eau supplémentaires par jour."
    good = {
        "author": "Dr M. Reyes",
        "body": text,
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }
    assert client.post("/api/v1/sync/import", headers=astronaut, json=good).status_code == 201
    assert client.post("/api/v1/sync/import", headers=astronaut, json=good).status_code == 409
    tampered = {**good, "body": text + " (modifié)"}
    assert client.post("/api/v1/sync/import", headers=astronaut, json=tampered).status_code == 422
    inbox = client.get("/api/v1/sync/messages", headers=astronaut).json()
    assert any(m["body"] == text for m in inbox)


def test_simulation_controls(client: TestClient, cmo) -> None:
    run = client.post(
        "/api/v1/sim/scenario", headers=cmo, json={"code": "S3", "speed_factor": 120}
    ).json()
    assert run["status"] == "running" and run["crew_code"] is None
    faster = client.post(
        "/api/v1/sim/speed", headers=cmo, json={"run_id": run["id"], "speed_factor": 600}
    ).json()
    assert faster["speed_factor"] == 600
    assert (
        client.post(
            "/api/v1/sim/speed", headers=cmo, json={"run_id": run["id"], "speed_factor": 5000}
        ).status_code
        == 422
    )
    second = client.post("/api/v1/sim/scenario", headers=cmo, json={"code": "S2"}).json()
    assert second["crew_code"] == "AV-02"
    runs = {r["id"]: r["status"] for r in client.get("/api/v1/sim/runs", headers=cmo).json()}
    assert runs[run["id"]] == "aborted"


def test_audit_chain_stays_valid_after_api_writes(client: TestClient, astronaut, cmo) -> None:
    client.post("/api/v1/checkins", headers=astronaut, json={"stress": 5})
    client.post("/api/v1/sync/export", headers=astronaut, json={})
    verdict = client.get("/api/v1/audit/verify", headers=cmo).json()
    assert verdict["valid"] is True and verdict["entries"] > 80


def test_datasets_are_public(client: TestClient) -> None:
    datasets = {d["code"]: d for d in client.get("/api/v1/datasets").json()}
    assert datasets["nasa-msl-rad"]["record_count"] > 1000
    assert datasets["nasa-msl-rad"]["agency"] == "NASA"


# --------------------------------------------------------------------- risk engine
def test_engine_routes(client: TestClient, astronaut, cmo) -> None:
    status_body = client.get("/api/v1/engine/status", headers=astronaut).json()
    assert {r["code"] for r in status_body["rules"]} >= {"HRV-01", "SANS-01", "RAD-SPE-01"}
    assert client.post("/api/v1/engine/run", headers=astronaut).status_code == 403

    report = client.post("/api/v1/engine/run", headers=cmo).json()
    levels = {m["code"]: m["status"] for m in report["members"]}
    assert levels == {
        "AV-01": "warning",
        "AV-02": "warning",
        "AV-03": "critical",
        "AV-04": "warning",
    }

    # La route de statut sert maintenant les scores du moteur.
    status_av02 = client.get("/api/v1/crew/AV-02/status", headers=astronaut).json()
    assert status_av02["status"] == "warning" and status_av02["top_factors"]

    alerts = client.get("/api/v1/alerts", headers=astronaut).json()
    hrv = next(a for a in alerts if a["rule_code"] == "HRV-01")
    explanation = client.get(f"/api/v1/alerts/{hrv['id']}/explanation", headers=astronaut).json()
    assert explanation["confirmations"] == 2 and "hrv_ratio" in explanation["rule"]

    history = client.get("/api/v1/crew/AV-02/domains/behavioral", headers=astronaut).json()
    assert history["history"] and history["level"] == "warning"


# --------------------------------------------------------------------- PR #6 routes
def test_profiles_are_public_and_carry_no_health_data(client: TestClient) -> None:
    profiles = client.get("/api/v1/profiles").json()
    assert [p["code"] for p in profiles] == ["AV-01", "AV-02", "AV-03", "AV-04"]
    assert [p["code"] for p in profiles if p["is_cmo"]] == ["AV-04"]
    assert all(
        set(p) == {"code", "first_name", "last_name", "crew_role", "is_cmo"} for p in profiles
    )


def test_latest_vitals_respect_rbac(client: TestClient, astronaut, cmo) -> None:
    own = client.get("/api/v1/crew/AV-02/vitals/latest", headers=astronaut)
    assert own.status_code == 200
    hr = own.json()["vitals"]["heart_rate"]
    assert hr["unit"] == "bpm" and hr["value"] is not None and len(hr["points"]) == 36
    assert hr["normal_band"]["low"] < hr["normal_band"]["high"]
    # Un astronaute ne doit pas lire les constantes d'un autre membre (§7).
    assert client.get("/api/v1/crew/AV-03/vitals/latest", headers=astronaut).status_code == 403
    assert client.get("/api/v1/crew/AV-03/vitals/latest", headers=cmo).status_code == 200
    assert client.get("/api/v1/crew/AV-99/vitals/latest", headers=cmo).status_code == 404
    assert client.get("/api/v1/crew/AV-02/vitals/latest").status_code == 401


def test_mission_exposes_next_contact_time(client: TestClient, astronaut) -> None:
    mission = client.get("/api/v1/mission", headers=astronaut).json()
    assert mission["next_contact_time"] and len(mission["next_contact_time"]) == 8
    assert mission["clock"] == "J+142 · 14:05"
    assert 0 <= mission["next_contact_in_s"] <= 12 * 3600


def test_vital_card_levels_follow_engine_thresholds() -> None:
    from types import SimpleNamespace

    from app.models.enums import HealthLevel, Metric
    from app.services.vitals import level_for

    hrv_baseline = SimpleNamespace(mean=48.0, median=48.0, mad=4.0)
    assert level_for(Metric.HRV_RMSSD, 31, hrv_baseline) is HealthLevel.WARNING  # 65 %
    assert level_for(Metric.HRV_RMSSD, 25, hrv_baseline) is HealthLevel.CRITICAL  # 52 %
    assert level_for(Metric.HRV_RMSSD, 60, hrv_baseline) is HealthLevel.NOMINAL  # hausse : OK
    assert level_for(Metric.SPO2, 92, None) is HealthLevel.WARNING
    assert level_for(Metric.SPO2, 90, None) is HealthLevel.CRITICAL
    assert level_for(Metric.CORE_TEMPERATURE, 38.2, None) is HealthLevel.WARNING


def test_history_lists_respect_rbac_and_pagination(client: TestClient, astronaut, cmo) -> None:
    for kind in ("checkins", "sleep", "exercises", "pvt"):
        own = client.get(f"/api/v1/{kind}/AV-02", headers=astronaut, params={"limit": 3}).json()
        assert own["total"] > 0 and len(own["items"]) == min(3, own["total"]), kind
        assert client.get(f"/api/v1/{kind}/AV-03", headers=astronaut).status_code == 403
        assert (
            client.get(f"/api/v1/{kind}/AV-03", headers=cmo).status_code == 200
        )  # CMO: whole crew
    checkins = client.get("/api/v1/checkins/AV-02", headers=astronaut).json()["items"]
    stamps = [c["submitted_at"] for c in checkins]
    assert stamps == sorted(stamps, reverse=True)
    assert checkins[0]["stress"] == 7  # histoire S2 : stress déclaré à 7/10
    page2 = client.get(
        "/api/v1/sleep/AV-02", headers=astronaut, params={"limit": 2, "offset": 2}
    ).json()
    assert page2["offset"] == 2 and len(page2["items"]) == 2
