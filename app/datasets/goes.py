"""NOAA GOES integral proton flux (spec F5.4: early warning of solar radiation storms).

NOAA issues a solar radiation storm alert (S1) when the >= 10 MeV flux reaches 10 pfu;
the engine reuses that threshold. Only the last 7 days are served in real time, so the
file is a snapshot kept for offline demos.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.datasets.http import get_json
from app.datasets.paths import GOES_DIR, ensure_dir

URL = "https://services.swpc.noaa.gov/json/goes/primary/integral-protons-7-day.json"
S1_THRESHOLD_PFU = 10.0  # NOAA S-scale, >= 10 MeV protons


def fetch() -> Path:
    ensure_dir(GOES_DIR)
    payload = get_json(URL)
    path = GOES_DIR / f"integral_protons_{datetime.now(UTC):%Y%m%d}.json"
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return path


def peak_10mev(payload: list[dict]) -> float:
    """Highest >= 10 MeV flux in the snapshot (pfu)."""
    values = [
        row["flux"]
        for row in payload
        if row.get("energy") == ">=10 MeV" and row.get("flux") is not None
    ]
    return max(values, default=0.0)
