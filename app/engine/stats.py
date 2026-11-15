"""Small robust statistics used by the engine (spec F2.1, F2.2)."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

MAD_TO_SIGMA = 1.4826  # MAD × 1.4826 ≈ standard deviation for normal data


def mean(values: Sequence[float]) -> float | None:
    return float(np.mean(values)) if len(values) else None


def median_mad(values: Sequence[float]) -> tuple[float, float] | None:
    if not len(values):
        return None
    arr = np.asarray(values, dtype=float)
    med = float(np.median(arr))
    return med, float(np.median(np.abs(arr - med)))


def robust_z(value: float | None, median: float | None, mad: float | None, floor: float) -> float | None:
    """(value - median) / (1.4826 · MAD); ``floor`` avoids dividing by a near-zero MAD."""
    if value is None or median is None:
        return None
    scale = max((mad or 0.0) * MAD_TO_SIGMA, floor)
    return (value - median) / scale


def slope_per_hour(hours: Sequence[float], values: Sequence[float]) -> float | None:
    """Least-squares slope (unit per hour)."""
    if len(values) < 3:
        return None
    x, y = np.asarray(hours, dtype=float), np.asarray(values, dtype=float)
    if np.ptp(x) == 0:
        return None
    return float(np.polyfit(x, y, 1)[0])
