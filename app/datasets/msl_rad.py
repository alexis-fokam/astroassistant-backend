"""NASA Curiosity RAD: absorbed dose rate measured inside the spacecraft on the way to Mars.

Source: PDS Planetary Plasma Interactions node, volume MSL-M-RAD-3-RDR-V1.0, directory
``DATA/CRUISE`` (one ~40 MB ASCII file per day, December 2011 to July 2012).
Each observation (~8.5 min) carries ``[DOSIMETRY_TOTAL_DOSE_B]`` and ``[DOSIMETRY_TOTAL_DOSE_E]``
in microgray per hour (RAD RDR SIS). Files are streamed and only the dose rates are kept,
so the full cruise fits in a small CSV.

Dose equivalent: during cruise RAD measured an average quality factor of about 3.8
(Zeitlin et al., Science 2013), used to convert absorbed dose (Gy) to dose equivalent (Sv).
"""

from __future__ import annotations

import csv
import http.client
import re
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from app.datasets.http import get_text, iter_lines
from app.datasets.paths import MSL_RAD_CSV, ensure_dir

ROOT = "https://pds-ppi.igpp.ucla.edu/data/MSL-M-RAD-3-RDR-V1.0/DATA/CRUISE/"
CRUISE_QUALITY_FACTOR = 3.8

_FILE_RE = re.compile(r'href="(RAD_RDR_\d{4}_\d{3}_\d{2}_\d{2}_C\d{3}_V\d{2}\.TXT)"')
_SECTION_RE = re.compile(r"^\[(\w+): \d+\]$")
CSV_HEADER = ["utc", "dose_rate_b_ugy_h", "dose_rate_e_ugy_h", "dose_equivalent_usv_h"]


@dataclass(frozen=True)
class DoseSample:
    utc: datetime
    dose_rate_b_ugy_h: float  # silicon detector B
    dose_rate_e_ugy_h: float  # plastic scintillator E (tissue-like)

    @property
    def dose_equivalent_usv_h(self) -> float:
        return self.dose_rate_e_ugy_h * CRUISE_QUALITY_FACTOR


def list_cruise_files() -> list[str]:
    return sorted(set(_FILE_RE.findall(get_text(ROOT))))


def parse_utc(value: str) -> datetime:
    """RAD times are ``YYYY-DOY HH:MM:SS``."""
    return datetime.strptime(value.strip('"'), "%Y-%j %H:%M:%S").replace(tzinfo=UTC)


def parse_lines(lines: Iterable[str]) -> Iterator[DoseSample]:
    """Extract one dose sample per observation from an RDR text stream."""
    section = None
    utc: datetime | None = None
    dose_b: float | None = None
    for line in lines:
        stripped = line.strip()
        header = _SECTION_RE.match(stripped)
        if header:
            section = header.group(1)
            if section == "OBSERVATION":
                utc, dose_b = None, None
            continue
        if not stripped:
            continue
        if section == "OBSERVATION" and stripped.startswith("START_OBS_UTC="):
            utc = parse_utc(stripped.split("=", 1)[1])
        elif section == "DOSIMETRY_TOTAL_DOSE_B":
            dose_b = float(stripped)
            section = None
        elif section == "DOSIMETRY_TOTAL_DOSE_E":
            section = None
            dose_e = float(stripped)
            # Negative or zero values flag invalid observations in RDR files.
            if utc and dose_b is not None and dose_b > 0 and dose_e > 0:
                yield DoseSample(utc, dose_b, dose_e)


def file_date(name: str) -> date:
    """Observation day encoded in a cruise file name (``RAD_RDR_YYYY_DDD_...``)."""
    _, _, year, doy, *_ = name.split("_")
    return datetime.strptime(f"{year}-{doy}", "%Y-%j").date()


def fetch_file(name: str, retries: int = 4) -> list[DoseSample]:
    """Stream one cruise file; the PDS server sometimes resets long transfers, so retry."""
    for attempt in range(retries):
        try:
            return list(parse_lines(iter_lines(ROOT + name)))
        except (OSError, http.client.HTTPException) as error:
            if attempt == retries - 1:
                raise
            wait = 10 * 2**attempt
            print(f"  {name}: {error.__class__.__name__}, retry in {wait} s")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _resume_point(output: Path) -> date | None:
    """Last day already in the CSV; its rows are dropped so that day is fetched again."""
    if not output.exists():
        return None
    with output.open(encoding="utf-8") as handle:
        rows = list(csv.reader(handle))[1:]
    if not rows:
        return None
    last = datetime.fromisoformat(rows[-1][0]).date()
    kept = [r for r in rows if datetime.fromisoformat(r[0]).date() < last]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerows(kept)
    return last


def fetch(
    every_nth_day: int = 1, output: Path = MSL_RAD_CSV, *, resume: bool = True
) -> tuple[Path, int]:
    """Stream cruise files (optionally one day out of N) and write the dose CSV.

    With ``resume`` (default) an interrupted download continues from the last day in
    the CSV instead of starting over. A file that keeps failing is skipped and reported.
    """
    ensure_dir(output.parent)
    files = list_cruise_files()[::every_nth_day]
    since = _resume_point(output) if resume else None
    if since:
        files = [f for f in files if file_date(f) >= since]
        print(f"Resuming from {since} ({len(files)} files left)")
    else:
        with output.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow(CSV_HEADER)
    count, skipped = 0, []
    with output.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        for i, name in enumerate(files, 1):
            try:
                samples = fetch_file(name)
            except (OSError, http.client.HTTPException) as error:
                skipped.append(name)
                print(f"  {name}: skipped ({error})")
                continue
            writer.writerows(
                [
                    s.utc.isoformat(),
                    f"{s.dose_rate_b_ugy_h:.4f}",
                    f"{s.dose_rate_e_ugy_h:.4f}",
                    f"{s.dose_equivalent_usv_h:.4f}",
                ]
                for s in samples
            )
            handle.flush()
            count += len(samples)
            print(f"[{i}/{len(files)}] {name}: {len(samples)} samples")
    if skipped:
        print(f"{len(skipped)} file(s) skipped; run the command again to retry them.")
    return output, count


def load(path: Path = MSL_RAD_CSV) -> list[DoseSample]:
    with path.open(encoding="utf-8") as handle:
        return [
            DoseSample(
                datetime.fromisoformat(row["utc"]),
                float(row["dose_rate_b_ugy_h"]),
                float(row["dose_rate_e_ugy_h"]),
            )
            for row in csv.DictReader(handle)
        ]
