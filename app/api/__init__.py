from fastapi import APIRouter

from app.api.routes import health, ws

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)

ws_router = APIRouter()
ws_router.include_router(ws.router)
