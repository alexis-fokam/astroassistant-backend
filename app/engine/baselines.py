"""Rolling individual baselines (spec F2.1).

Each metric's baseline (mean, std, median, MAD) is recomputed from the member's own clean
readings over ``baseline_days``, ending ``baseline_gap_days`` before now so that an ongoing
drift is not absorbed into "normal". A baseline is refreshed at most once a day.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
from sqlalchemy.orm import Session

from app.engine import stats
from app.engine.config import EngineConfig
from app.engine.features import MemberData, naive_utc
from app.models import Baseline

MIN_SAMPLES = 48  # at least two days of hourly readings
REFRESH_EVERY = timedelta(hours=24)


def refresh(db: Session, data: MemberData, at: datetime, cfg: EngineConfig) -> list[str]:
    """Update stale baselines in place; returns the refreshed metric names."""
    at = naive_utc(at)
    end = at - timedelta(days=cfg.windows["baseline_gap_days"])
    start = end - timedelta(days=cfg.windows["baseline_days"])
    refreshed = []
    for metric, series in data.series.items():
        baseline = data.baselines.get(metric)
        if baseline is not None and at - naive_utc(baseline.computed_at) < REFRESH_EVERY:
            continue
        values = series.window(start, end)
        if len(values) < MIN_SAMPLES:
            continue
        median, mad = stats.median_mad(values)
        if baseline is None:
            baseline = Baseline(crew_member_id=data.member.id, metric=metric)
            db.add(baseline)
            data.baselines[metric] = baseline
        baseline.mean = round(float(np.mean(values)), 3)
        baseline.std = round(float(np.std(values, ddof=1)), 3)
        baseline.median = round(median, 3)
        baseline.mad = round(mad, 3)
        baseline.sample_count = len(values)
        baseline.window_days = cfg.windows["baseline_days"]
        baseline.computed_at = at
        refreshed.append(metric.value)
    return refreshed
