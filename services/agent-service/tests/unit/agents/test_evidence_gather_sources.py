"""Unit tests for evidence tasks.gather_sources.

Covers the two-pass flow (Haiku discovery -> Sonar -> fetch), each of
the four honest-empty exit sites, the SonarCache short-circuit, and the
denylist post-filter. The discovery subagent and the Sonar HTTP call are
both stubbed; the WebContentExtractor is the same minimal stub used by
the prior lookup_sources tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from swarm_reasoning.agents.evidence.tasks.gather_sources import (
    DiscoveryResult,
    SonarResult,
    gather_sources,
)
from swarm_reasoning.agents.evidence.tasks.gather_sources import task as task_module
from swarm_reasoning.agents.web import FetchErr, FetchOk, WebContentDocument


@pytest.fixture(autouse=True)
def _silence_share_progress(monkeypatch):
    """share_progress requires a LangGraph runnable context; stub to no-op."""
    monkeypatch.setattr(task_module, "share_progress", lambda *_args, **_kw: None)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


@dataclass
class _StubExtractor:
    """Minimal extractor stub: returns canned results keyed by URL."""

    by_url: dict

    async def fetch(self, url: str):
        return self.by_url[url]


@dataclass
class _StubSubagent:
    """Discovery subagent stub: returns a canned final-state dict, or raises."""

    state: dict[str, Any] | None = None
    raises: Exception | None = None

    async def ainvoke(self, payload: dict, config: dict) -> dict[str, Any]:
        if self.raises is not None:
            raise self.raises
        return self.state or {}


class _StubCache:
    """In-memory SonarCache stand-in. Tracks gets and sets."""

    def __init__(self, primed: dict | None = None) -> None:
        self.store: dict[str, list[dict]] = dict(primed or {})
        self.gets: list[str] = []
        self.sets: list[tuple[str, list[dict]]] = []

    @staticmethod
    def bypass() -> bool:
        return False

    def get(self, key: str) -> list[dict] | None:
        self.gets.append(key)
        return self.store.get(key)

    def set(self, key: str, results: list[dict]) -> None:
        self.sets.append((key, results))
        self.store[key] = results


def _ok(text: str, url: str = "https://example") -> FetchOk:
    return FetchOk(
        document=WebContentDocument(url=url, text=text, accessed_at="2026-04-19T00:00:00Z")
    )


def _state(domains: list[str], rationale: str = "ok") -> dict[str, Any]:
    return {"domains": domains, "rationale": rationale}


def _common_kwargs() -> dict[str, Any]:
    return dict(
        claim_text="vaccines are safe",
        domain="HEALTHCARE",
        persons=None,
        organizations=None,
        statistics=None,
        dates=None,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gather_sources_two_pass_happy_path(monkeypatch):
    """Pass-1 returns domains; Sonar returns one result; first fetch succeeds."""
    sonar_calls: list[dict] = []

    async def fake_sonar(*, claim_text, domains, recency):
        sonar_calls.append({"claim_text": claim_text, "domains": domains, "recency": recency})
        return [
            {
                "title": "CDC: vaccines",
                "url": "https://cdc.gov/vax",
                "snippet": "...",
                "date": None,
                "last_updated": None,
                "source": "web",
            }
        ]

    monkeypatch.setattr(task_module, "_sonar_search", fake_sonar)

    subagent = _StubSubagent(state=_state(["cdc.gov", "who.int"]))
    extractor = _StubExtractor(by_url={"https://cdc.gov/vax": _ok("Real CDC content")})

    result = await gather_sources(extractor=extractor, subagent=subagent, **_common_kwargs())

    assert len(result) == 1
    assert result[0]["url"] == "https://cdc.gov/vax"
    assert result[0]["name"] == "CDC: vaccines"
    assert "Real CDC content" in result[0]["content"]
    assert sonar_calls and sonar_calls[0]["domains"] == ["cdc.gov", "who.int"]


@pytest.mark.asyncio
async def test_gather_sources_passes_recency_hint_to_sonar(monkeypatch):
    """RecencyHint fields surface in the Sonar call."""
    captured: dict = {}

    async def fake_sonar(*, claim_text, domains, recency):
        captured["recency"] = recency
        return []

    monkeypatch.setattr(task_module, "_sonar_search", fake_sonar)

    subagent = _StubSubagent(
        state={
            "domains": ["cdc.gov"],
            "rationale": "ok",
            "window": "month",
            "after_date": "2025-01-01",
        }
    )
    extractor = _StubExtractor(by_url={})

    await gather_sources(extractor=extractor, subagent=subagent, **_common_kwargs())

    assert captured["recency"].window == "month"
    assert captured["recency"].after_date == "2025-01-01"


# ---------------------------------------------------------------------------
# Four honest-empty exit sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gather_sources_returns_empty_on_discovery_exception(monkeypatch):
    """Exit #1: discovery subagent raises -> []."""
    subagent = _StubSubagent(raises=RuntimeError("boom"))
    extractor = _StubExtractor(by_url={})
    result = await gather_sources(extractor=extractor, subagent=subagent, **_common_kwargs())
    assert result == []


