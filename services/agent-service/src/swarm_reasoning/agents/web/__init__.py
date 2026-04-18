"""Shared web content fetching and extraction (ADR-004).

Provides a URL-keyed fetch path with a configurable strategy chain and a
``FetchResult`` monad for explicit success / error handling.
"""

from __future__ import annotations

from swarm_reasoning.agents.web.cache import FetchCache
from swarm_reasoning.agents.web.extractor import (
    FetchErr,
    FetchOk,
    FetchResult,
    WebContentDocument,
    WebContentExtractor,
    hostname_fallback,
)
from swarm_reasoning.agents.web.strategies import (
    BeautifulSoupStrategy,
    ExtractionFailed,
    ExtractorStrategy,
    RawTextStrategy,
    TrafilaturaStrategy,
)

__all__ = [
    "BeautifulSoupStrategy",
    "ExtractionFailed",
    "ExtractorStrategy",
    "FetchCache",
    "FetchErr",
    "FetchOk",
    "FetchResult",
    "RawTextStrategy",
    "TrafilaturaStrategy",
    "WebContentDocument",
    "WebContentExtractor",
    "hostname_fallback",
]
