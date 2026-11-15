"""REST API under /api/v1 (spec §10) and the realtime WebSocket."""

from fastapi import APIRouter

from app.api.routes import care, crew, ground, health, history, telemetry, ws

api_router = APIRouter(prefix="/api/v1")
for module in (health, crew, telemetry, care, ground, history):
    api_router.include_router(module.router)

# Kept for existing clients: GET /api/health.
legacy_router = APIRouter(prefix="/api")
legacy_router.include_router(health.router)

ws_router = APIRouter()
ws_router.include_router(ws.router)
