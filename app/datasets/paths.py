"""Where dataset files live on disk."""

from pathlib import Path

from app.core.config import BASE_DIR

DATA_DIR = BASE_DIR / "data"
# Petits extraits versionnés utilisés par la démo hors ligne.
NASA_DIR = DATA_DIR / "nasa"
DONKI_DIR = NASA_DIR / "donki"
GOES_DIR = NASA_DIR / "goes"
MSL_RAD_CSV = NASA_DIR / "msl_rad_cruise_dose.csv"
# Extraits PhysioNet (ODC-By, redistribuables avec attribution) : références de calibration.
PHYSIONET_DIR = DATA_DIR / "physionet"
# Grands jeux tiers, téléchargés à la demande et jamais versionnés.
EXTERNAL_DIR = DATA_DIR / "external"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
