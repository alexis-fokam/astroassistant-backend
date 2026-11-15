"""Calibration and evaluation of the risk engine on real physiological data.

    python -m app.engine.calibration bidmc      # SpO2 / heart-rate / respiration ranges
    python -m app.engine.calibration sleep      # healthy sleep (Sleep-EDF hypnograms)
    python -m app.engine.calibration wesad      # HRV-01 sensitivity / false-alarm rate
    python -m app.engine.calibration wesad-extract  # raw WESAD → HRV windows CSV (data/physionet)

Results are written to ``docs/calibration.json`` and summarized in
``docs/fiche-moteur-ia.md``. Data come from ``data/external/`` (see
``app/datasets/physionet.py``); WESAD must be downloaded by hand.

WESAD protocol (Schmidt et al., ICMI 2018): 15 subjects, chest ECG at 700 Hz, labels
1 = baseline, 2 = stress (Trier Social Stress Test), 3 = amusement. For each subject we
compute RMSSD on 60 s windows, take the median RMSSD of the baseline period as the
individual baseline, and apply the engine's HRV rule ``RMSSD < ratio × baseline``.
Sensitivity = stress windows flagged; false-alarm rate = baseline + amusement windows flagged.
"""

from __future__ import annotations

import argparse
import csv
import json
import pickle
from pathlib import Path
from statistics import median

import numpy as np

from app.core.config import BASE_DIR
from app.datasets import physionet

OUTPUT = BASE_DIR / "docs" / "calibration.json"
ECG_HZ = 700
WINDOW_S = 60


def _percentiles(values: list[float]) -> dict[str, float]:
    arr = np.asarray(values, dtype=float)
    return {f"p{p}": round(float(np.percentile(arr, p)), 2) for p in (1, 5, 25, 50, 75, 95, 99)}


# --------------------------------------------------------------------- BIDMC
def calibrate_bidmc() -> dict:
    files = sorted(physionet.BIDMC_DIR.glob("bidmc_*_Numerics.csv"))
    if not files:
        raise SystemExit("BIDMC absent : python -m app.datasets fetch bidmc")
    pooled: dict[str, list[float]] = {}
    for path in files:
        for key, values in physionet.read_bidmc(path).items():
            pooled.setdefault(key, []).extend(values)
    spo2 = np.asarray(pooled.get("SpO2", []))
    return {
        "dataset": "BIDMC (PhysioNet), 53 patients de soins intensifs, 1 Hz",
        "records": len(files),
        "seconds": int(len(spo2)),
        "heart_rate": _percentiles(pooled.get("HR", [])),
        "respiratory_rate": _percentiles(pooled.get("RESP", [])),
        "spo2": _percentiles(pooled.get("SpO2", [])),
        "spo2_below_94_pct": round(float((spo2 < 94).mean() * 100), 2),
        "spo2_below_90_pct": round(float((spo2 <= 90).mean() * 100), 2),
        **_bidmc_rule_rates(files),
    }


def _bidmc_rule_rates(files: list[Path]) -> dict:
    """Share of seconds, and of patients, where the engine's critical cardio rules hold."""
    seconds = cardio = spo2_crit = 0
    patients_cardio = patients_spo2 = 0
    for path in files:
        hr, spo2 = [], []
        with path.open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row = {k.strip(): (v or "").strip() for k, v in row.items()}
                if row.get("HR") and row.get("SpO2"):
                    hr.append(float(row["HR"]))
                    spo2.append(float(row["SpO2"]))
        hr_arr, spo2_arr = np.asarray(hr), np.asarray(spo2)
        hit_cardio = (hr_arr > 120) & (spo2_arr < 94)
        hit_spo2 = spo2_arr <= 90
        seconds += len(hr_arr)
        cardio += int(hit_cardio.sum())
        spo2_crit += int(hit_spo2.sum())
        patients_cardio += bool(hit_cardio.any())
        patients_spo2 += bool(hit_spo2.any())
    return {
        "cardio_crit_01_seconds_pct": round(100 * cardio / seconds, 2),
        "cardio_crit_01_patients": patients_cardio,
        "spo2_crit_01_seconds_pct": round(100 * spo2_crit / seconds, 2),
        "spo2_crit_01_patients": patients_spo2,
    }


# --------------------------------------------------------------------- Sleep-EDF
def calibrate_sleep() -> dict:
    files = sorted(physionet.SLEEP_EDF_DIR.glob("SC4*-Hypnogram.edf"))
    if not files:
        raise SystemExit("Sleep-EDF absent : python -m app.datasets fetch sleep-edf")
    nights = [n for n in (physionet.summarize_night(f) for f in files) if n is not None]
    tst = [n.total_sleep_h for n in nights]
    return {
        "dataset": "Sleep-EDF Expanded, étude « sleep cassette » (adultes sains de 25 à 101 ans)",
        "nights": len(nights),
        "total_sleep_h": _percentiles(tst),
        "efficiency": _percentiles([n.efficiency for n in nights]),
        "waso_min": _percentiles([n.waso_min for n in nights]),
        "awakenings": _percentiles([n.awakenings for n in nights]),
        "nights_below_6h_pct": round(100 * sum(h < 6 for h in tst) / len(tst), 1),
    }


