import random
from datetime import datetime
from typing import Dict
from app.schemas.simulateur import ScenarioCode, VitalBatch
from app.sim.nominal import generate_circadian_vitals
from app.sim.scenarios import apply_scenario_modifiers


class TelemetryGenerator:
    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.baselines: Dict[str, Dict[str, float]] = {
            "AV-01": {"hr": 65.0, "hrv_rmssd": 52.0, "sbp": 116.0, "dbp": 75.0, "spo2": 98.5, "temp": 36.7},
            "AV-02": {"hr": 70.0, "hrv_rmssd": 48.0, "sbp": 120.0, "dbp": 78.0, "spo2": 98.0, "temp": 36.8},
            "AV-03": {"hr": 62.0, "hrv_rmssd": 58.0, "sbp": 114.0, "dbp": 72.0, "spo2": 99.0, "temp": 36.6},
            "AV-04": {"hr": 72.0, "hrv_rmssd": 45.0, "sbp": 122.0, "dbp": 80.0, "spo2": 97.8, "temp": 36.9},
        }

    def reseed(self, seed: int) -> None:
        self.rng = random.Random(seed)

    def generate_batch(
        self,
        crew_id: str,
        sim_time: datetime,
        scenario: ScenarioCode,
        elapsed_hours: float,
    ) -> VitalBatch:
        baseline = self.baselines.get(crew_id, self.baselines["AV-01"])
        nominal = generate_circadian_vitals(sim_time, baseline, self.rng)
        perturbed = apply_scenario_modifiers(nominal, scenario, elapsed_hours)

        return VitalBatch(
            crew_id=crew_id,
            timestamp=sim_time,
            **perturbed,
        )