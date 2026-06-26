"""Tiny HTTP layer: retrying GETs with an on-disk cache.

Bioconductor's static files (VIEWS, config.yaml, stats tabs) are large and change
at most weekly, so a content cache keyed by URL keeps re-runs cheap and polite.
Set ``BIOCINTEL_NO_CACHE=1`` to bypass.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import httpx

CACHE_DIR = Path(os.getenv("BIOCINTEL_CACHE_DIR", "data/cache"))
_TIMEOUT = httpx.Timeout(60.0, connect=20.0)
_RETRIES = 4
_BACKOFF = 1.5


class HttpError(RuntimeError):
    """A non-retryable HTTP failure (e.g. 404) surfaced to the caller."""

    def __init__(self, url: str, status: int):
        self.url = url
        self.status = status
        super().__init__(f"HTTP {status} for {url}")


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    return CACHE_DIR / digest


def get_text(url: str, *, use_cache: bool = True) -> str:
    """GET ``url`` as text, with retries on transient errors and a disk cache.

    Raises :class:`HttpError` on a definitive 4xx (so callers can skip a missing
    resource without aborting the run — see ``extract_downloads``).
    """
    use_cache = use_cache and os.getenv("BIOCINTEL_NO_CACHE") != "1"
    cache = _cache_path(url)
    if use_cache and cache.exists():
        return cache.read_text(encoding="utf-8")

    last_exc: Exception | None = None
    for attempt in range(_RETRIES):
        try:
            resp = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True)
            if 400 <= resp.status_code < 500:
                raise HttpError(url, resp.status_code)
            resp.raise_for_status()
            text = resp.text
            if use_cache:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(text, encoding="utf-8")
            return text
        except HttpError:
            raise
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            time.sleep(_BACKOFF**attempt)
    raise RuntimeError(f"GET failed after {_RETRIES} attempts: {url}") from last_exc