@pytest.mark.asyncio
async def test_gather_sources_returns_empty_when_all_domains_denylisted(monkeypatch):
    """Exit #2: every discovery domain is in denylist.json -> []."""
    sonar_called = False

    async def fake_sonar(**_):
        nonlocal sonar_called
        sonar_called = True
        return []

    monkeypatch.setattr(task_module, "_sonar_search", fake_sonar)

    subagent = _StubSubagent(state=_state(["wikipedia.org", "reddit.com", "medium.com"]))
    extractor = _StubExtractor(by_url={})

    result = await gather_sources(extractor=extractor, subagent=subagent, **_common_kwargs())
    assert result == []
    assert sonar_called is False


@pytest.mark.asyncio
async def test_gather_sources_returns_empty_on_sonar_exception(monkeypatch):
    """Exit #3: Sonar raises -> []."""

    async def fake_sonar(**_):
        raise RuntimeError("sonar down")

    monkeypatch.setattr(task_module, "_sonar_search", fake_sonar)

    subagent = _StubSubagent(state=_state(["cdc.gov"]))
    extractor = _StubExtractor(by_url={})

    result = await gather_sources(extractor=extractor, subagent=subagent, **_common_kwargs())
    assert result == []


@pytest.mark.asyncio
async def test_gather_sources_returns_empty_when_sonar_yields_no_candidates(monkeypatch):
    """Exit #4a: Sonar returns []; gather_sources yields []."""

    async def fake_sonar(**_):
        return []

    monkeypatch.setattr(task_module, "_sonar_search", fake_sonar)

    subagent = _StubSubagent(state=_state(["cdc.gov"]))
    extractor = _StubExtractor(by_url={})

    result = await gather_sources(extractor=extractor, subagent=subagent, **_common_kwargs())
    assert result == []


@pytest.mark.asyncio
async def test_gather_sources_returns_empty_when_all_fetches_fail(monkeypatch):
    """Exit #4b: Sonar returns candidates, all fetches fail -> []."""

    async def fake_sonar(**_):
        return [
            {
                "title": "a",
                "url": "https://a",
                "snippet": "",
                "date": None,
                "last_updated": None,
                "source": "web",
            },
            {
                "title": "b",
                "url": "https://b",
                "snippet": "",
                "date": None,
                "last_updated": None,
                "source": "web",
            },
        ]

    monkeypatch.setattr(task_module, "_sonar_search", fake_sonar)

    subagent = _StubSubagent(state=_state(["cdc.gov"]))
    extractor = _StubExtractor(
        by_url={
            "https://a": FetchErr(reason="404"),
            "https://b": _ok(""),
        }
    )

    result = await gather_sources(extractor=extractor, subagent=subagent, **_common_kwargs())
    assert result == []


