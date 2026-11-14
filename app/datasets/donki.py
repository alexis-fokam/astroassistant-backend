"""NASA DONKI (Space Weather Database Of Notifications, Knowledge, Information).

Fetches solar particle events (SEP) and coronal mass ejections (CME) through
api.nasa.gov and maps them to ``SpaceWeatherEvent`` rows (spec F5.3, scenario S3).
The flare endpoint (FLR) currently answers 404 on api.nasa.gov, so flare classes are
not fetched; SEP and CME are enough to replay historical radiation storms.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from app.datasets.http import get_json
from app.datasets.paths import DONKI_DIR, ensure_dir
from app.models.enums import SpaceWeatherKind

API_ROOT = "https://api.nasa.gov/DONKI"
ENDPOINTS: dict[str, SpaceWeatherKind] = {
    "SEP": SpaceWeatherKind.SOLAR_PARTICLE_EVENT,
    "CME": SpaceWeatherKind.CME,
}

# Reference windows replayed by the demo: the September 2017 storm (scenario S3,
# X9.3 flare and ground-level enhancement) and the May 2024 "Gannon" storm.
DEFAULT_WINDOWS: list[tuple[date, date]] = [
    (date(2017, 9, 1), date(2017, 9, 30)),
    (date(2024, 5, 1), date(2024, 5, 31)),
]


@dataclass(frozen=True)
class DonkiEvent:
    donki_id: str
    kind: SpaceWeatherKind
    started_at: datetime
    description: str | None


def endpoint_url(endpoint: str, start: date, end: date, api_key: str) -> str:
    query = urlencode(
        {"startDate": start.isoformat(), "endDate": end.isoformat(), "api_key": api_key}
    )
    return f"{API_ROOT}/{endpoint}?{query}"


def raw_path(endpoint: str, start: date, end: date) -> Path:
    return DONKI_DIR / f"{endpoint.lower()}_{start:%Y%m%d}_{end:%Y%m%d}.json"


def fetch(api_key: str, windows: list[tuple[date, date]] | None = None) -> list[Path]:
    """Download raw DONKI JSON for each endpoint and window; returns written files."""
    ensure_dir(DONKI_DIR)
    written = []
    for start, end in windows or DEFAULT_WINDOWS:
        for endpoint in ENDPOINTS:
            payload = get_json(endpoint_url(endpoint, start, end, api_key))
            path = raw_path(endpoint, start, end)
            path.write_text(
                json.dumps(payload or [], indent=2, ensure_ascii=False), encoding="utf-8"
            )
            written.append(path)
    return written


def parse_time(value: str) -> datetime:
    """DONKI times look like ``2017-09-10T16:45Z``."""
    return datetime.strptime(value, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)


def parse(endpoint: str, payload: list[dict[str, Any]]) -> list[DonkiEvent]:
    """Map one raw DONKI payload to events; unknown or incomplete entries are skipped."""
    kind = ENDPOINTS[endpoint]
    events = []
    for item in payload or []:
        if endpoint == "SEP":
            event_id, time_value = item.get("sepID"), item.get("eventTime")
            instruments = ", ".join(i["displayName"] for i in item.get("instruments") or [])
            description = f"Solar particle event detected by {instruments}" if instruments else None
        else:
            event_id, time_value = item.get("activityID"), item.get("startTime")
            description = (item.get("note") or "").strip() or None
        if not event_id or not time_value:
            continue
        events.append(DonkiEvent(event_id, kind, parse_time(time_value), description))
    return events


def load_cached() -> list[DonkiEvent]:
    """Parse every DONKI file already stored under ``data/nasa/donki``."""
    events: dict[str, DonkiEvent] = {}
    for path in sorted(DONKI_DIR.glob("*.json")):
        endpoint = path.name.split("_", 1)[0].upper()
        if endpoint not in ENDPOINTS:
            continue
        for event in parse(endpoint, json.loads(path.read_text(encoding="utf-8"))):
            events[event.donki_id] = event
    return sorted(events.values(), key=lambda e: e.started_at)
