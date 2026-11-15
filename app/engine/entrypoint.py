from collections import deque
from typing import Dict, Deque
from app.schemas.simulateur import EngineEvaluationResponse, VitalBatch
from app.engine.preprocessing import preprocess_history
from app.engine.features import extract_features
from app.engine.detection import AnomalyDetector
from app.engine.scoring import compute_domain_scores, compute_global_score
from app.engine.rules import ClinicalRulesEngine


class HealthEngineEntrypoint:
    """Orchestrateur unique de la chaîne analytique (Étapes 2 à 6 du cahier des charges)."""

    def __init__(self, window_size: int = 30):
        self.window_size = window_size
        self.buffers: Dict[str, Deque[VitalBatch]] = {}
        self.detector = AnomalyDetector()
        self.rules_engine = ClinicalRulesEngine()
        self.baselines: Dict[str, Dict[str, float]] = {
            "AV-01": {"hr": 65.0, "hrv_rmssd": 52.0, "sbp": 116.0, "dbp": 75.0, "spo2": 98.5, "temp": 36.7},
            "AV-02": {"hr": 70.0, "hrv_rmssd": 48.0, "sbp": 120.0, "dbp": 78.0, "spo2": 98.0, "temp": 36.8},
            "AV-03": {"hr": 62.0, "hrv_rmssd": 58.0, "sbp": 114.0, "dbp": 72.0, "spo2": 99.0, "temp": 36.6},
            "AV-04": {"hr": 72.0, "hrv_rmssd": 45.0, "sbp": 122.0, "dbp": 80.0, "spo2": 97.8, "temp": 36.9},
        }

    def process_batch(self, batch: VitalBatch) -> EngineEvaluationResponse:
        crew_id = batch.crew_id
        if crew_id not in self.buffers:
            self.buffers[crew_id] = deque(maxlen=self.window_size)
        self.buffers[crew_id].append(batch)

        baseline = self.baselines.get(crew_id, self.baselines["AV-01"])

        # 1. Nettoyage & lissage
        df = preprocess_history(list(self.buffers[crew_id]))

        # 2. Extraction des features
        features = extract_features(df, baseline)

        # 3. Détection statistique & ML
        signals = self.detector.detect(features, baseline)

        # 4. Scoring par domaine & global
        domain_scores = compute_domain_scores(features, signals)
        global_score = compute_global_score(domain_scores)

        # 5. Moteur de règles cliniques & explicabilité
        status, rules, top_factors, protocol = self.rules_engine.evaluate(
            crew_id=crew_id,
            features=features,
            baseline=baseline,
            domain_scores=domain_scores,
            global_score=global_score,
        )

        return EngineEvaluationResponse(
            crew_id=crew_id,
            timestamp=batch.timestamp,
            status=status,
            global_score=global_score,
            domains=domain_scores,
            top_factors=top_factors,
            triggered_rules=rules,
            recommended_protocol=protocol,
        )