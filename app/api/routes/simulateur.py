from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.schemas.simulateur import (
    EngineEvaluationResponse,
    ScenarioRequest,
    SpeedRequest,
    VitalBatch,
)
from app.services.telemetry import telemetry_service
from app.sim.runner import SimulationRunner

router = APIRouter(prefix="/api/v1", tags=["Simulation & Moteur"])
sim_runner = SimulationRunner(telemetry_service=telemetry_service)


@router.post("/sim/scenario")
async def trigger_scenario(req: ScenarioRequest):
    """Injecte un scénario de démo (S1 à S6) sur un membre d'équipage."""
    sim_runner.set_scenario(scenario=req.scenario, crew_id=req.crew_id, seed=req.seed)
    await sim_runner.start()
    return {
        "message": f"Scénario {req.scenario.value} activé pour {req.crew_id}",
        "speed_multiplier": sim_runner.speed_multiplier,
    }


@router.post("/sim/speed")
async def set_simulation_speed(req: SpeedRequest):
    """Règle le facteur d'accélération du temps simulé (x1 à x1000)."""
    sim_runner.set_speed(req.speed_multiplier)
    return {"speed_multiplier": sim_runner.speed_multiplier}


@router.post("/vitals", response_model=EngineEvaluationResponse)
async def ingest_vitals(batch: VitalBatch):
    """Point d'ingestion manuel ou capteur externe passant directement dans le moteur."""
    return await telemetry_service.ingest_and_process(batch)


@router.get("/crew/{crew_id}/status", response_model=EngineEvaluationResponse | None)
async def get_crew_status(crew_id: str):
    """Retourne le dernier état évalué par le moteur IA pour un astronaute."""
    return telemetry_service.latest_states.get(crew_id)


@router.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket):
    """Flux temps réel poussant les constantes et scores au dashboard Nuxt."""
    await telemetry_service.connect_ws(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        telemetry_service.disconnect_ws(websocket)