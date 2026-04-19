"""Unit tests for evidence tasks.gather_sources.

Covers the two-pass flow (Haiku discovery -> Sonar -> fetch), each of
the four honest-empty exit sites, and the denylist post-filter. The
discovery subagent and ``sonar_search`` are both stubbed; the
WebContentExtractor is the same minimal stub used by the prior
lookup_sources tests. SonarCache behavior is owned by
``sonar_search`` and tested at that boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from swarm_reasoning.agents.evidence.tasks.gather_sources import (
    SonarResult,
    gather_sources,
)
from swarm_reasoning.agents.evidence.tasks.gather_sources import (
    sonar_client as sonar_client_module,
)
from swarm_reasoning.agents.web import FetchErr, FetchOk, WebContentDocument


@pytest.fixture(autouse=True)
def _silence_share_progress(monkeypatch):
    """share_progress requires a LangGraph runnable context; stub to no-op."""
    import swarm_reasoning.agents.messaging as _msg_mod
    monkeypatch.setattr(_msg_mod, "share_progress", lambda *_args, **_kw: None)


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
        config={"configurable": {"thread_id": "test-thread", "checkpoint_ns": ""}},
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gather_sources_two_pass_happy_path(monkeypatch):
    """Pass-1 returns domains; Sonar returns one result; first fetch succeeds."""
    sonar_calls: list[dict] = []

    async def fake_sonar(query, *, bypass_cache=False):
        sonar_calls.append(
            {
                "claim_text": query.claim_text,
                "domains": list(query.domains),
                "recency": query.recency,
            }
        )
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

    monkeypatch.setattr(sonar_client_module, "sonar_search", fake_sonar)

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

    async def fake_sonar(query, *, bypass_cache=False):
        captured["recency"] = query.recency
        return []

    monkeypatch.setattr(sonar_client_module, "sonar_search", fake_sonar)

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

    monkeypatch.setattr(sonar_client_module, "sonar_search", fake_sonar)

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

    monkeypatch.setattr(sonar_client_module, "sonar_search", fake_sonar)

    subagent = _StubSubagent(state=_state(["cdc.gov"]))
    extractor = _StubExtractor(by_url={})

    result = await gather_sources(extractor=extractor, subagent=subagent, **_common_kwargs())
    assert result == []


@pytest.mark.asyncio
async def test_gather_sources_returns_empty_when_sonar_yields_no_candidates(monkeypatch):
    """Exit #4a: Sonar returns []; gather_sources yields []."""

    async def fake_sonar(**_):
        return []

    monkeypatch.setattr(sonar_client_module, "sonar_search", fake_sonar)

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

    monkeypatch.setattr(sonar_client_module, "sonar_search", fake_sonar)

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
# Denylist filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_denylist_filter_drops_flagged_domains_before_sonar(monkeypatch):
    """Domains present in denylist.json are dropped before the Sonar request."""
    captured_domains: list[str] = []

    async def fake_sonar(query, *, bypass_cache=False):
        captured_domains.extend(query.domains)
        return []

    monkeypatch.setattr(sonar_client_module, "sonar_search", fake_sonar)

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
