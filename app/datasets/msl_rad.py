"""NASA Curiosity RAD : débit de dose absorbée mesuré dans le vaisseau en route vers Mars.

Source : nœud PDS Planetary Plasma Interactions, volume MSL-M-RAD-3-RDR-V1.0, dossier
``DATA/CRUISE`` (un fichier ASCII d'environ 40 Mo par jour, de décembre 2011 à juillet 2012).
Chaque observation (~8,5 min) porte ``[DOSIMETRY_TOTAL_DOSE_B]`` et
``[DOSIMETRY_TOTAL_DOSE_E]`` en microgray par heure (RAD RDR SIS). Les fichiers sont lus en
flux et seuls les débits de dose sont gardés : tout le trajet tient dans un petit CSV.

Équivalent de dose : pendant le trajet, RAD a mesuré un facteur de qualité moyen d'environ
3,8 (Zeitlin et al., Science 2013), utilisé pour passer de la dose absorbée (Gy) à
l'équivalent de dose (Sv).
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
    """Les dates RAD sont au format ``AAAA-JJJ HH:MM:SS`` (jour de l'année)."""
    return datetime.strptime(value.strip('"'), "%Y-%j %H:%M:%S").replace(tzinfo=UTC)


def parse_lines(lines: Iterable[str]) -> Iterator[DoseSample]:
    """Extraire un échantillon de dose par observation d'un flux texte RDR."""
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
            # Une valeur négative ou nulle signale une observation RDR invalide.
            if utc and dose_b is not None and dose_b > 0 and dose_e > 0:
                yield DoseSample(utc, dose_b, dose_e)


def file_date(name: str) -> date:
    """Jour d'observation codé dans le nom d'un fichier (``RAD_RDR_YYYY_DDD_...``)."""
    _, _, year, doy, *_ = name.split("_")
    return datetime.strptime(f"{year}-{doy}", "%Y-%j").date()


def fetch_file(name: str, retries: int = 4) -> list[DoseSample]:
    """Lire un fichier du trajet ; le serveur PDS coupe parfois les longs transferts : réessayer."""
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
    """Dernier jour déjà dans le CSV ; ses lignes sont retirées pour le retélécharger."""
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


def finalize(output: Path = MSL_RAD_CSV) -> int:
    """Trier le CSV par date et retirer les observations répétées.

    Les fichiers RDR entremêlent plusieurs séquences et certaines observations apparaissent
    deux fois : les lignes brutes ne sont ni ordonnées ni uniques. Renvoie le nombre gardé.
    """
    with output.open(encoding="utf-8") as handle:
        rows = list(csv.reader(handle))[1:]
    unique = {row[0]: row for row in rows}
    ordered = [unique[k] for k in sorted(unique, key=datetime.fromisoformat)]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerows(ordered)
    return len(ordered)


def fetch(
    every_nth_day: int = 1, output: Path = MSL_RAD_CSV, *, resume: bool = True
) -> tuple[Path, int]:
    """Lire les fichiers du trajet (éventuellement un jour sur N) et écrire le CSV de dose.

    Avec ``resume`` (par défaut), un téléchargement interrompu reprend au dernier jour du
    CSV au lieu de recommencer. Un fichier qui échoue sans cesse est sauté et signalé.
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
    total = finalize(output)
    print(f"{total} unique samples in {output.name} ({count} fetched in this run)")
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
