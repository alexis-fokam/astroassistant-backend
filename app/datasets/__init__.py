"""Open datasets used by Astro Assistant (spec §12).

- ``donki``: NASA DONKI space-weather events (solar particle events, CMEs).
- ``goes``: NOAA GOES integral proton flux (solar radiation storm alerts).
- ``msl_rad``: NASA Curiosity RAD dose rate measured during the cruise to Mars.
- ``catalog``: larger external datasets (physiology, sleep, vigilance) fetched on demand.

Small NASA extracts are versioned under ``data/nasa/`` so the demo runs offline;
large external datasets go to ``data/external/`` (git-ignored).
Run ``python -m app.datasets --help`` for the command line.
"""
