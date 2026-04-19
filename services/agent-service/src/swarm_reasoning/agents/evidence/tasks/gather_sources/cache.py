"""sqlite-backed cache for Perplexity Sonar ``search_results``.

Dev-only convenience to avoid duplicate Sonar calls during local
iteration. Mirrors :class:`swarm_reasoning.agents.web.FetchCache`:
single sqlite file, no TTL, no eviction (``rm`` to clear).

Activation contract: the agent-service NEVER constructs a ``SonarCache``.
The CLI constructs one when caching is desired and threads it through
``build_evidence_agent``. Production deployments do not pass an instance,
so the production path never touches sqlite.

Bypass: even when an instance is provided, setting the ``SONAR_CACHE``
env var to ``bypass`` short-circuits both ``get`` and ``set`` calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from swarm_reasoning.agents.evidence.tasks.gather_sources.models import RecencyHint

_SONAR_CACHE_ENV = "SONAR_CACHE"
_SONAR_CACHE_PATH_ENV = "SONAR_CACHE_PATH"


def _default_path() -> Path:
    """Default sqlite path: ``~/.cache/fact-checker/sonar.db``."""
    return Path.home() / ".cache" / "fact-checker" / "sonar.db"


def _cache_key(
    *,
    claim_text: str,
    domains: tuple[str, ...],
    recency: RecencyHint,
    context: str,
    model: str,
) -> str:
    """Compute the sha256 cache key for a Sonar request.

    ``claim_text`` is normalized (``strip().lower()``) before hashing so
    near-identical claims with trivial whitespace differences share a
    cache slot.
    """
    normalized = claim_text.strip().lower()
    payload = json.dumps(
        [
            model,
            sorted(domains),
            recency.window,
            recency.after_date,
            recency.before_date,
            context,
            normalized,
        ],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class SonarCache:
    """sqlite-backed cache of Sonar ``search_results`` arrays.

    Single file, no TTL, no eviction. Concurrent-safe at the sqlite level
    (one connection per call). Construct only in the CLI; never in the
    agent service.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or Path(os.environ.get(_SONAR_CACHE_PATH_ENV) or _default_path())
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sonar_results "
                "(key TEXT PRIMARY KEY, results TEXT NOT NULL)"
            )

    @staticmethod
    def bypass() -> bool:
        """Return True iff ``SONAR_CACHE=bypass`` is set in the environment."""
        return os.environ.get(_SONAR_CACHE_ENV, "").lower() == "bypass"

    def get(self, key: str) -> list[dict] | None:
        """Look up cached search_results for ``key``; return None on miss."""
        with sqlite3.connect(self._path) as conn:
            row = conn.execute("SELECT results FROM sonar_results WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    def set(self, key: str, results: list[dict]) -> None:
        """Insert or replace cached search_results for ``key``."""
        with sqlite3.connect(self._path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sonar_results (key, results) VALUES (?, ?)",
                (key, json.dumps(results)),
            )
