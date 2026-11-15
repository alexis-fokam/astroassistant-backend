"""Open dataset parsers (offline: no network access)."""

import csv
from datetime import date

from app.datasets import msl_rad
from app.datasets.msl_rad import CSV_HEADER, file_date, finalize, parse_lines

# Two observations in the RDR layout; the second one is flagged invalid (negative dose).
RDR_SAMPLE = """\
[OBSERVATION: 01]
START_OBS_UTC="2012-098 04:12:30"
[DOSIMETRY_TOTAL_DOSE_B: 02]
12.5
[DOSIMETRY_TOTAL_DOSE_E: 03]
16.0

[OBSERVATION: 01]
START_OBS_UTC="2012-098 04:21:00"
[DOSIMETRY_TOTAL_DOSE_B: 02]
-1.0
[DOSIMETRY_TOTAL_DOSE_E: 03]
15.0
"""


def test_file_date_reads_year_and_day_of_year() -> None:
    assert file_date("RAD_RDR_2012_098_04_12_C001_V01.TXT") == date(2012, 4, 7)


def test_parse_lines_keeps_valid_observations_only() -> None:
    samples = list(parse_lines(RDR_SAMPLE.splitlines()))
    assert len(samples) == 1
    sample = samples[0]
    assert sample.utc.isoformat() == "2012-04-07T04:12:30+00:00"
    assert (sample.dose_rate_b_ugy_h, sample.dose_rate_e_ugy_h) == (12.5, 16.0)
    assert sample.dose_equivalent_usv_h == 16.0 * 3.8


def test_finalize_sorts_and_deduplicates(tmp_path) -> None:
    path = tmp_path / "rad.csv"
    rows = [
        ["2012-01-02T00:15:16+00:00", "1", "2", "7.6"],
        ["2012-01-02T00:11:55+00:00", "1", "2", "7.6"],
        ["2012-01-02T00:15:16+00:00", "1", "2", "7.6"],
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerows(rows)

    assert finalize(path) == 2
    loaded = msl_rad.load(path)
    assert [s.utc.minute for s in loaded] == [11, 15]


def test_bundled_cruise_csv_is_clean() -> None:
    if not msl_rad.MSL_RAD_CSV.exists():
        return
    samples = msl_rad.load()
    times = [s.utc for s in samples]
    assert times == sorted(times)
    assert len(times) == len(set(times))
    assert times[0].date() < date(2012, 1, 1) < times[-1].date()


def test_donki_events_are_imported_with_provenance(db) -> None:
    from sqlalchemy import select

    from app.datasets import donki
    from app.datasets.importer import import_space_weather, seed_sources
    from app.models import SpaceWeatherEvent
    from app.models.enums import SpaceWeatherKind

    cached = donki.load_cached()
    source = seed_sources(db)["nasa-donki"]
    count = import_space_weather(db, source)
    events = db.scalars(select(SpaceWeatherEvent)).all()
    assert len(events) == count
    flares = [e for e in events if e.kind is SpaceWeatherKind.SOLAR_FLARE]
    assert {f.flare_class for f in flares} >= {"X8.2", "X5.8"}
    if cached:
        assert source.record_count == len(cached)
        from_donki = [e for e in events if e.source_id == source.id]
        assert len({e.donki_id for e in from_donki}) == len(cached)


def test_donki_windows_are_split_by_month() -> None:
    from app.datasets.donki import monthly

    chunks = monthly(date(2011, 12, 15), date(2012, 2, 10))
    assert chunks == [
        (date(2011, 12, 15), date(2011, 12, 31)),
        (date(2012, 1, 1), date(2012, 1, 31)),
        (date(2012, 2, 1), date(2012, 2, 10)),
    ]
