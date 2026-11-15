from typing import Any, Dict
import numpy as np
import pandas as pd


def extract_features(df: pd.DataFrame, baseline: Dict[str, float]) -> Dict[str, Any]:
    """Calcule les indicateurs dérivés (ratios baseline, pentes de dérive, dette)."""
    latest = df.iloc[-1]

    # Ratio VFC par rapport à la baseline individuelle
    hrv_base = baseline.get("hrv_rmssd", 50.0)
    hrv_ratio_pct = (float(latest["hrv_rmssd_smooth"]) / hrv_base) * 100.0

    # Pente de dérive sur la fenêtre disponible (régression linéaire simple)
    hrv_slope = 0.0
    if len(df) >= 4:
        x = np.arange(len(df), dtype=float)
        y = df["hrv_rmssd_smooth"].to_numpy(dtype=float)
        coeffs = np.polyfit(x, y, deg=1)
        hrv_slope = float(coeffs[0])

    return {
        "hr": float(latest["hr_smooth"]),
        "hrv_rmssd": float(latest["hrv_rmssd_smooth"]),
        "hrv_ratio_pct": round(hrv_ratio_pct, 1),
        "hrv_slope": round(hrv_slope, 3),
        "sbp": float(latest["sbp_smooth"]),
        "spo2": float(latest["spo2_smooth"]),
        "temp": float(latest["temp_smooth"]),
        "radiation_rate_msv_h": float(latest["radiation_rate_msv_h"]),
        "radiation_cumul_pct": float(latest["radiation_cumul_pct"]),
        "sleep_hours": float(latest["sleep_hours"]),
        "sleep_debt_h": float(latest["sleep_debt_h"]),
        "exercise_adherence_pct": float(latest["exercise_adherence_pct"]),
        "stress_score": float(latest["stress_score"]),
        "blurred_vision": bool(latest["blurred_vision"]),
        "headache_intensity": int(latest["headache_intensity"]),
    }
