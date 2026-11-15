"""Flux intégral de protons NOAA GOES (F5.4 : alerte précoce de tempête radiative).

La NOAA émet une alerte de tempête radiative (S1) quand le flux >= 10 MeV atteint 10 pfu ;
le moteur reprend ce seuil. Seuls les 7 derniers jours sont servis en temps réel : le
fichier est un instantané conservé pour les démos hors ligne.
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
    """Flux >= 10 MeV le plus élevé de l'instantané (pfu)."""
    values = [
        row["flux"]
        for row in payload
        if row.get("energy") == ">=10 MeV" and row.get("flux") is not None
    ]
    return max(values, default=0.0)
