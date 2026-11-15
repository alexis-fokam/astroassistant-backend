"""Catalogue of every dataset used by Astro Assistant, with provenance and licence.

Seeded into the ``dataset_sources`` table so each imported row can be traced back to
its origin (spec §12, judging criterion "use of space agency data").
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
        code="nasa-osdr-i4",
        name="Inspiration4 mission data (OSDR)",
        agency="NASA",
        url="https://osdr.nasa.gov/bio/repo/search?q=inspiration4",
        licence="Open data, OSDR terms",
        usage=(
            "Orders of magnitude of in-flight physiology and "
            "cognition used to calibrate the simulator."
        ),
        size="varies",
        bundled=False,
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
        code="physionet-bidsleep",
        name="Multi-night wearable sleep dataset (Apple Watch + EEG labels)",
        agency="PhysioNet",
        url="https://www.physionet.org/content/bidsleep-dataset/",
        licence="PhysioNet open access",
        usage="Realistic night-time heart rate and motion for the telemetry simulator (F7, F15).",
        size="varies",
        bundled=False,
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
    DatasetInfo(
        code="monash-pvt",
        name="PVT under 40 h sleep deprivation (Monash University)",
        agency="Monash University",
        url="https://researchdata.edu.au/shortened-pst-prediction-laboratory/false",
        licence="CC BY-NC-ND 4.0",
        usage="Reference reaction times and lapses for the vigilance test (F8).",
        size="varies",
        bundled=False,
    ),
]


def by_code(code: str) -> DatasetInfo:
    return next(info for info in CATALOG if info.code == code)
