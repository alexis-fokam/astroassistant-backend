"""Catalogue des jeux de données réellement utilisés par Astro Assistant (origine, licence).

Inséré dans la table ``dataset_sources`` pour que chaque ligne importée remonte à sa source
(cahier des charges §12, critère du jury « utilisation des données des agences spatiales »).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetInfo:
    code: str
    name: str
    agency: str
    url: str
    licence: str
    usage: str
    size: str
    # True when the dataset is fetched and versioned by `python -m app.datasets`.
    bundled: bool


CATALOG: list[DatasetInfo] = [
    DatasetInfo(
        code="nasa-donki",
        name="DONKI — Space Weather Database of Notifications, Knowledge, Information",
        agency="NASA",
        url="https://api.nasa.gov",
        licence="US Government work, public domain",
        usage="Solar particle events and CMEs replayed by the dosimetry module (F5, scenario S3).",
        size="< 1 MB",
        bundled=True,
    ),
    DatasetInfo(
        code="nasa-msl-rad",
        name="Curiosity RAD — cruise dose rate (MSL-M-RAD-3-RDR-V1.0)",
        agency="NASA",
        url="https://pds-ppi.igpp.ucla.edu/data/MSL-M-RAD-3-RDR-V1.0/",
        licence="US Government work, public domain",
        usage="Real dose rate measured on the way to Mars; drives the radiation simulator (F5).",
        size="~9 GB raw, ~1 MB extracted",
        bundled=True,
    ),
    DatasetInfo(
        code="noaa-goes-protons",
        name="GOES integral proton flux (7-day)",
        agency="NOAA SWPC",
        url="https://services.swpc.noaa.gov/json/goes/primary/integral-protons-7-day.json",
        licence="US Government work, public domain",
        usage="Solar radiation storm thresholds (S1 >= 10 pfu) for early warning (F5.4).",
        size="< 1 MB",
        bundled=True,
    ),
    DatasetInfo(
        code="wesad",
        name="WESAD — Wearable Stress and Affect Detection",
        agency="Univ. Siegen / UCI",
        url="https://archive.ics.uci.edu/dataset/465/wesad",
        licence="Non-commercial research use, attribution",
        usage="Training and validation of the stress / HRV anomaly detector (F2).",
        size="~2.5 GB",
        bundled=False,
    ),
    DatasetInfo(
        code="sleep-edfx",
        name="Sleep-EDF Database Expanded",
        agency="PhysioNet",
        url="https://physionet.org/content/sleep-edfx/1.0.0/",
        licence="Open Data Commons Attribution v1.0",
        usage="Expert hypnograms of healthy sleepers: sleep duration, short-night threshold (F7).",
        size="~0.7 MB (hypnograms only; full dataset 8.1 GB)",
        bundled=True,
    ),
    DatasetInfo(
        code="physionet-bidmc",
        name="BIDMC PPG and Respiration Dataset (numerics, 1 Hz)",
        agency="PhysioNet",
        url="https://physionet.org/content/bidmc/1.0.0/",
        licence="Open Data Commons Attribution v1.0",
        usage="SpO2, heart and respiratory rate distributions to calibrate thresholds (F1, §6).",
        size="~0.5 MB (numerics only)",
        bundled=True,
    ),
]


def by_code(code: str) -> DatasetInfo:
    return next(info for info in CATALOG if info.code == code)
