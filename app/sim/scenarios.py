from typing import Dict, Any
from app.schemas.simulateur import ScenarioCode


def apply_scenario_modifiers(
    vitals: Dict[str, Any],
    scenario: ScenarioCode,
    elapsed_hours: float,
) -> Dict[str, Any]:
    """Altère les constantes nominales selon le scénario actif et le temps écoulé."""
    data = vitals.copy()

    if scenario == ScenarioCode.S1:
        # Journée nominale : aucune modification
        return data

    elif scenario == ScenarioCode.S2:
        # Stress & dette de sommeil : VFC en baisse progressive + sommeil < 6h
        decay = min(1.0, elapsed_hours / 48.0)
        data["hrv_rmssd"] = round(data["hrv_rmssd"] * (1.0 - 0.38 * decay), 1)
        data["hr"] = round(data["hr"] + 14.0 * decay, 1)
        data["sleep_hours"] = round(5.2 - 0.5 * decay, 1)
        data["sleep_debt_h"] = round(3.0 + 3.5 * decay, 1)
        data["stress_score"] = round(min(95.0, 45.0 + 35.0 * decay), 1)

    elif scenario == ScenarioCode.S3:
        # Événement à particules solaires (SPE) : pic brutal de débit de dose
        spike = min(1.0, elapsed_hours / 1.5)
        data["radiation_rate_msv_h"] = round(0.00025 + 18.5 * spike, 4)
        data["radiation_cumul_pct"] = round(15.0 + 42.0 * spike, 1)
        data["stress_score"] = round(min(90.0, data["stress_score"] + 30.0 * spike), 1)

    elif scenario == ScenarioCode.S4:
        # Suspicion SANS : vision floue déclarée + maux de tête répétés
        data["blurred_vision"] = True
        data["headache_intensity"] = 7
        data["sbp"] = round(data["sbp"] + 12.0, 1)

    elif scenario == ScenarioCode.S5:
        # Déconditionnement : séances d'exercice manquées
        drop = min(1.0, elapsed_hours / 72.0)
        data["exercise_adherence_pct"] = round(max(15.0, 80.0 - 65.0 * drop), 1)
        data["hr"] = round(data["hr"] + 8.0 * drop, 1)

    elif scenario == ScenarioCode.S6:
        # Fenêtre de contact sol : paramètres nominaux, flag géré par le runner
        pass

    return data