import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional
from app.schemas.simulateur import ScenarioCode
from app.sim.generator import TelemetryGenerator


class SimulationRunner:
    def __init__(self, telemetry_service):
        self.telemetry_service = telemetry_service
        self.generator = TelemetryGenerator(seed=42)
        self.active_scenario: ScenarioCode = ScenarioCode.S1
        self.target_crew_id: str = "AV-01"
        self.speed_multiplier: int = 1
        self.sim_time: datetime = datetime.now(timezone.utc)
        self.scenario_start_time: datetime = self.sim_time
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

    def set_scenario(self, scenario: ScenarioCode, crew_id: str = "AV-01", seed: Optional[int] = 42) -> None:
        if seed is not None:
            self.generator.reseed(seed)
        self.active_scenario = scenario
        self.target_crew_id = crew_id
        self.scenario_start_time = self.sim_time

    def set_speed(self, multiplier: int) -> None:
        self.speed_multiplier = max(1, min(1000, multiplier))

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        tick_real_seconds = 2.0  # Fréquence de rafraîchissement < 2s (Exigence F1.8)
        while self._running:
            simulated_delta = timedelta(seconds=tick_real_seconds * self.speed_multiplier)
            self.sim_time += simulated_delta
            elapsed_hours = (self.sim_time - self.scenario_start_time).total_seconds() / 3600.0

            for crew_id in self.generator.baselines.keys():
                scen = self.active_scenario if crew_id == self.target_crew_id else ScenarioCode.S1
                batch = self.generator.generate_batch(
                    crew_id=crew_id,
                    sim_time=self.sim_time,
                    scenario=scen,
                    elapsed_hours=elapsed_hours if scen != ScenarioCode.S1 else 0.0,
                )
                await self.telemetry_service.ingest_and_process(batch)

            await asyncio.sleep(tick_real_seconds)