from typing import Dict, Any, List, Tuple
from app.schemas.simulateur import AlertLevel, FactorExplanation


class ClinicalRulesEngine:
    def __init__(self):
        # Mémoire des alertes WARNING en attente de confirmation (2 mesures consécutives)
        self._pending_warnings: Dict[str, int] = {}

    def evaluate(
        self,
        crew_id: str,
        features: Dict[str, Any],
        baseline: Dict[str, float],
        domain_scores: Dict[str, int],
        global_score: int,
    ) -> Tuple[AlertLevel, List[str], List[FactorExplanation], str | None]:
        triggered_rules: List[str] = []
        factors: List[FactorExplanation] = []
        critical_override = False
        warning_candidate = False
        protocol: str | None = None

        # --- Règle 1 : Événement radiatif aigu (SPE - Scénario S3) ---
        if features["radiation_rate_msv_h"] >= 1.0 or features["radiation_cumul_pct"] > 80.0:
            triggered_rules.append("RULE-RAD-SPE-CRITICAL")
            critical_override = True
            protocol = "PRT-RAD-SHELTER-01"
            factors.append(FactorExplanation(
                feature="radiation_rate_msv_h",
                value=features["radiation_rate_msv_h"],
                baseline=0.00025,
                contribution=0.85,
            ))

        # --- Règle 2 : Suspicion SANS (Scénario S4) ---
        if features["blurred_vision"] and features["headache_intensity"] >= 5:
            triggered_rules.append("RULE-SANS-OCULAR-WARN")
            warning_candidate = True
            protocol = protocol or "PRT-SANS-VISION-01"
            factors.append(FactorExplanation(
                feature="blurred_vision + headache",
                value=f"Vision floue / Céphalée {features['headache_intensity']}/10",
                contribution=0.68,
            ))

        # --- Règle 3 : Stress & Dette de sommeil (Scénario S2) ---
        if features["hrv_ratio_pct"] < 80.0 or features["sleep_debt_h"] > 4.0:
            triggered_rules.append("RULE-BEHAV-HRV-SLEEP")
            warning_candidate = True
            protocol = protocol or "PRT-STRESS-BREATH-01"
            factors.append(FactorExplanation(
                feature="hrv_rmssd",
                value=features["hrv_rmssd"],
                baseline=baseline.get("hrv_rmssd", 50.0),
                contribution=0.45,
            ))
            factors.append(FactorExplanation(
                feature="sleep_debt_h",
                value=features["sleep_debt_h"],
                baseline=0.0,
                contribution=0.35,
            ))

        # --- Règle 4 : Déconditionnement musculosquelettique (Scénario S5) ---
        if features["exercise_adherence_pct"] < 60.0:
            triggered_rules.append("RULE-MUSC-EXERCISE-DROP")
            warning_candidate = True
            protocol = protocol or "PRT-MUSC-RECOVERY-01"
            factors.append(FactorExplanation(
                feature="exercise_adherence_pct",
                value=features["exercise_adherence_pct"],
                baseline=95.0,
                contribution=0.55,
            ))

        # --- Règle 5 : Seuils vitaux critiques (Section 6.2) ---
        if features["hr"] > 120 or features["hr"] < 40 or features["spo2"] <= 90 or features["temp"] >= 38.5:
            triggered_rules.append("RULE-VITALS-CRITICAL")
            critical_override = True
            protocol = protocol or "PRT-EMERGENCY-VITALS-01"

        # --- Détermination du statut avec confirmation sur 2 mesures pour WARNING ---
        if critical_override or global_score >= 70:
            status = AlertLevel.CRITICAL
            self._pending_warnings[crew_id] = 0
        elif warning_candidate or global_score >= 40:
            count = self._pending_warnings.get(crew_id, 0) + 1
            self._pending_warnings[crew_id] = count
            if count >= 2:
                status = AlertLevel.WARNING
            else:
                status = AlertLevel.NOMINAL
                protocol = None
        else:
            status = AlertLevel.NOMINAL
            self._pending_warnings[crew_id] = 0
            protocol = None

        # Tri des facteurs explicatifs par contribution décroissante (max 3)
        factors.sort(key=lambda f: f.contribution, reverse=True)
        return status, triggered_rules, factors[:3], protocol