# ---------------------------------------------------------------------------
# Cache short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sonar_cache_hit_skips_sonar_call(monkeypatch):
    """When the cache holds an entry for the request key, Sonar is not called."""
    sonar_calls = 0

    async def fake_sonar(**_):
        nonlocal sonar_calls
        sonar_calls += 1
        return []

    monkeypatch.setattr(task_module, "_sonar_search", fake_sonar)

    cached_results = [
        {
            "title": "Cached CDC",
            "url": "https://cdc.gov/cached",
            "snippet": "",
            "date": None,
            "last_updated": None,
            "source": "web",
        }
    ]
    cache = _StubCache()
    # Prime cache: compute the same key gather_sources would
    from swarm_reasoning.agents.evidence.tasks.gather_sources.cache import _cache_key
    from swarm_reasoning.agents.evidence.tasks.gather_sources.sonar_client import (
        SONAR_CONTEXT_SIZE,
        SONAR_MODEL,
    )

    discovery = DiscoveryResult.from_state(_state(["cdc.gov"]))
    key = _cache_key(
        claim_text=_common_kwargs()["claim_text"],
        domains=discovery.domains,
        recency=discovery.recency,
        context=SONAR_CONTEXT_SIZE,
        model=SONAR_MODEL,
    )
    cache.store[key] = cached_results

    subagent = _StubSubagent(state=_state(["cdc.gov"]))
    extractor = _StubExtractor(by_url={"https://cdc.gov/cached": _ok("from cache")})

    result = await gather_sources(
        extractor=extractor,
        subagent=subagent,
        sonar_cache=cache,
        **_common_kwargs(),
    )

    assert sonar_calls == 0
    assert len(result) == 1
    assert result[0]["url"] == "https://cdc.gov/cached"
    assert cache.gets == [key]


@pytest.mark.asyncio
async def test_sonar_cache_miss_populates_on_set(monkeypatch):
    """Cache miss invokes Sonar, then writes the result back."""
    raw = [
        {
            "title": "fresh",
            "url": "https://x",
            "snippet": "",
            "date": None,
            "last_updated": None,
            "source": "web",
        }
    ]

    async def fake_sonar(**_):
        return raw

    monkeypatch.setattr(task_module, "_sonar_search", fake_sonar)

    cache = _StubCache()
    subagent = _StubSubagent(state=_state(["cdc.gov"]))
    extractor = _StubExtractor(by_url={"https://x": _ok("body")})

    await gather_sources(
        extractor=extractor,
        subagent=subagent,
        sonar_cache=cache,
        **_common_kwargs(),
    )

    assert len(cache.sets) == 1
    assert cache.sets[0][1] == raw


# ---------------------------------------------------------------------------
# Denylist filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_denylist_filter_drops_flagged_domains_before_sonar(monkeypatch):
    """Domains present in denylist.json are dropped before the Sonar request."""
    captured_domains: list[str] = []

    async def fake_sonar(*, claim_text, domains, recency):
        captured_domains.extend(domains)
        return []

    monkeypatch.setattr(task_module, "_sonar_search", fake_sonar)

    subagent = _StubSubagent(state=_state(["cdc.gov", "wikipedia.org", "nih.gov"]))
    extractor = _StubExtractor(by_url={})

    await gather_sources(extractor=extractor, subagent=subagent, **_common_kwargs())

    assert captured_domains == ["cdc.gov", "nih.gov"]


# ---------------------------------------------------------------------------
# SonarResult projection
# ---------------------------------------------------------------------------


def test_sonar_result_projection_handles_missing_fields():
    """SonarResult.from_result is tolerant of partial Sonar payloads."""
    r = SonarResult.from_result({"url": "https://x"})
    assert r.url == "https://x"
    assert r.title == ""
    assert r.snippet == ""
    assert r.date is None
    assert r.last_updated is None
    assert r.source == "web"
