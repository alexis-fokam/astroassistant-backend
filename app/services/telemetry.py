from typing import Dict, List
from fastapi import WebSocket
from app.schemas.simulateur import EngineEvaluationResponse, VitalBatch
from app.engine.entrypoint import HealthEngineEntrypoint


class TelemetryService:
    def __init__(self):
        self.engine = HealthEngineEntrypoint()
        self.latest_states: Dict[str, EngineEvaluationResponse] = {}
        self.latest_vitals: Dict[str, VitalBatch] = {}
        self.active_connections: List[WebSocket] = []

    async def connect_ws(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect_ws(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def ingest_and_process(self, batch: VitalBatch) -> EngineEvaluationResponse:
        # Inférence locale via le point d'entrée unique du moteur
        evaluation = self.engine.process_batch(batch)

        # Mise en cache mémoire (à compléter par l'insertion SQLAlchemy SQLite)
        self.latest_vitals[batch.crew_id] = batch
        self.latest_states[batch.crew_id] = evaluation

        # Diffusion temps réel via WebSocket (F1.8)
        payload = {
            "vitals": batch.model_dump(mode="json"),
            "evaluation": evaluation.model_dump(mode="json"),
        }
        for connection in list(self.active_connections):
            try:
                await connection.send_json(payload)
            except Exception:
                self.disconnect_ws(connection)

        return evaluation


# Instances partagées (Singletons d'application)
telemetry_service = TelemetryService()