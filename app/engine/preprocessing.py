import pandas as pd
from app.schemas.simulateur import VitalBatch


def preprocess_history(history: list[VitalBatch]) -> pd.DataFrame:
    """Convertit l'historique récent en DataFrame nettoyé avec lissage léger."""
    df = pd.DataFrame([b.model_dump() for b in history])
    df = df.sort_values("timestamp").reset_index(drop=True)

    numeric_cols = ["hr", "hrv_rmssd", "sbp", "dbp", "spo2", "temp", "radiation_rate_msv_h"]
    for col in numeric_cols:
        # Interpolation des trous courts et lissage par moyenne mobile sur 3 points
        df[col] = df[col].interpolate(method="linear", limit=2)
        if len(df) >= 3:
            df[f"{col}_smooth"] = df[col].rolling(window=3, min_periods=1).mean()
        else:
            df[f"{col}_smooth"] = df[col]

    return df