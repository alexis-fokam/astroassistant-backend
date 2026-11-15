"""Open physiological datasets used to calibrate the risk engine (spec §6, §12).

* BIDMC (PhysioNet, ODC-By): 53 recordings of ~8 min with heart rate, respiratory rate and
  SpO2 at 1 Hz (``*_Numerics.csv``, a few kB each) → plausible ranges, SpO2 thresholds.
* Sleep-EDF Expanded (PhysioNet, ODC-By), "sleep cassette" study of healthy adults:
  expert hypnograms only (``*-Hypnogram.edf``, ~5 kB each) → sleep duration, efficiency,
  latency and awakenings of healthy sleepers.
* WESAD (Univ. Siegen, non-commercial research): must be downloaded by hand after reading
  its terms; see ``app/engine/calibration.py`` for the stress evaluation.

Files go to ``data/external/`` (git-ignored); nothing here is needed to run the app.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from app.datasets.http import get_text
from app.datasets.paths import EXTERNAL_DIR, ensure_dir

BIDMC_ROOT = "https://physionet.org/files/bidmc/1.0.0/bidmc_csv/"
BIDMC_DIR = EXTERNAL_DIR / "bidmc"
SLEEP_EDF_ROOT = "https://physionet.org/files/sleep-edfx/1.0.0/sleep-cassette/"
SLEEP_EDF_DIR = EXTERNAL_DIR / "sleep-edfx"
WESAD_DIR = EXTERNAL_DIR / "wesad"

_HYPNOGRAM_RE = re.compile(r'href="(SC4\d{3}E[0-9A-Z]-Hypnogram\.edf)"')
# Rechtschaffen & Kales stages as written in the EDF+ annotations.
SLEEP_STAGES = {"W": "wake", "1": "n1", "2": "n2", "3": "n3", "4": "n3", "R": "rem"}


def _download(url: str, path: Path, retries: int = 4) -> Path:
    """Download one small file, retrying slow or dropped connections."""
    import time
    import urllib.request

    from app.datasets.http import USER_AGENT

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = response.read()
            path.write_bytes(payload)
            return path
        except OSError:
            if attempt == retries - 1:
                raise
            time.sleep(5 * 2**attempt)
    return path


def fetch_bidmc(records: range = range(1, 54)) -> list[Path]:
    ensure_dir(BIDMC_DIR)
    paths = []
    for i in records:
        name = f"bidmc_{i:02d}_Numerics.csv"
        path = BIDMC_DIR / name
        if not path.exists():
            _download(BIDMC_ROOT + name, path)
        paths.append(path)
    return paths


def fetch_sleep_edf_hypnograms(limit: int | None = None) -> list[Path]:
    ensure_dir(SLEEP_EDF_DIR)
    names = sorted(set(_HYPNOGRAM_RE.findall(get_text(SLEEP_EDF_ROOT))))[:limit]
    paths = []
    for name in names:
        path = SLEEP_EDF_DIR / name
        if not path.exists():
            _download(SLEEP_EDF_ROOT + name, path)
        paths.append(path)
    return paths


# --------------------------------------------------------------------- readers
def read_bidmc(path: Path) -> dict[str, list[float]]:
    """Columns HR, PULSE, RESP, SpO2 of one Numerics file (blank cells skipped)."""
    columns: dict[str, list[float]] = {}
    with path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            for key, value in row.items():
                key = key.strip()
                value = (value or "").strip()
                if key == "Time [s]" or not value or value.lower() == "nan":
                    continue
                columns.setdefault(key, []).append(float(value))
    return columns


@dataclass(frozen=True)
class SleepNight:
    """Metrics over the main sleep episode (30 s epochs, daytime naps excluded).

    Lights-off times are not in the hypnograms, so sleep latency is not computed.
    """

    record: str
    sleep_period_h: float  # sleep onset → final awakening
    total_sleep_h: float
    efficiency: float  # total sleep / sleep period
    waso_min: float  # wake after sleep onset
    awakenings: int  # wake bouts after sleep onset
    stages_h: dict[str, float]


def read_hypnogram_annotations(path: Path) -> list[tuple[float, float, str]]:
    """(onset s, duration s, stage) from an EDF+ annotation file, without extra libraries.

    EDF+ stores annotations as TALs: ``+onset\\x15duration\\x14text\\x14\\x00``.
    """
    raw = path.read_bytes()
    header_bytes = int(raw[184:192].decode("ascii").strip())
    payload = raw[header_bytes:].decode("latin-1")
    events = []
    for onset, duration, text in re.findall(r"\+([\d.]+)\x15([\d.]+)\x14([^\x14]+)\x14", payload):
        match = re.match(r"Sleep stage (\w)", text)
        if match:
            events.append((float(onset), float(duration), match.group(1)))
    return events


SLEEP = ("n1", "n2", "n3", "rem")
# Wake longer than this ends a sleep episode (recordings last ~20 h and include naps).
EPISODE_BREAK_EPOCHS = 120  # 60 min of 30 s epochs


def main_sleep_episode(epochs: list[str]) -> list[str]:
    """Longest sleep episode: sleep epochs joined by wake/unscored gaps under 60 min."""
    episodes: list[tuple[int, int]] = []
    start = last = None
    for i, stage in enumerate(epochs):
        if stage not in SLEEP:
            continue
        if start is None:
            start = last = i
        elif i - last > EPISODE_BREAK_EPOCHS:
            episodes.append((start, last))
            start = i
        last = i
    if start is not None:
        episodes.append((start, last))
    if not episodes:
        return []
    first, end = max(episodes, key=lambda e: sum(s in SLEEP for s in epochs[e[0] : e[1] + 1]))
    return epochs[first : end + 1]


def summarize_night(path: Path) -> SleepNight | None:
    events = read_hypnogram_annotations(path)
    epochs: list[str] = []
    for _, duration, stage in events:
        epochs.extend([SLEEP_STAGES.get(stage, "unscored")] * int(duration // 30))
    period = main_sleep_episode(epochs)
    if not period:
        return None
    sleep_epochs = sum(s in ("n1", "n2", "n3", "rem") for s in period)
    awakenings, previous = 0, None
    for stage in period:
        if stage == "wake" and previous != "wake":
            awakenings += 1
        previous = stage
    return SleepNight(
        record=path.name[:7],
        sleep_period_h=len(period) / 120,
        total_sleep_h=sleep_epochs / 120,
        efficiency=sleep_epochs / len(period),
        waso_min=period.count("wake") * 0.5,
        awakenings=awakenings,
        stages_h={k: period.count(k) / 120 for k in ("n1", "n2", "n3", "rem")},
    )