# --------------------------------------------------------------------- WESAD
def rr_intervals(ecg: np.ndarray, fs: int = ECG_HZ) -> np.ndarray:
    """R-peak detection: band-pass filter, then peaks at least 0.33 s apart (≤ 180 bpm)."""
    from scipy.signal import butter, filtfilt, find_peaks

    b, a = butter(3, [5 / (fs / 2), 15 / (fs / 2)], btype="band")
    filtered = filtfilt(b, a, ecg)
    energy = filtered**2
    peaks, _ = find_peaks(energy, distance=int(0.33 * fs), height=np.percentile(energy, 90))
    rr = np.diff(peaks) / fs * 1000
    return rr[(rr > 333) & (rr < 1500)]  # 40-180 bpm


def rmssd(rr: np.ndarray) -> float | None:
    if len(rr) < 20:
        return None
    diff = np.diff(rr)
    diff = diff[np.abs(diff) < 200]  # ectopic beats / missed peaks
    return float(np.sqrt(np.mean(diff**2))) if len(diff) >= 10 else None


CONDITIONS = {1: "baseline", 2: "stress", 3: "amusement"}


def subject_windows(path: Path) -> list[tuple[int, float, float]]:
    """(label, start s, RMSSD) for each 60 s window with a single label among 1, 2, 3."""
    with path.open("rb") as handle:
        data = pickle.load(handle, encoding="latin1")
    ecg = np.asarray(data["signal"]["chest"]["ECG"]).ravel()
    labels = np.asarray(data["label"]).ravel()
    step = ECG_HZ * WINDOW_S
    windows = []
    for start in range(0, len(ecg) - step, step):
        window_labels = labels[start : start + step]
        label = int(window_labels[0])
        if label not in CONDITIONS or not (window_labels == label).all():
            continue
        value = rmssd(rr_intervals(ecg[start : start + step]))
        if value is not None:
            windows.append((label, start / ECG_HZ, value))
    return windows


def extract_wesad_windows(output: Path = physionet.WESAD_WINDOWS_CSV) -> Path:
    """Raw WESAD (2.5 GB) → small CSV of RMSSD per 60 s window (a few hundred kB).

    Run it wherever the raw data is (e.g. Google Colab, see notebooks/), then copy the
    CSV into data/physionet/: the seed imports it and the evaluation reads it.
    """
    files = sorted(physionet.WESAD_DIR.glob("S*/S*.pkl"))
    if not files:
        raise SystemExit(
            "WESAD absent : téléchargez-le depuis "
            "https://www.eti.uni-siegen.de/ubicomp/home/datasets/icmi18/ "
            "puis décompressez-le dans data/external/wesad/ (ou utilisez le notebook Colab)"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["subject", "condition", "t_offset_s", "rmssd_ms"])
        for path in files:
            for label, t, value in subject_windows(path):
                writer.writerow([path.stem, CONDITIONS[label], t, round(value, 3)])
            print(f"  {path.stem}: ok")
    return output


def load_wesad_windows(
    path: Path = physionet.WESAD_WINDOWS_CSV,
) -> dict[str, list[tuple[str, float]]]:
    """subject → [(condition, RMSSD)] from the extracted CSV."""
    subjects: dict[str, list[tuple[str, float]]] = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            subjects.setdefault(row["subject"], []).append(
                (row["condition"], float(row["rmssd_ms"]))
            )
    return subjects


def evaluate_wesad(
    ratios: tuple[float, ...] = (0.6, 0.7, 0.8, 0.9), windows_csv: Path | None = None
) -> dict:
    windows_csv = windows_csv or physionet.WESAD_WINDOWS_CSV
    if not windows_csv.exists():
        extract_wesad_windows(windows_csv)
    subjects = {}
    for subject, windows in load_wesad_windows(windows_csv).items():
        base = [v for condition, v in windows if condition == "baseline"]
        if len(base) >= 5:
            subjects[subject] = (median(base), windows)
    results = []
    for ratio in ratios:
        tp = fn = fp = tn = 0
        for baseline, windows in subjects.values():
            for condition, value in windows:
                flagged = value < ratio * baseline
                if condition == "stress":
                    tp, fn = tp + flagged, fn + (not flagged)
                else:
                    fp, tn = fp + flagged, tn + (not flagged)
        results.append(
            {
                "ratio": ratio,
                "sensitivity": round(tp / (tp + fn), 3) if tp + fn else None,
                "false_alarm_rate": round(fp / (fp + tn), 3) if fp + tn else None,
                "stress_windows": tp + fn,
                "non_stress_windows": fp + tn,
            }
        )
    stress_ratio = [
        median([v for condition, v in w if condition == "stress"]) / b
        for b, w in subjects.values()
        if any(condition == "stress" for condition, _ in w)
    ]
    return {
        "dataset": "WESAD (Univ. Siegen), ECG thoracique 700 Hz, fenêtres de 60 s",
        "subjects": len(subjects),
        "median_rmssd_stress_over_baseline": round(median(stress_ratio), 3)
        if stress_ratio
        else None,
        "hrv_rule": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.engine.calibration", description=__doc__.splitlines()[0]
    )
    parser.add_argument("target", choices=["bidmc", "sleep", "wesad", "wesad-extract", "all"])
    args = parser.parse_args()
    report = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    if args.target == "wesad-extract":
        print(f"→ {extract_wesad_windows()}")
        return
    targets = ["bidmc", "sleep", "wesad"] if args.target == "all" else [args.target]
    jobs = {"bidmc": calibrate_bidmc, "sleep": calibrate_sleep, "wesad": evaluate_wesad}
    for target in targets:
        try:
            report[target] = jobs[target]()
            print(f"{target}: ok")
        except SystemExit as missing:
            print(f"{target}: {missing}")
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"→ {OUTPUT}")


if __name__ == "__main__":
    main()
