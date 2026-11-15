"""Open dataset parsers (offline: no network access)."""

import csv
from datetime import date

import pytest

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


def test_edf_plus_hypnogram_annotations_are_parsed(tmp_path) -> None:
    from app.datasets.physionet import summarize_night

    # Minimal EDF+ annotation file: 256-byte header, then TALs (onset, duration, text).
    tals = (
        "+0\x14\x14\x00"
        "+0\x151800\x14Sleep stage W\x14\x00"
        "+1800\x1514400\x14Sleep stage 2\x14\x00"
        "+16200\x15600\x14Sleep stage W\x14\x00"
        "+16800\x157200\x14Sleep stage R\x14\x00"
        "+24000\x153600\x14Sleep stage W\x14\x00"
    )
    header = b"0".ljust(184) + b"256".ljust(8) + b" " * 64
    path = tmp_path / "SC4001EC-Hypnogram.edf"
    path.write_bytes(header + tals.encode("latin-1"))

    night = summarize_night(path)
    assert night.total_sleep_h == 6.0  # 4 h N2 + 2 h REM
    assert night.sleep_period_h == pytest.approx(6 + 10 / 60)
    assert night.awakenings == 1 and night.waso_min == 10


def test_rmssd_from_a_synthetic_ecg() -> None:
    import numpy as np

    from app.engine.calibration import ECG_HZ, rmssd, rr_intervals

    # 60 s of spikes alternating 800 ms / 850 ms R-R intervals → RMSSD = 50 ms.
    ecg = np.zeros(ECG_HZ * 60)
    t, toggle = 0.5, False
    while t < 59.5:
        ecg[int(t * ECG_HZ)] = 1.0
        t += 0.85 if toggle else 0.80
        toggle = not toggle
    rr = rr_intervals(ecg)
    assert len(rr) > 60
    assert rmssd(rr) == pytest.approx(50, abs=3)


def test_reference_datasets_are_imported(db) -> None:
    from sqlalchemy import func, select

    from app.datasets.importer import import_all
    from app.models import DatasetSource, ReferenceSleepNight, ReferenceVitalSample
    from app.models.enums import Metric

    counts = import_all(db)
    if counts["physionet-bidmc"]:
        spo2 = db.scalar(
            select(func.avg(ReferenceVitalSample.value)).where(
                ReferenceVitalSample.metric == Metric.SPO2
            )
        )
        assert 90 < spo2 < 100
        subjects = db.scalar(select(func.count(func.distinct(ReferenceVitalSample.subject))))
        assert subjects >= 53
    if counts["sleep-edfx"]:
        nights = db.scalars(select(ReferenceSleepNight)).all()
        assert len(nights) == counts["sleep-edfx"]
        assert all(0 < n.efficiency <= 1 and n.total_sleep_h <= n.sleep_period_h for n in nights)
    bidmc = db.scalars(select(DatasetSource).where(DatasetSource.code == "physionet-bidmc")).one()
    assert bidmc.bundled and bidmc.record_count == counts["physionet-bidmc"]


def test_wesad_windows_csv_is_imported_and_evaluated(db, tmp_path, monkeypatch) -> None:
    from sqlalchemy import select

    from app.datasets import physionet
    from app.datasets.importer import import_wesad_windows, seed_sources
    from app.engine import calibration
    from app.models import ReferenceVitalSample

    path = tmp_path / "wesad_hrv_windows.csv"
    rows = ["subject,condition,t_offset_s,rmssd_ms"]
    for subject in ("S2", "S3"):
        rows += [f"{subject},baseline,{i * 60},{50 + i % 3}" for i in range(10)]
        rows += [f"{subject},stress,{600 + i * 60},{30 + i % 2}" for i in range(6)]
        rows += [f"{subject},amusement,{1000 + i * 60},48" for i in range(4)]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(physionet, "WESAD_WINDOWS_CSV", path)

    source = seed_sources(db)["wesad"]
    assert import_wesad_windows(db, source) == 40
    assert {r.condition for r in db.scalars(select(ReferenceVitalSample))} == {
        "baseline",
        "stress",
        "amusement",
    }

    report = calibration.evaluate_wesad(windows_csv=path)
    rule_80 = next(r for r in report["hrv_rule"] if r["ratio"] == 0.8)
    assert report["subjects"] == 2
    assert rule_80["sensitivity"] == 1.0 and rule_80["false_alarm_rate"] == 0.0
