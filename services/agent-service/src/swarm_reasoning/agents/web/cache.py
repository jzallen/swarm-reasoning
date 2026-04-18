"""URL-keyed SQLite cache for fetched web documents.

Single-file, no TTL, no eviction -- ``rm`` the file to clear. Bypassed
when the ``FETCH_CACHE`` env var is set to ``bypass``.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import asdict
from pathlib import Path

from swarm_reasoning.agents.web.extractor import WebContentDocument

logger = logging.getLogger(__name__)

_FETCH_CACHE_ENV = "FETCH_CACHE"
_FETCH_CACHE_PATH_ENV = "FETCH_CACHE_PATH"


def _default_cache_path() -> Path:
    return Path.home() / ".cache" / "fact-checker" / "fetch.db"


class FetchCache:
    """URL-keyed cache of extracted web documents.

    Stores a JSON-serialized :class:`WebContentDocument` per URL. When
    ``FETCH_CACHE=bypass`` the cache is a no-op (both reads and writes
    return / persist nothing).
    """

    def __init__(self, path: Path | str | None = None) -> None:
        override = os.environ.get(_FETCH_CACHE_PATH_ENV)
        if path is not None:
            self._path = Path(path)
        elif override:
            self._path = Path(override)
        else:
            self._path = _default_cache_path()

    @staticmethod
    def bypass() -> bool:
        """Return ``True`` when the cache env flag requests bypass."""
        return os.environ.get(_FETCH_CACHE_ENV, "").lower() == "bypass"

    def _conn(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._path))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS fetch_cache (url TEXT PRIMARY KEY, payload TEXT)"
        )
        return conn

    def get(self, url: str) -> WebContentDocument | None:
        """Return the cached document for *url*, or ``None`` on miss / bypass."""
        if self.bypass():
            return None
        try:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT payload FROM fetch_cache WHERE url = ?", (url,)
                ).fetchone()
        except sqlite3.Error:
            logger.exception("Fetch cache read failed for %s", url)
            return None
        if not row:
            return None
        try:
            return WebContentDocument(**json.loads(row[0]))
        except (TypeError, ValueError):
            logger.info("Fetch cache schema mismatch for %s; treating as miss", url)
            return None

    def put(self, document: WebContentDocument) -> None:
        """Persist *document* under its URL. No-op when bypassed."""
        if self.bypass():
            return
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO fetch_cache (url, payload) VALUES (?, ?)",
                    (document.url, json.dumps(asdict(document))),
                )
        except sqlite3.Error:
            logger.exception("Fetch cache write failed for %s", document.url)
