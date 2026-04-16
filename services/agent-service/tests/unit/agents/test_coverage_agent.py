"""Tests for coverage agent LangGraph ReAct agent (sr-l0y.5.6).

Verifies:
- CoverageInput/CoverageOutput typed contracts
- Core utility functions (sentiment scoring, framing classification, source selection)
- _Results accumulator dataclass
- Tool factory (_build_tools produces 4 tools)
- Agent construction (create_agent returns invokable graph)
- run_coverage_agent() entry point (observation publishing, heartbeats, progress)
- _publish_observations helper
- Module re-exports from agents.coverage package
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.coverage.agent import (
    _build_tools,
    _publish_observations,
    _Results,
    create_agent,
    run_coverage_agent,
)
from swarm_reasoning.agents.coverage.core import (
    classify_framing,
    compute_compound_sentiment,
    select_top_source,
)
from swarm_reasoning.agents.coverage.models import CoverageInput, CoverageOutput
from swarm_reasoning.models.observation import ObservationCode, ValueType

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class FakePipelineContext:
    """Minimal PipelineContext double for unit tests."""

    run_id: str = "run-test"
    session_id: str = "sess-test"
    published_observations: list = field(default_factory=list)
    published_progress: list = field(default_factory=list)
    heartbeat_calls: list = field(default_factory=list)

    async def publish_observation(self, *, agent, code, value, value_type, **kwargs):
        self.published_observations.append({
            "agent": agent,
            "code": code,
            "value": value,
            "value_type": value_type,
            **kwargs,
        })

    async def publish_progress(self, agent, message):
        self.published_progress.append({"agent": agent, "message": message})

    def heartbeat(self, node_name):
        self.heartbeat_calls.append(node_name)


@pytest.fixture
def ctx():
    return FakePipelineContext()


@pytest.fixture
def sample_sources():
    return [
        {"id": "source-a", "name": "Source A", "credibility_rank": 80},
        {"id": "source-b", "name": "Source B", "credibility_rank": 60},
        {"id": "source-c", "name": "Source C", "credibility_rank": 90},
    ]


@pytest.fixture
def sample_input():
    return CoverageInput(normalized_claim="the unemployment rate dropped to 3.5%")


@pytest.fixture
def sample_articles():
    return [
        {
            "title": "Economy grows amid strong jobs data",
            "url": "https://example.com/article1",
            "source": {"id": "source-a", "name": "Source A"},
        },
        {
            "title": "Unemployment drops to record low",
            "url": "https://example.com/article2",
            "source": {"id": "source-c", "name": "Source C"},
        },
    ]


def _mock_agent_invocation(results: _Results, articles=None, framing_cwe=None, top_source=None):
    """Return an AsyncMock agent whose ainvoke populates results like real tools would."""
    if articles is not None:
        results.articles = articles
    if framing_cwe is not None:
        results.framing_cwe = framing_cwe
    if top_source is not None:
        results.top_source = top_source

    agent = MagicMock()
    agent.ainvoke = AsyncMock(return_value={"messages": []})
    return agent


# ---------------------------------------------------------------------------
# CoverageInput / CoverageOutput typed contracts
# ---------------------------------------------------------------------------


class TestCoverageModels:
    """Test the CoverageInput/CoverageOutput typed contracts."""

    def test_coverage_input_type(self):
        inp: CoverageInput = {"normalized_claim": "test claim"}
        assert inp["normalized_claim"] == "test claim"

    def test_coverage_output_type(self):
        out: CoverageOutput = {
            "articles": [],
            "framing": "ABSENT",
            "compound_score": 0.0,
            "top_source": None,
        }
        assert out["framing"] == "ABSENT"
        assert out["top_source"] is None

    def test_coverage_output_with_articles(self):
        out: CoverageOutput = {
            "articles": [{"title": "Test", "url": "https://x.com", "source": "S", "framing": "N"}],
            "framing": "NEUTRAL",
            "compound_score": 0.01,
            "top_source": {"name": "Source", "url": "https://x.com"},
        }
        assert len(out["articles"]) == 1
        assert out["top_source"]["name"] == "Source"


# ---------------------------------------------------------------------------
# Core utility function tests
# ---------------------------------------------------------------------------


class TestCoreCompoundSentiment:
    """Test compute_compound_sentiment from core.py."""

    def test_empty_headlines(self):
        assert compute_compound_sentiment([]) == 0.0

    def test_positive_headlines(self):
        headlines = ["Great economic growth reported", "Jobs market shows improvement"]
        score = compute_compound_sentiment(headlines)
        assert score > 0.0

    def test_negative_headlines(self):
        headlines = ["Crisis deepens as economy fails", "Losses mount amid market collapse"]
        score = compute_compound_sentiment(headlines)
        assert score < 0.0

    def test_neutral_headlines(self):
        headlines = ["Meeting scheduled for Thursday", "Report released today"]
        score = compute_compound_sentiment(headlines)
        assert score == 0.0

    def test_score_bounded(self):
        """Score is always in [-1.0, 1.0]."""
        positive = ["good great best success win strong growth improved"] * 10
        negative = ["bad worst crisis failure loss crash collapse"] * 10
        assert -1.0 <= compute_compound_sentiment(positive) <= 1.0
        assert -1.0 <= compute_compound_sentiment(negative) <= 1.0

    def test_negation_flips_sentiment(self):
        """Negation words reverse the sentiment of the following word."""
        positive = compute_compound_sentiment(["Economy shows good growth"])
        negated = compute_compound_sentiment(["Economy shows not good growth"])
        assert positive > 0.0
        assert negated < positive


class TestCoreClassifyFraming:
    """Test classify_framing from core.py."""

    def test_supportive(self):
        result = classify_framing(0.3)
        assert result.startswith("SUPPORTIVE")

    def test_critical(self):
        result = classify_framing(-0.3)
        assert result.startswith("CRITICAL")

    def test_neutral(self):
        result = classify_framing(0.0)
        assert result.startswith("NEUTRAL")

    def test_boundary_supportive(self):
        result = classify_framing(0.05)
        assert result.startswith("SUPPORTIVE")

    def test_boundary_critical(self):
        result = classify_framing(-0.05)
        assert result.startswith("CRITICAL")

    def test_just_below_supportive_threshold(self):
        result = classify_framing(0.049)
        assert result.startswith("NEUTRAL")

    def test_cwe_format(self):
        """Framing values use CWE triple format: CODE^Display^System."""
        result = classify_framing(0.5)
        parts = result.split("^")
        assert len(parts) == 3
        assert parts[2] == "FCK"


class TestCoreSelectTopSource:
    """Test select_top_source from core.py."""

    def test_empty_articles(self):
        assert select_top_source([], []) is None

    def test_selects_highest_credibility(self, sample_articles, sample_sources):
        result = select_top_source(sample_articles, sample_sources)
        assert result is not None
        name, url = result
        assert name == "Source C"
        assert url == "https://example.com/article2"

    def test_single_article(self, sample_sources):
        articles = [
            {
                "title": "Solo",
                "url": "https://example.com/solo",
                "source": {"id": "source-b", "name": "Source B"},
            }
        ]
        result = select_top_source(articles, sample_sources)
        assert result is not None
        name, url = result
        assert name == "Source B"

    def test_unknown_source_returns_fallback(self):
        articles = [
            {
                "title": "Unknown",
                "url": "https://example.com/unk",
                "source": {"id": "unknown-id", "name": "Unknown Src"},
            }
        ]
        sources = [{"id": "other", "name": "Other", "credibility_rank": 50}]
        result = select_top_source(articles, sources)
        assert result is not None
        name, url = result
        assert url == "https://example.com/unk"


# ---------------------------------------------------------------------------
# _Results accumulator tests
# ---------------------------------------------------------------------------


class TestResultsAccumulator:
    """Test the _Results dataclass."""

    def test_defaults(self):
        r = _Results()
        assert r.articles == []
        assert r.framing_cwe == "ABSENT^Not Covered^FCK"
        assert r.compound_score == 0.0
        assert r.top_source is None

    def test_mutable_articles(self):
        r = _Results()
        r.articles = [{"title": "Test"}]
        assert len(r.articles) == 1

    def test_independent_instances(self):
        r1 = _Results()
        r2 = _Results()
        r1.articles.append({"title": "Only R1"})
        assert len(r2.articles) == 0


# ---------------------------------------------------------------------------
# _build_tools tests
# ---------------------------------------------------------------------------


class TestBuildTools:
    """Test the tool factory function."""

    def test_returns_four_tools(self, sample_input, sample_sources):
        results = _Results()
        tools = _build_tools("left", sample_sources, sample_input, results)
        assert len(tools) == 4

    def test_tool_names(self, sample_input, sample_sources):
        results = _Results()
        tools = _build_tools("left", sample_sources, sample_input, results)
        names = {t.name for t in tools}
        assert names == {"build_query", "search_news", "detect_framing", "find_top_source"}

    def test_build_query_tool(self, sample_input, sample_sources):
        results = _Results()
        tools = _build_tools("left", sample_sources, sample_input, results)
        build_query = next(t for t in tools if t.name == "build_query")
        query = build_query.invoke({})
        assert isinstance(query, str)
        assert len(query) > 0
        # Stop words should be removed
        assert "the" not in query.split()

    def test_detect_framing_tool_no_articles(self, sample_input, sample_sources):
        results = _Results()
        tools = _build_tools("left", sample_sources, sample_input, results)
        detect = next(t for t in tools if t.name == "detect_framing")
        output = detect.invoke({})
        assert "ABSENT" in output
        assert results.framing_cwe == "ABSENT^Not Covered^FCK"

    def test_detect_framing_tool_with_articles(self, sample_input, sample_sources, sample_articles):
        results = _Results()
        results.articles = sample_articles
        tools = _build_tools("left", sample_sources, sample_input, results)
        detect = next(t for t in tools if t.name == "detect_framing")
        output = detect.invoke({})
        assert "Framing:" in output
        assert results.framing_cwe != "ABSENT^Not Covered^FCK"

    def test_find_top_source_tool_no_articles(self, sample_input, sample_sources):
        results = _Results()
        tools = _build_tools("left", sample_sources, sample_input, results)
        find = next(t for t in tools if t.name == "find_top_source")
        output = find.invoke({})
        assert "No articles" in output
        assert results.top_source is None

    def test_find_top_source_tool_with_articles(
        self, sample_input, sample_sources, sample_articles
    ):
        results = _Results()
        results.articles = sample_articles
        tools = _build_tools("left", sample_sources, sample_input, results)
        find = next(t for t in tools if t.name == "find_top_source")
        output = find.invoke({})
        assert "Top source:" in output
        assert results.top_source is not None
        assert results.top_source["name"] == "Source C"


# ---------------------------------------------------------------------------
# create_agent tests
# ---------------------------------------------------------------------------


class TestCreateAgent:
    """Test the agent construction factory."""

    def test_returns_invokable_graph(self, sample_input, sample_sources):
        results = _Results()
        agent = create_agent("left", sample_sources, sample_input, results)
        assert agent is not None
        assert hasattr(agent, "ainvoke")

    def test_parameterized_per_spectrum(self, sample_input, sample_sources):
        r1 = _Results()
        r2 = _Results()
        agent_left = create_agent("left", sample_sources, sample_input, r1)
        agent_right = create_agent("right", sample_sources, sample_input, r2)
        assert agent_left is not agent_right


# ---------------------------------------------------------------------------
# _publish_observations tests
# ---------------------------------------------------------------------------


class TestPublishObservations:
    """Test the _publish_observations helper."""

    async def test_publishes_article_count(self, ctx):
        results = _Results()
        results.articles = [{"title": "A1"}, {"title": "A2"}]
        await _publish_observations(results, ctx, "coverage-left")

        count_obs = [
            o for o in ctx.published_observations
            if o["code"] == ObservationCode.COVERAGE_ARTICLE_COUNT
        ]
        assert len(count_obs) == 1
        assert count_obs[0]["value"] == "2"
        assert count_obs[0]["value_type"] == ValueType.NM

    async def test_publishes_framing(self, ctx):
        results = _Results()
        results.framing_cwe = "SUPPORTIVE^Supportive^FCK"
        await _publish_observations(results, ctx, "coverage-center")

        framing_obs = [
            o for o in ctx.published_observations
            if o["code"] == ObservationCode.COVERAGE_FRAMING
        ]
        assert len(framing_obs) == 1
        assert framing_obs[0]["value"] == "SUPPORTIVE^Supportive^FCK"
        assert framing_obs[0]["value_type"] == ValueType.CWE

    async def test_publishes_top_source_when_present(self, ctx):
        results = _Results()
        results.top_source = {"name": "Reuters", "url": "https://reuters.com/art"}
        await _publish_observations(results, ctx, "coverage-right")

        source_obs = [
            o for o in ctx.published_observations
            if o["code"] == ObservationCode.COVERAGE_TOP_SOURCE
        ]
        url_obs = [
            o for o in ctx.published_observations
            if o["code"] == ObservationCode.COVERAGE_TOP_SOURCE_URL
        ]
        assert len(source_obs) == 1
        assert source_obs[0]["value"] == "Reuters"
        assert len(url_obs) == 1
        assert url_obs[0]["value"] == "https://reuters.com/art"

    async def test_no_top_source_observations_when_absent(self, ctx):
        results = _Results()
        results.top_source = None
        await _publish_observations(results, ctx, "coverage-left")

        top_codes = (
            ObservationCode.COVERAGE_TOP_SOURCE,
            ObservationCode.COVERAGE_TOP_SOURCE_URL,
        )
        source_obs = [
            o for o in ctx.published_observations
            if o["code"] in top_codes
        ]
        assert len(source_obs) == 0

    async def test_agent_name_propagated(self, ctx):
        results = _Results()
        await _publish_observations(results, ctx, "coverage-right")

        for obs in ctx.published_observations:
            assert obs["agent"] == "coverage-right"

    async def test_always_publishes_count_and_framing(self, ctx):
        """Article count and framing are always published, even with empty results."""
        results = _Results()
        await _publish_observations(results, ctx, "coverage-left")

        codes = [o["code"] for o in ctx.published_observations]
        assert ObservationCode.COVERAGE_ARTICLE_COUNT in codes
        assert ObservationCode.COVERAGE_FRAMING in codes


# ---------------------------------------------------------------------------
# run_coverage_agent() entry point tests
# ---------------------------------------------------------------------------


class TestRunCoverageAgent:
    """Test run_coverage_agent() with mocked LLM agent.

    run_coverage_agent() is the public API that the pipeline node wrapper calls.
    It creates a ReAct agent, invokes it, then publishes observations and
    returns CoverageOutput. We mock create_agent so no LLM calls are made.
    """

    def _patch_create_agent(self, articles=None, framing_cwe=None, top_source=None):
        """Return a patch context that replaces create_agent with a fake.

        The fake agent's ainvoke populates the _Results accumulator (which
        is created inside run_coverage_agent and passed to create_agent).
        """
        if articles is None:
            articles = []

        def fake_create_agent(spectrum, sources, input, results):
            async def fake_ainvoke(input_dict):
                results.articles = articles
                if framing_cwe:
                    results.framing_cwe = framing_cwe
                if top_source:
                    results.top_source = top_source
                return {"messages": []}

            agent = MagicMock()
            agent.ainvoke = AsyncMock(side_effect=fake_ainvoke)
            return agent

        return patch(
            "swarm_reasoning.agents.coverage.agent.create_agent",
            side_effect=fake_create_agent,
        )

    async def test_returns_coverage_output(self, ctx, sample_sources, sample_input):
        articles = [
            {
                "title": "Test Article",
                "url": "https://example.com/1",
                "source": {"id": "source-a", "name": "Source A"},
            }
        ]
        with self._patch_create_agent(
            articles=articles,
            framing_cwe="SUPPORTIVE^Supportive^FCK",
            top_source={"name": "Source A", "url": "https://example.com/1"},
        ):
            result = await run_coverage_agent("left", sample_sources, sample_input, ctx)

        assert result["framing"] == "SUPPORTIVE"
        assert len(result["articles"]) == 1
        assert result["articles"][0]["framing"] == "SUPPORTIVE"
        assert result["top_source"] == {"name": "Source A", "url": "https://example.com/1"}

    async def test_returns_empty_output_no_articles(self, ctx, sample_sources, sample_input):
        with self._patch_create_agent():
            result = await run_coverage_agent("center", sample_sources, sample_input, ctx)

        assert result["articles"] == []
        assert result["framing"] == "ABSENT"
        assert result["compound_score"] == 0.0
        assert result["top_source"] is None

    async def test_calls_heartbeat(self, ctx, sample_sources, sample_input):
        with self._patch_create_agent():
            await run_coverage_agent("left", sample_sources, sample_input, ctx)

        assert "coverage-left" in ctx.heartbeat_calls

    async def test_heartbeat_called_twice(self, ctx, sample_sources, sample_input):
        """Heartbeat at start and after agent invocation."""
        with self._patch_create_agent():
            await run_coverage_agent("right", sample_sources, sample_input, ctx)

        right_heartbeats = [h for h in ctx.heartbeat_calls if h == "coverage-right"]
        assert len(right_heartbeats) == 2

    async def test_publishes_progress_start(self, ctx, sample_sources, sample_input):
        with self._patch_create_agent():
            await run_coverage_agent("left", sample_sources, sample_input, ctx)

        messages = [p["message"] for p in ctx.published_progress]
        assert any("left-spectrum" in m.lower() or "left" in m.lower() for m in messages)

    async def test_publishes_progress_completion(self, ctx, sample_sources, sample_input):
        with self._patch_create_agent(
            articles=[{"title": "Art", "url": "https://x.com", "source": {"name": "S"}}],
            framing_cwe="NEUTRAL^Neutral^FCK",
        ):
            await run_coverage_agent("center", sample_sources, sample_input, ctx)

        messages = [p["message"] for p in ctx.published_progress]
        assert any("complete" in m.lower() for m in messages)

    async def test_completion_progress_includes_count(self, ctx, sample_sources, sample_input):
        articles = [
            {"title": f"Art {i}", "url": f"https://x.com/{i}", "source": {"name": "S"}}
            for i in range(3)
        ]
        with self._patch_create_agent(articles=articles, framing_cwe="NEUTRAL^Neutral^FCK"):
            await run_coverage_agent("left", sample_sources, sample_input, ctx)

        messages = [p["message"] for p in ctx.published_progress]
        completion_msg = [m for m in messages if "complete" in m.lower()]
        assert len(completion_msg) >= 1
        assert "3" in completion_msg[0]

    async def test_completion_progress_includes_top_source(self, ctx, sample_sources, sample_input):
        articles = [
            {"title": "Art", "url": "https://x.com/1", "source": {"name": "Reuters"}}
        ]
        with self._patch_create_agent(
            articles=articles,
            framing_cwe="NEUTRAL^Neutral^FCK",
            top_source={"name": "Reuters", "url": "https://x.com/1"},
        ):
            await run_coverage_agent("right", sample_sources, sample_input, ctx)

        messages = [p["message"] for p in ctx.published_progress]
        completion_msg = [m for m in messages if "complete" in m.lower()]
        assert any("Reuters" in m for m in completion_msg)

    async def test_publishes_observations(self, ctx, sample_sources, sample_input):
        with self._patch_create_agent(
            articles=[{"title": "A", "url": "u", "source": {"name": "S"}}],
            framing_cwe="SUPPORTIVE^Supportive^FCK",
            top_source={"name": "S", "url": "u"},
        ):
            await run_coverage_agent("left", sample_sources, sample_input, ctx)

        codes = [o["code"] for o in ctx.published_observations]
        assert ObservationCode.COVERAGE_ARTICLE_COUNT in codes
        assert ObservationCode.COVERAGE_FRAMING in codes
        assert ObservationCode.COVERAGE_TOP_SOURCE in codes
        assert ObservationCode.COVERAGE_TOP_SOURCE_URL in codes

    async def test_all_observations_have_correct_agent(self, ctx, sample_sources, sample_input):
        with self._patch_create_agent():
            await run_coverage_agent("center", sample_sources, sample_input, ctx)

        for obs in ctx.published_observations:
            assert obs["agent"] == "coverage-center"

    async def test_all_progress_has_correct_agent(self, ctx, sample_sources, sample_input):
        with self._patch_create_agent():
            await run_coverage_agent("right", sample_sources, sample_input, ctx)

        for progress in ctx.published_progress:
            assert progress["agent"] == "coverage-right"

    async def test_articles_include_framing_label(self, ctx, sample_sources, sample_input):
        articles = [
            {"title": "Art1", "url": "https://x.com/1", "source": {"id": "s", "name": "S"}},
            {"title": "Art2", "url": "https://x.com/2", "source": {"id": "s", "name": "S"}},
        ]
        with self._patch_create_agent(
            articles=articles, framing_cwe="CRITICAL^Critical^FCK"
        ):
            result = await run_coverage_agent("left", sample_sources, sample_input, ctx)

        for art in result["articles"]:
            assert art["framing"] == "CRITICAL"

    async def test_output_compound_score(self, ctx, sample_sources, sample_input):
        with self._patch_create_agent(framing_cwe="NEUTRAL^Neutral^FCK"):
            result = await run_coverage_agent("center", sample_sources, sample_input, ctx)

        assert isinstance(result["compound_score"], float)

    async def test_spectrum_parameterizes_agent_name(self, ctx, sample_sources, sample_input):
        """Each spectrum uses its own agent name for observations and progress."""
        for spectrum in ("left", "center", "right"):
            local_ctx = FakePipelineContext()
            with self._patch_create_agent():
                await run_coverage_agent(spectrum, sample_sources, sample_input, local_ctx)

            expected_agent = f"coverage-{spectrum}"
            assert expected_agent in local_ctx.heartbeat_calls
            for obs in local_ctx.published_observations:
                assert obs["agent"] == expected_agent
            for prog in local_ctx.published_progress:
                assert prog["agent"] == expected_agent


# ---------------------------------------------------------------------------
# Package re-export tests
# ---------------------------------------------------------------------------


class TestPackageReexports:
    """Test that the coverage package re-exports correctly."""

    def test_import_create_agent_from_package(self):
        from swarm_reasoning.agents.coverage import create_agent as ca
        assert callable(ca)

    def test_import_run_coverage_agent_from_package(self):
        from swarm_reasoning.agents.coverage import run_coverage_agent as rca
        assert callable(rca)

    def test_import_input_output_from_package(self):
        from swarm_reasoning.agents.coverage import CoverageInput, CoverageOutput
        assert CoverageInput is not None
        assert CoverageOutput is not None
