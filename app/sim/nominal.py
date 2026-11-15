import math
import random
from datetime import datetime
from typing import Dict


def generate_circadian_vitals(
    sim_time: datetime,
    baseline: Dict[str, float],
    rng: random.Random,
) -> Dict[str, float]:
    """Calcule les constantes nominales modulées par l'heure circadienne et un bruit gaussien."""
    hour = sim_time.hour + sim_time.minute / 60.0
    # Phase circadienne : pic l'après-midi (~16h), creux la nuit (~4h)
    circadian_phase = math.sin(2 * math.pi * (hour - 10) / 24.0)

    hr = baseline.get("hr", 68.0) + 6.0 * circadian_phase + rng.gauss(0, 2.0)
    hrv = baseline.get("hrv_rmssd", 50.0) - 5.0 * circadian_phase + rng.gauss(0, 2.5)
    sbp = baseline.get("sbp", 118.0) + 4.0 * circadian_phase + rng.gauss(0, 3.0)
    dbp = baseline.get("dbp", 76.0) + 2.5 * circadian_phase + rng.gauss(0, 2.0)
    temp = baseline.get("temp", 36.8) + 0.3 * circadian_phase + rng.gauss(0, 0.08)
    spo2 = min(100.0, max(95.0, baseline.get("spo2", 98.0) + rng.gauss(0, 0.3)))

    return {
        "hr": round(hr, 1),
        "hrv_rmssd": round(max(10.0, hrv), 1),
        "sbp": round(sbp, 1),
        "dbp": round(dbp, 1),
        "spo2": round(spo2, 1),
        "temp": round(temp, 2),
        "radiation_rate_msv_h": round(max(0.0001, 0.00025 + rng.gauss(0, 0.00003)), 6),
        "radiation_cumul_pct": 15.0,
        "sleep_hours": 7.5,
        "sleep_debt_h": 0.5,
        "exercise_adherence_pct": 95.0,
        "stress_score": round(max(5.0, 22.0 + rng.gauss(0, 3.0)), 1),
        "blurred_vision": False,
        "headache_intensity": 0,
    }