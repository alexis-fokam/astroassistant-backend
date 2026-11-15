from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router, legacy_router, ws_router
from app.api.routes.simulateur import router as sim_router, sim_runner
from app.core.config import get_settings
from app.core.database import engine
from app.models import Base

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # 1. Initialisation des tables SQLite au démarrage
    Base.metadata.create_all(bind=engine)
    # 2. Démarrage de la boucle de simulation de télémétrie
    await sim_runner.start()
    yield
    # 3. Arrêt propre du simulateur à la fermeture de l'API
    await sim_runner.stop()


app = FastAPI(
    title=settings.app_name,
    summary="Mentor IA de surveillance de santé de l'équipage (NASA Space Apps 2026)",
    version=settings.version,
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(legacy_router, include_in_schema=False)
app.include_router(ws_router)
app.include_router(sim_router)