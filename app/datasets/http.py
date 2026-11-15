"""Utilitaires HTTP minimaux sur la bibliothèque standard (aucune dépendance en plus)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

USER_AGENT = "AstroAssistant/0.1 (NASA Space Apps 2026 prototype)"
TIMEOUT_S = 60


def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})


def get_json(url: str, retries: int = 3) -> Any:
    """GET d'un document JSON, en réessayant les échecs passagers avec attente croissante."""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(_request(url), timeout=TIMEOUT_S) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            # 429 = quota dépassé (DEMO_KEY : ~30 requêtes/heure) : attendre et réessayer.
            if error.code != 429 or attempt == retries - 1:
                raise
        except urllib.error.URLError:
            if attempt == retries - 1:
                raise
        time.sleep(2**attempt * 5)
    raise RuntimeError("unreachable")


def iter_lines(url: str) -> Iterator[str]:
    """Lire un gros fichier texte ligne par ligne sans le garder sur le disque."""
    with urllib.request.urlopen(_request(url), timeout=TIMEOUT_S) as response:
        for raw in response:
            yield raw.decode("latin-1").rstrip("\r\n")


def get_text(url: str) -> str:
    with urllib.request.urlopen(_request(url), timeout=TIMEOUT_S) as response:
        return response.read().decode("latin-1")
