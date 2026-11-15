from typing import Dict, Any
import numpy as np


DOMAIN_WEIGHTS = {
    "cardio": 0.25,
    "radiation": 0.25,
    "musculo": 0.15,
    "behavioral": 0.20,
    "immune": 0.15,
}


def compute_domain_scores(features: Dict[str, Any], signals: Dict[str, float]) -> Dict[str, int]:
    # Cardio : FC, VFC, PA, SpO2 + composante multivariée
    cardio_raw = (
        0.35 * min(1.0, signals["z_hrv"] / 3.0)
        + 0.25 * min(1.0, signals["z_hr"] / 3.0)
        + 0.20 * min(1.0, signals["z_sbp"] / 2.5)
        + 0.20 * signals["iso_score"]
    )
    if features["spo2"] <= 90:
        cardio_raw = max(cardio_raw, 0.90)
    elif features["spo2"] <= 94:
        cardio_raw = max(cardio_raw, 0.55)

    # Radiation : débit de dose (SPE) + cumul carrière
    rad_rate_score = min(1.0, features["radiation_rate_msv_h"] / 5.0)
    rad_cumul_score = min(1.0, features["radiation_cumul_pct"] / 85.0)
    radiation_raw = max(rad_rate_score, rad_cumul_score)

    # Musculosquelettique : manque d'exercice + symptômes SANS (vision/céphalées)
    ex_deficit = max(0.0, (90.0 - features["exercise_adherence_pct"]) / 75.0)
    sans_flag = 0.65 if (features["blurred_vision"] and features["headache_intensity"] >= 5) else 0.0
    musculo_raw = max(ex_deficit, sans_flag)

    # Comportemental : dette de sommeil, VFC basse, score de stress
    sleep_penalty = min(1.0, features["sleep_debt_h"] / 6.0)
    stress_penalty = min(1.0, features["stress_score"] / 85.0)
    behavioral_raw = 0.45 * sleep_penalty + 0.35 * stress_penalty + 0.20 * min(1.0, signals["z_hrv"] / 2.5)

    # Immunitaire : température corporelle
    immune_raw = min(1.0, signals["z_temp"] / 3.0)
    if features["temp"] >= 38.5:
        immune_raw = max(immune_raw, 0.85)

    return {
        "cardio": int(np.clip(round(cardio_raw * 100), 0, 100)),
        "radiation": int(np.clip(round(radiation_raw * 100), 0, 100)),
        "musculo": int(np.clip(round(musculo_raw * 100), 0, 100)),
        "behavioral": int(np.clip(round(behavioral_raw * 100), 0, 100)),
        "immune": int(np.clip(round(immune_raw * 100), 0, 100)),
    }


def compute_global_score(domain_scores: Dict[str, int]) -> int:
    weighted = sum(domain_scores[d] * w for d, w in DOMAIN_WEIGHTS.items())
    # Influence du domaine le plus critique pour éviter la dilution
    peak_domain = max(domain_scores.values())
    combined = 0.55 * weighted + 0.45 * peak_domain
    return int(np.clip(round(combined), 0, 100))