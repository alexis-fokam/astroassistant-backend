from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_websocket_hello() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        assert ws.receive_json() == {"type": "hello"}


def test_errors_are_clear_json() -> None:
    from fastapi import APIRouter

    with TestClient(app, raise_server_exceptions=False) as client:
        invalid = client.post("/api/v1/auth/login", json={"code": "AV-02", "pin": "ab"})
        assert invalid.status_code == 422
        body = invalid.json()
        assert body["detail"] == "Données invalides" and body["erreurs"][0]["champ"] == "pin"

        boom = APIRouter()

        @boom.get("/api/v1/__boom")
        def _boom():
            raise RuntimeError("secret internal detail")

        app.include_router(boom)
        crash = client.get("/api/v1/__boom")
        assert crash.status_code == 500
        assert "secret" not in crash.text and "journalisé" in crash.json()["detail"]
