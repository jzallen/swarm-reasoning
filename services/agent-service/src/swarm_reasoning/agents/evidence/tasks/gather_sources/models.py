"""Frozen projection dataclasses for the gather_sources two-pass flow.

- :class:`RecencyHint` — pass-1 subagent's optional recency window/bounds.
- :class:`DiscoveryResult` — composite of pass-1 domains + rationale + recency.
- :class:`SonarResult` — projection of one entry in Sonar's
  ``search_results`` array.

Mirrors the ``ReviewedClaim`` / ``WebContentDocument`` frozen + classmethod
pattern: callers construct via ``from_state`` / ``from_result``, never the
raw constructor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecencyHint:
    """Optional recency hint surfaced by the discovery subagent."""

    window: str | None = None  # one of "hour" / "day" / "week" / "month" / "year"
    after_date: str | None = None  # ISO8601 YYYY-MM-DD lower bound
    before_date: str | None = None  # ISO8601 YYYY-MM-DD upper bound

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "RecencyHint":
        """Project the discovery subagent's _DiscoverState dict into a RecencyHint."""
        return cls(
            window=state.get("window") or None,
            after_date=state.get("after_date") or None,
            before_date=state.get("before_date") or None,
        )


@dataclass(frozen=True)
class DiscoveryResult:
    """Composite result of pass-1 (Haiku source-discovery)."""

    domains: tuple[str, ...]
    rationale: str
    recency: RecencyHint

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> "DiscoveryResult":
        """Project the discovery subagent's final state dict into a DiscoveryResult."""
        return cls(
            domains=tuple(state.get("domains") or []),
            rationale=str(state.get("rationale") or ""),
            recency=RecencyHint.from_state(state),
        )


@dataclass(frozen=True)
class SonarResult:
    """Projection of one entry in Perplexity Sonar's ``search_results`` array."""

    title: str
    url: str
    snippet: str
    date: str | None
    last_updated: str | None
    source: str  # "web" | "attachment"

    @classmethod
    def from_result(cls, raw: dict[str, Any]) -> "SonarResult":
        """Project a raw Sonar search_results entry into a SonarResult."""
        return cls(
            title=str(raw.get("title") or ""),
            url=str(raw.get("url") or ""),
            snippet=str(raw.get("snippet") or ""),
            date=raw.get("date"),
            last_updated=raw.get("last_updated"),
            source=str(raw.get("source") or "web"),
        )
