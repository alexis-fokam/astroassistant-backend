"""Multivariate anomaly detection with an Isolation Forest per crew member (spec F2.3).

Each model is trained on the member's own hourly vectors from the baseline window
(the most recent days are excluded, so an ongoing drift does not become "normal").
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from app.core.config import get_settings
from app.engine.config import EngineConfig
from app.engine.features import MemberData, naive_utc
from app.models.enums import Metric

_CACHE: dict[tuple[int, str, int], IsolationForest] = {}


def hourly_matrix(
    data: MemberData, metrics: list[Metric], start: datetime, end: datetime
) -> np.ndarray:
    """One row per hour with a reading of every metric (hour means)."""
    buckets: dict[datetime, dict[Metric, list[float]]] = {}
    for metric in metrics:
        series = data.series.get(metric)
        if series is None:
            return np.empty((0, len(metrics)))
        for t, v in zip(series.times, series.values, strict=True):
            if start <= t < end:
                hour = t.replace(minute=0, second=0, microsecond=0)
                buckets.setdefault(hour, {}).setdefault(metric, []).append(v)
    rows = [
        [float(np.mean(values[m])) for m in metrics]
        for _, values in sorted(buckets.items())
        if all(m in values for m in metrics)
    ]
    return np.asarray(rows, dtype=float).reshape(-1, len(metrics))


def _model(data: MemberData, at: datetime, cfg: EngineConfig) -> IsolationForest | None:
    metrics = [Metric(m) for m in cfg.anomaly["metrics"]]
    end = at - timedelta(days=cfg.windows["baseline_gap_days"])
    start = end - timedelta(days=cfg.windows["baseline_days"])
    key = (data.member.id, end.strftime("%Y-%m-%d"), len(metrics))
    if key in _CACHE:
        return _CACHE[key]
    path = model_path(data.member.code, end)
    if path.exists():
        _CACHE[key] = joblib.load(path)
        return _CACHE[key]
    matrix = hourly_matrix(data, metrics, start, end)
    if len(matrix) < cfg.anomaly["min_training_hours"]:
        return None
    model = IsolationForest(
        n_estimators=100,
        contamination=cfg.anomaly["contamination"],
        random_state=cfg.anomaly["random_state"],
    ).fit(matrix)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    _CACHE[key] = model
    return model


def model_path(code: str, end: datetime) -> Path:
    """One model per member and training window (spec §8: models persisted with joblib)."""
    return Path(get_settings().models_dir) / f"isolation_forest_{code}_{end:%Y%m%d}.joblib"


def score(
    data: MemberData, features: dict[str, float | None], at: datetime, cfg: EngineConfig
) -> float | None:
    """Anomaly score in [0, 1]: ≈ 0.5 at the decision boundary, → 1 for strong anomalies."""
    at = naive_utc(at)
    vector = [features.get(f"{m}_1h") for m in cfg.anomaly["metrics"]]
    if any(v is None for v in vector):
        return None
    model = _model(data, at, cfg)
    if model is None:
        return None
    decision = float(model.decision_function(np.asarray([vector], dtype=float))[0])
    return round(1 / (1 + math.exp(12 * decision)), 4)


def clear_cache() -> None:
    _CACHE.clear()
