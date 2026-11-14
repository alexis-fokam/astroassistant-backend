"""Load the bundled open datasets into the database (tables ``dataset_sources``,
``cruise_dose_samples``, ``proton_flux_readings``, ``space_weather_events``).

Every imported row points to its ``dataset_sources`` entry, so the provenance of any
value shown in the app can be traced back to the agency that published it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.datasets import donki, msl_rad
from app.datasets.catalog import CATALOG
from app.datasets.paths import DONKI_DIR, GOES_DIR, MSL_RAD_CSV
from app.models import CruiseDoseSample, DatasetSource, ProtonFluxReading, SpaceWeatherEvent
from app.models.enums import SpaceWeatherKind

# GOES bands kept in the database: the S-scale threshold band and the hard-spectrum band.
GOES_BANDS = (">=10 MeV", ">=100 MeV")

# Reference events from NOAA/SWPC event reports, used when no DONKI cache is available
# (the DEMO_KEY quota is easily exhausted). They drive scenario S3.
REFERENCE_EVENTS = [
    {
        "kind": SpaceWeatherKind.SOLAR_FLARE,
        "flare_class": "X8.2",
        "started_at": datetime(2017, 9, 10, 15, 35, tzinfo=UTC),
        "peak_at": datetime(2017, 9, 10, 16, 6, tzinfo=UTC),
        "ended_at": datetime(2017, 9, 10, 16, 31, tzinfo=UTC),
        "description": "Éruption X8.2 (région 12673), à l'origine de "
        "l'événement à protons du 10 septembre 2017.",
    },
    {
        "kind": SpaceWeatherKind.SOLAR_PARTICLE_EVENT,
        "flare_class": None,
        "started_at": datetime(2017, 9, 10, 16, 45, tzinfo=UTC),
        "peak_at": datetime(2017, 9, 11, 11, 45, tzinfo=UTC),
        "ended_at": datetime(2017, 9, 13, 0, 0, tzinfo=UTC),
        "peak_proton_flux_pfu": 1490.0,
        "description": "Tempête de radiation S3 : flux ≥ 10 MeV "
        "jusqu'à ~1 490 pfu (GOES-13). Rejouée par S3.",
    },
    {
        "kind": SpaceWeatherKind.SOLAR_FLARE,
        "flare_class": "X5.8",
        "started_at": datetime(2024, 5, 11, 1, 10, tzinfo=UTC),
        "peak_at": datetime(2024, 5, 11, 1, 23, tzinfo=UTC),
        "ended_at": datetime(2024, 5, 11, 1, 39, tzinfo=UTC),
        "description": "Éruption X5.8 (région 13664) pendant la tempête géomagnétique de mai 2024.",
    },
]


def _mtime(path: Path) -> datetime | None:
    return datetime.fromtimestamp(path.stat().st_mtime, UTC) if path.exists() else None


def seed_sources(session: Session) -> dict[str, DatasetSource]:
    sources = {}
    for info in CATALOG:
        source = DatasetSource(
            code=info.code,
            name=info.name,
            agency=info.agency,
            url=info.url,
            licence=info.licence,
            usage=info.usage,
            bundled=info.bundled,
        )
        session.add(source)
        sources[info.code] = source
    session.flush()
    return sources


def import_msl_rad(session: Session, source: DatasetSource, path: Path = MSL_RAD_CSV) -> int:
    if not path.exists():
        return 0
    rows = [
        {
            "source_id": source.id,
            "measured_at": s.utc,
            "dose_rate_b_ugy_h": s.dose_rate_b_ugy_h,
            "dose_rate_e_ugy_h": s.dose_rate_e_ugy_h,
            "dose_equivalent_usv_h": round(s.dose_equivalent_usv_h, 4),
        }
        for s in msl_rad.load(path)
    ]
    if rows:
        session.execute(CruiseDoseSample.__table__.insert(), rows)
    source.record_count, source.retrieved_at = len(rows), _mtime(path)
    return len(rows)


def latest_goes_file() -> Path | None:
    files = sorted(GOES_DIR.glob("integral_protons_*.json"))
    return files[-1] if files else None


def import_goes(session: Session, source: DatasetSource, path: Path | None = None) -> int:
    path = path or latest_goes_file()
    if path is None:
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = [
        {
            "source_id": source.id,
            "measured_at": datetime.fromisoformat(r["time_tag"].replace("Z", "+00:00")),
            "satellite": r["satellite"],
            "energy_band": r["energy"],
            "flux_pfu": max(r["flux"], 0.0),
        }
        for r in payload
        if r.get("energy") in GOES_BANDS and r.get("flux") is not None
    ]
    if rows:
        session.execute(ProtonFluxReading.__table__.insert(), rows)
    source.record_count, source.retrieved_at = len(rows), _mtime(path)
    return len(rows)


def import_space_weather(session: Session, source: DatasetSource) -> int:
    """DONKI events (SEP, CME) when cached, plus the reference flares.

    The DONKI flare route (FLR) is not served by api.nasa.gov, so flares always come from
    the NOAA reference list; without a DONKI cache the reference SEP is used as well.
    """
    events = donki.load_cached()
    for e in events:
        session.add(
            SpaceWeatherEvent(
                source=source,
                kind=e.kind,
                donki_id=e.donki_id,
                started_at=e.started_at,
                description=e.description,
            )
        )
    references = [
        spec
        for spec in REFERENCE_EVENTS
        if not events or spec["kind"] is SpaceWeatherKind.SOLAR_FLARE
    ]
    for spec in references:
        session.add(SpaceWeatherEvent(**spec))
    if events:
        files = sorted(DONKI_DIR.glob("*.json"))
        source.record_count = len(events)
        source.retrieved_at = max((_mtime(f) for f in files), default=None)
    return len(events) + len(references)


def import_all(session: Session) -> dict[str, int]:
    """Create the provenance entries and import every bundled dataset available locally."""
    sources = seed_sources(session)
    counts = {
        "nasa-msl-rad": import_msl_rad(session, sources["nasa-msl-rad"]),
        "noaa-goes-protons": import_goes(session, sources["noaa-goes-protons"]),
        "nasa-donki": import_space_weather(session, sources["nasa-donki"]),
    }
    session.flush()
    return counts
