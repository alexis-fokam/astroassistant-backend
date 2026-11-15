"""Références individuelles glissantes (F2.1).

La référence de chaque mesure (moyenne, écart-type, médiane, MAD) est recalculée sur les
mesures propres du membre pendant ``baseline_days``, en s'arrêtant ``baseline_gap_days``
avant maintenant pour qu'une dérive en cours ne soit pas absorbée dans le « normal ».
Une référence est rafraîchie au plus une fois par jour.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
from sqlalchemy.orm import Session

from app.engine import stats
from app.engine.config import EngineConfig
from app.engine.features import MemberData, naive_utc
from app.models import Baseline

MIN_SAMPLES = 48  # au moins deux jours de mesures horaires
REFRESH_EVERY = timedelta(hours=24)


def refresh(db: Session, data: MemberData, at: datetime, cfg: EngineConfig) -> list[str]:
    """Mettre à jour les références périmées ; renvoie les noms des mesures rafraîchies."""
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
            baseline = Baseline(metric=metric)
            # Via la relation, pour que l'exécution suivante la voie (pas d'insertion en double).
            data.member.baselines.append(baseline)
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
