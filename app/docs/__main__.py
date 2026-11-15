"""CLI : ``python -m app.docs [--output CHEMIN]`` écrit le dictionnaire de données."""

import argparse
from datetime import datetime
from pathlib import Path

from app.core.config import BASE_DIR
from app.docs.dictionary import build

DEFAULT_OUTPUT = BASE_DIR / "docs" / "dictionnaire-de-donnees.md"


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app.docs", description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build(generated_at=datetime.now()), encoding="utf-8")
    print(f"Data dictionary written to {args.output}")


if __name__ == "__main__":
    main()
