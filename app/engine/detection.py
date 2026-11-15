from pathlib import Path
from typing import Dict, Any
import joblib
import numpy as np
from sklearn.ensemble import IsolationForest


class AnomalyDetector:
    def __init__(self, model_path: str = "app/data/isolation_forest.joblib"):
        self.model_path = Path(model_path)
        self.iso_forest = self._load_or_init_model()

    def _load_or_init_model(self) -> IsolationForest:
        if self.model_path.exists():
            return joblib.load(self.model_path)
        # Initialisation de secours sur une distribution nominale synthétique
        rng = np.random.default_rng(42)
        X_nom = np.column_stack([
            rng.normal(68, 6, 300),     # hr
            rng.normal(50, 7, 300),     # hrv
            rng.normal(118, 7, 300),    # sbp
            rng.normal(36.8, 0.2, 300), # temp
            rng.normal(98.2, 0.5, 300), # spo2
            rng.normal(7.5, 0.5, 300),  # sleep
            rng.normal(22, 6, 300),     # stress
        ])
        clf = IsolationForest(contamination=0.05, random_state=42)
        clf.fit(X_nom)
        return clf

    def detect(self, features: Dict[str, Any], baseline: Dict[str, float]) -> Dict[str, Any]:
        # 1. Z-score robuste simplifié (écart relatif à la baseline)
        z_hr = abs(features["hr"] - baseline.get("hr", 68.0)) / 8.0
        z_hrv = max(0.0, (baseline.get("hrv_rmssd", 50.0) - features["hrv_rmssd"]) / 8.0)
        z_sbp = max(0.0, (features["sbp"] - baseline.get("sbp", 118.0)) / 10.0)
        z_temp = abs(features["temp"] - baseline.get("temp", 36.8)) / 0.3

        # 2. Score multivarié Isolation Forest normalisé entre 0 et 1
        vec = np.array([[
            features["hr"],
            features["hrv_rmssd"],
            features["sbp"],
            features["temp"],
            features["spo2"],
            features["sleep_hours"],
            features["stress_score"],
        ]])
        raw_if_score = -float(self.iso_forest.score_samples(vec)[0])
        iso_anomaly_norm = float(np.clip((raw_if_score - 0.40) / 0.35, 0.0, 1.0))

        return {
            "z_hr": round(z_hr, 2),
            "z_hrv": round(z_hrv, 2),
            "z_sbp": round(z_sbp, 2),
            "z_temp": round(z_temp, 2),
            "iso_score": round(iso_anomaly_norm, 3),
        }