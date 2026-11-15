"""Command line for the open datasets.

python -m app.datasets fetch donki      # NASA DONKI (SEP + CME), reference windows
python -m app.datasets fetch goes       # NOAA GOES proton flux snapshot
python -m app.datasets fetch msl-rad    # Curiosity RAD cruise dose (streams ~9 GB, resumable)
python -m app.datasets fetch bidmc      # PhysioNet BIDMC numerics (~1 MB, calibration)
python -m app.datasets fetch sleep-edf  # PhysioNet Sleep-EDF hypnograms (~1 MB, calibration)
python -m app.datasets catalog          # list every dataset and where to get it
"""

from __future__ import annotations

import argparse

from app.core.config import get_settings
from app.datasets import donki, goes, msl_rad, physionet
from app.datasets.catalog import CATALOG


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m app.datasets", description="Astro Assistant open datasets"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="download a bundled dataset into data/nasa/")
    fetch.add_argument("source", choices=["donki", "goes", "msl-rad", "bidmc", "sleep-edf", "all"])
    fetch.add_argument("--every", type=int, default=1, help="msl-rad: keep one cruise day out of N")
    fetch.add_argument(
        "--restart", action="store_true", help="msl-rad: ignore the existing CSV and start over"
    )
    sub.add_parser("catalog", help="list every dataset")
    args = parser.parse_args()

    if args.command == "catalog":
        for info in CATALOG:
            mark = "bundled " if info.bundled else "external"
            print(f"[{mark}] {info.code:<20} {info.size:<24} {info.url}")
        return

    sources = ["donki", "goes", "msl-rad"] if args.source == "all" else [args.source]
    if "donki" in sources:
        for path in donki.fetch(get_settings().nasa_api_key):
            print(f"DONKI -> {path}")
    if "goes" in sources:
        print(f"GOES  -> {goes.fetch()}")
    if args.source == "bidmc":
        print(f"BIDMC -> {len(physionet.fetch_bidmc())} files in data/external/bidmc/")
    if args.source == "sleep-edf":
        print(
            f"Sleep-EDF -> {len(physionet.fetch_sleep_edf_hypnograms())} hypnograms "
            "in data/external/sleep-edfx/"
        )
    if "msl-rad" in sources:
        path, count = msl_rad.fetch(every_nth_day=args.every, resume=not args.restart)
        print(f"RAD   -> {path} ({count} samples)")


if __name__ == "__main__":
    main()
