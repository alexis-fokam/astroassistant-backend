"""Live simulator: injected anomalies must be detected by the risk engine (jury demo)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.sim.controller import controller
from tests.test_api import client, demo_db, login  # noqa: F401 (pytest fixtures)


@pytest.fixture(autouse=True)
def fresh_controller():
    controller.reset()
    yield
    controller.reset()


@pytest.fixture
def cmo(client: TestClient) -> dict[str, str]:  # noqa: F811
    return login(client, "AV-04")


def start(api: TestClient, headers, code: str = "S1", speed: int = 60, crew: str | None = None):
    body = {"code": code, "speed_factor": speed, **({"crew_code": crew} if crew else {})}
    response = api.post("/api/v1/sim/scenario", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def new_alerts(api: TestClient, headers, crew: str) -> dict[str, dict]:
    alerts = api.get("/api/v1/alerts", headers=headers, params={"crew": crew}).json()
    return {a["rule_code"]: a for a in alerts}


def test_inject_requires_a_running_scenario(client: TestClient, cmo) -> None:  # noqa: F811
    body = {"anomaly": "fever", "crew_code": "AV-01"}
    assert client.post("/api/v1/sim/inject", headers=cmo, json=body).status_code == 409
    assert client.post("/api/v1/sim/tick", headers=cmo).status_code == 409


def test_nominal_ticks_advance_the_mission_clock(client: TestClient, cmo) -> None:  # noqa: F811
    before = client.get("/api/v1/mission", headers=cmo).json()["mission_time"]
    start(client, cmo, "S1", speed=60)
    state = client.post("/api/v1/sim/tick", headers=cmo, params={"count": 5}).json()
    assert state["ticks"] == 5 and state["effects"] == []
    after = client.get("/api/v1/mission", headers=cmo).json()["mission_time"]
    assert after > before  # telemetry flows: 5 ticks × 2 s × 60 = 10 simulated minutes


def test_injected_tachycardia_is_detected_live(client: TestClient, cmo) -> None:  # noqa: F811
    start(client, cmo, "S1", speed=60)
    state = client.post(
        "/api/v1/sim/inject", headers=cmo, json={"anomaly": "tachycardia", "crew_code": "AV-01"}
    ).json()
    assert state["effects"][0]["expected_rules"] == ["CARDIO-CRIT-01"]
    state = client.post("/api/v1/sim/tick", headers=cmo, params={"count": 20}).json()

    alerts = new_alerts(client, cmo, "AV-01")
    assert "CARDIO-CRIT-01" in alerts
    assert alerts["CARDIO-CRIT-01"]["level"] == "critical"
    assert any(e["kind"] == "alert" and e["crew"] == "AV-01" for e in state["events"])
    status = client.get("/api/v1/crew/AV-01/status", headers=cmo).json()
    assert status["status"] == "critical"


def test_solar_storm_scenario_alerts_the_whole_crew(client: TestClient, cmo) -> None:  # noqa: F811
    start(client, cmo, "S3", speed=60)
    client.post("/api/v1/sim/tick", headers=cmo, params={"count": 4})
    for crew in ("AV-01", "AV-02", "AV-03", "AV-04"):
        alerts = new_alerts(client, cmo, crew)
        assert "RAD-SPE-01" in alerts, crew
        assert alerts["RAD-SPE-01"]["recommended_protocol"] == "PRT-RAD-02"
    radiation = client.get("/api/v1/radiation/AV-02", headers=cmo).json()
    assert radiation["dose_rate_msv_h"] > 1


def test_fever_is_detected_after_confirmation(client: TestClient, cmo) -> None:  # noqa: F811
    start(client, cmo, "S1", speed=60)
    client.post("/api/v1/sim/inject", headers=cmo, json={"anomaly": "fever", "crew_code": "AV-02"})
    client.post("/api/v1/sim/tick", headers=cmo, params={"count": 40})
    assert "TEMP-01" in new_alerts(client, cmo, "AV-02")


def test_speed_and_stop(client: TestClient, cmo) -> None:  # noqa: F811
    run = start(client, cmo, "S1", speed=60)
    client.post("/api/v1/sim/speed", headers=cmo, json={"run_id": run["id"], "speed_factor": 600})
    assert client.get("/api/v1/sim/state", headers=cmo).json()["speed_factor"] == 600
    stopped = client.post(f"/api/v1/sim/runs/{run['id']}/stop", headers=cmo).json()
    assert stopped["status"] == "completed"


def test_contact_window_scenario_sends_a_packet(client: TestClient, cmo) -> None:  # noqa: F811
    start(client, cmo, "S6", speed=60)
    packets = client.get("/api/v1/sync/packets", headers=cmo, params={"queued_only": False}).json()
    assert any(p["kind"] == "daily_summary" and p["sent_at"] for p in packets)
    anomalies = client.get("/api/v1/sim/anomalies", headers=cmo).json()
    assert {a["code"] for a in anomalies} >= {"tachycardia", "radiation", "fever"}


# --------------------------------------------------------------------- communication delay
def test_ground_instruction_arrives_after_the_delay(client: TestClient, cmo) -> None:  # noqa: F811
    astronaut = login(client, "AV-02")
    body = {
        "crew_code": "AV-02",
        "subject": "Hydratation",
        "body": "Boire 500 ml de plus aujourd'hui.",
    }
    sent = client.post("/api/v1/ground/instructions", headers=cmo, json=body).json()
    assert sent["in_transit"] is True  # Mars transit: 12 min one way
    onboard = client.get("/api/v1/sync/messages", headers=astronaut).json()
    assert all(m["subject"] != "Hydratation" for m in onboard)

    start(client, cmo, "S1", speed=60)  # 2 simulated minutes per tick
    client.post("/api/v1/sim/tick", headers=cmo, params={"count": 7})
    onboard = client.get("/api/v1/sync/messages", headers=astronaut).json()
    assert any(m["subject"] == "Hydratation" and not m["in_transit"] for m in onboard)
    ground = client.get("/api/v1/ground/instructions", headers=cmo).json()
    assert any(m["subject"] == "Hydratation" for m in ground)


def test_packets_and_alerts_show_ground_reception_time(client: TestClient, cmo) -> None:  # noqa: F811
    from datetime import datetime

    start(client, cmo, "S6", speed=60)
    packet = next(
        p
        for p in client.get(
            "/api/v1/sync/packets", headers=cmo, params={"queued_only": False}
        ).json()
        if p["kind"] == "daily_summary" and p["sent_at"]
    )
    delay = datetime.fromisoformat(packet["received_at_ground"]) - datetime.fromisoformat(
        packet["sent_at"]
    )
    assert delay.total_seconds() == 720 and packet["in_transit"] is True
    alert = client.get("/api/v1/alerts", headers=cmo).json()[0]
    gap = datetime.fromisoformat(alert["ground_received_at"]) - datetime.fromisoformat(
        alert["triggered_at"]
    )
    assert gap.total_seconds() == 720


def test_mission_profile_sets_the_delay(client: TestClient, cmo) -> None:  # noqa: F811
    astronaut = login(client, "AV-02")
    patch = {"destination": "moon"}
    assert client.patch("/api/v1/mission", headers=astronaut, json=patch).status_code == 403
    mission = client.patch("/api/v1/mission", headers=cmo, json=patch).json()
    assert mission["destination"] == "moon" and mission["one_way_latency_s"] == 3
    mars = client.patch("/api/v1/mission", headers=cmo, json={"destination": "mars_surface"}).json()
    assert mars["one_way_latency_s"] == 1320 and mars["day_length_min"] == 1477
