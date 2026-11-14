"""Minimal HTTP helpers on the standard library (no extra runtime dependency)."""

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
    """GET a JSON document, retrying transient failures with backoff."""
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(_request(url), timeout=TIMEOUT_S) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            # 429 = rate limited (DEMO_KEY allows ~30 requests per hour): wait and retry.
            if error.code != 429 or attempt == retries - 1:
                raise
        except urllib.error.URLError:
            if attempt == retries - 1:
                raise
        time.sleep(2**attempt * 5)
    raise RuntimeError("unreachable")


def iter_lines(url: str) -> Iterator[str]:
    """Stream a large text file line by line without keeping it on disk."""
    with urllib.request.urlopen(_request(url), timeout=TIMEOUT_S) as response:
        for raw in response:
            yield raw.decode("latin-1").rstrip("\r\n")


def get_text(url: str) -> str:
    with urllib.request.urlopen(_request(url), timeout=TIMEOUT_S) as response:
        return response.read().decode("latin-1")
