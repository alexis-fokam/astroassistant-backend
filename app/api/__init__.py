"""API REST sous /api/v1 (cahier des charges §10) et WebSocket temps réel."""

from fastapi import APIRouter

from app.api.routes import care, crew, engine, ground, health, history, telemetry, ws

api_router = APIRouter(prefix="/api/v1")
for module in (health, crew, telemetry, care, engine, ground, history):
    api_router.include_router(module.router)

# Gardé pour les clients existants : GET /api/health.
legacy_router = APIRouter(prefix="/api")
legacy_router.include_router(health.router)

ws_router = APIRouter()
ws_router.include_router(ws.router)
