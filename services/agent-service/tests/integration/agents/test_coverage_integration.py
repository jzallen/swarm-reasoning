"""Integration tests for the coverage agent (sr-l0y.5.6).

Exercises run_coverage_agent() end-to-end with a capturing FakePipelineContext.
Unlike unit tests that test individual functions in isolation, these tests
invoke the complete coverage agent through its public entry point and verify:
  - Observation publishing (COVERAGE_ARTICLE_COUNT, COVERAGE_FRAMING,
    COVERAGE_TOP_SOURCE, COVERAGE_TOP_SOURCE_URL)
  - Progress event publishing (start + completion)
  - CoverageOutput contract (all fields, correct types)
  - Heartbeat signaling
  - Multiple scenarios (articles found, no articles, all spectrums)

The LLM agent (create_react_agent) is mocked to simulate tool invocations
without calling the Anthropic API. The observation publishing and output
construction run for real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.coverage.agent import run_coverage_agent
from swarm_reasoning.agents.coverage.models import CoverageInput
from swarm_reasoning.models.observation import ObservationCode

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class CapturingPipelineContext:
    """PipelineContext double that captures all side-effects for assertions."""

    run_id: str = "integ-cov-run"
    session_id: str = "integ-cov-sess"
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
    return CapturingPipelineContext()


@pytest.fixture
def sample_sources():
    return [
        {"id": "source-a", "name": "Source A", "credibility_rank": 80},
        {"id": "source-b", "name": "Source B", "credibility_rank": 60},
        {"id": "source-c", "name": "Source C", "credibility_rank": 90},
    ]


@pytest.fixture
def claim_input():
    return CoverageInput(normalized_claim="the unemployment rate dropped to 3.5% in 2024")


def _articles_with_sources():
    """Articles with source IDs matching sample_sources."""
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
        {
            "title": "Job market improvement continues",
            "url": "https://example.com/article3",
            "source": {"id": "source-b", "name": "Source B"},
        },
    ]


def _patch_agent(articles=None, framing_cwe=None, compound_score=None, top_source=None):
    """Patch create_agent to simulate tool results without LLM."""
    def fake_create_agent(spectrum, sources, input, results):
        async def fake_ainvoke(input_dict):
            results.articles = articles or []
            if framing_cwe is not None:
                results.framing_cwe = framing_cwe
            if compound_score is not None:
                results.compound_score = compound_score
            if top_source is not None:
                results.top_source = top_source
            return {"messages": []}

        agent = MagicMock()
        agent.ainvoke = AsyncMock(side_effect=fake_ainvoke)
        return agent

    return patch(
        "swarm_reasoning.agents.coverage.agent.create_agent",
        side_effect=fake_create_agent,
    )


# ---------------------------------------------------------------------------
# End-to-end run_coverage_agent() tests
# ---------------------------------------------------------------------------


class TestCoverageEndToEnd:
    """End-to-end tests for run_coverage_agent() with full observation publishing."""

    async def test_articles_found_produces_complete_output(self, ctx, sample_sources, claim_input):
        with _patch_agent(
            articles=_articles_with_sources(),
            framing_cwe="SUPPORTIVE^Supportive^FCK",
            compound_score=0.35,
            top_source={"name": "Source C", "url": "https://example.com/article2"},
        ):
            result = await run_coverage_agent("left", sample_sources, claim_input, ctx)

        assert result["framing"] == "SUPPORTIVE"
        assert len(result["articles"]) == 3
        assert result["compound_score"] == 0.35
        assert result["top_source"]["name"] == "Source C"

    async def test_no_articles_produces_absent_framing(self, ctx, sample_sources, claim_input):
        with _patch_agent():
            result = await run_coverage_agent("center", sample_sources, claim_input, ctx)

        assert result["framing"] == "ABSENT"
        assert result["articles"] == []
        assert result["compound_score"] == 0.0
        assert result["top_source"] is None

    async def test_all_spectrums_produce_valid_output(self, ctx, sample_sources, claim_input):
        """Each spectrum (left/center/right) produces well-formed output."""
        for spectrum in ("left", "center", "right"):
            local_ctx = CapturingPipelineContext()
            with _patch_agent(
                articles=_articles_with_sources(),
                framing_cwe="NEUTRAL^Neutral^FCK",
            ):
                result = await run_coverage_agent(spectrum, sample_sources, claim_input, local_ctx)

            assert "articles" in result
            assert "framing" in result
            assert "compound_score" in result
            assert "top_source" in result

    async def test_articles_enriched_with_framing_label(self, ctx, sample_sources, claim_input):
        with _patch_agent(
            articles=_articles_with_sources(),
            framing_cwe="CRITICAL^Critical^FCK",
        ):
            result = await run_coverage_agent("right", sample_sources, claim_input, ctx)

        for article in result["articles"]:
            assert "title" in article
            assert "url" in article
            assert "source" in article
            assert "framing" in article
            assert article["framing"] == "CRITICAL"


# ---------------------------------------------------------------------------
# Observation publishing verification
# ---------------------------------------------------------------------------


class TestObservationPublishing:
    """Verify correct observation codes published through run_coverage_agent()."""

    async def test_publishes_article_count(self, ctx, sample_sources, claim_input):
        with _patch_agent(articles=_articles_with_sources()):
            await run_coverage_agent("left", sample_sources, claim_input, ctx)

        codes = [o["code"] for o in ctx.published_observations]
        assert ObservationCode.COVERAGE_ARTICLE_COUNT in codes

    async def test_article_count_value_matches(self, ctx, sample_sources, claim_input):
        with _patch_agent(articles=_articles_with_sources()):
            await run_coverage_agent("center", sample_sources, claim_input, ctx)

        count_obs = [
            o for o in ctx.published_observations
            if o["code"] == ObservationCode.COVERAGE_ARTICLE_COUNT
        ]
        assert count_obs[0]["value"] == "3"

    async def test_publishes_framing(self, ctx, sample_sources, claim_input):
        with _patch_agent(framing_cwe="SUPPORTIVE^Supportive^FCK"):
            await run_coverage_agent("right", sample_sources, claim_input, ctx)

        framing_obs = [
            o for o in ctx.published_observations
            if o["code"] == ObservationCode.COVERAGE_FRAMING
        ]
        assert len(framing_obs) == 1
        assert framing_obs[0]["value"] == "SUPPORTIVE^Supportive^FCK"

    async def test_publishes_top_source_when_present(self, ctx, sample_sources, claim_input):
        with _patch_agent(
            articles=_articles_with_sources(),
            top_source={"name": "Source C", "url": "https://example.com/article2"},
        ):
            await run_coverage_agent("left", sample_sources, claim_input, ctx)

        codes = [o["code"] for o in ctx.published_observations]
        assert ObservationCode.COVERAGE_TOP_SOURCE in codes
        assert ObservationCode.COVERAGE_TOP_SOURCE_URL in codes

    async def test_no_top_source_observations_when_absent(self, ctx, sample_sources, claim_input):
        with _patch_agent():
            await run_coverage_agent("center", sample_sources, claim_input, ctx)

        codes = [o["code"] for o in ctx.published_observations]
        assert ObservationCode.COVERAGE_TOP_SOURCE not in codes
        assert ObservationCode.COVERAGE_TOP_SOURCE_URL not in codes

    async def test_all_observations_have_correct_agent(self, ctx, sample_sources, claim_input):
        with _patch_agent(articles=_articles_with_sources()):
            await run_coverage_agent("right", sample_sources, claim_input, ctx)

        for obs in ctx.published_observations:
            assert obs["agent"] == "coverage-right"

    async def test_zero_articles_count_observation(self, ctx, sample_sources, claim_input):
        with _patch_agent():
            await run_coverage_agent("left", sample_sources, claim_input, ctx)

        count_obs = [
            o for o in ctx.published_observations
            if o["code"] == ObservationCode.COVERAGE_ARTICLE_COUNT
        ]
        assert count_obs[0]["value"] == "0"


# ---------------------------------------------------------------------------
# Progress and heartbeat verification
# ---------------------------------------------------------------------------


class TestProgressAndHeartbeat:
    """Verify progress events and heartbeat signaling."""

    async def test_heartbeat_at_start_and_after_agent(self, ctx, sample_sources, claim_input):
        with _patch_agent():
            await run_coverage_agent("left", sample_sources, claim_input, ctx)

        left_heartbeats = [h for h in ctx.heartbeat_calls if h == "coverage-left"]
        assert len(left_heartbeats) == 2

    async def test_publishes_analyzing_progress(self, ctx, sample_sources, claim_input):
        with _patch_agent():
            await run_coverage_agent("center", sample_sources, claim_input, ctx)

        messages = [p["message"] for p in ctx.published_progress]
        assert any("center" in m.lower() for m in messages)

    async def test_publishes_completion_progress(self, ctx, sample_sources, claim_input):
        with _patch_agent(articles=_articles_with_sources()):
            await run_coverage_agent("right", sample_sources, claim_input, ctx)

        messages = [p["message"] for p in ctx.published_progress]
        assert any("complete" in m.lower() for m in messages)

    async def test_all_progress_from_correct_agent(self, ctx, sample_sources, claim_input):
        with _patch_agent():
            await run_coverage_agent("left", sample_sources, claim_input, ctx)

        for progress in ctx.published_progress:
            assert progress["agent"] == "coverage-left"

    async def test_completion_progress_mentions_framing(self, ctx, sample_sources, claim_input):
        with _patch_agent(
            articles=_articles_with_sources(),
            framing_cwe="CRITICAL^Critical^FCK",
        ):
            await run_coverage_agent("center", sample_sources, claim_input, ctx)

        messages = [p["message"] for p in ctx.published_progress]
        completion_msg = [m for m in messages if "complete" in m.lower()]
        assert any("CRITICAL" in m for m in completion_msg)


# ---------------------------------------------------------------------------
# Output contract verification
# ---------------------------------------------------------------------------


class TestOutputContract:
    """Verify CoverageOutput typed contract compliance."""

    async def test_all_output_fields_present(self, ctx, sample_sources, claim_input):
        with _patch_agent(articles=_articles_with_sources()):
            result = await run_coverage_agent("left", sample_sources, claim_input, ctx)

        assert "articles" in result
        assert "framing" in result
        assert "compound_score" in result
        assert "top_source" in result

    async def test_articles_structure(self, ctx, sample_sources, claim_input):
        with _patch_agent(
            articles=_articles_with_sources(),
            framing_cwe="NEUTRAL^Neutral^FCK",
        ):
            result = await run_coverage_agent("center", sample_sources, claim_input, ctx)

        for art in result["articles"]:
            assert "title" in art
            assert "url" in art
            assert "source" in art
            assert "framing" in art

    async def test_framing_is_label_not_cwe(self, ctx, sample_sources, claim_input):
        """CoverageOutput.framing is the label (SUPPORTIVE), not the full CWE triple."""
        with _patch_agent(framing_cwe="SUPPORTIVE^Supportive^FCK"):
            result = await run_coverage_agent("right", sample_sources, claim_input, ctx)

        assert result["framing"] == "SUPPORTIVE"
        assert "^" not in result["framing"]

    async def test_compound_score_is_float(self, ctx, sample_sources, claim_input):
        with _patch_agent(compound_score=0.42):
            result = await run_coverage_agent("left", sample_sources, claim_input, ctx)

        assert isinstance(result["compound_score"], float)

    async def test_top_source_dict_structure(self, ctx, sample_sources, claim_input):
        with _patch_agent(
            articles=_articles_with_sources(),
            top_source={"name": "Source C", "url": "https://example.com/article2"},
        ):
            result = await run_coverage_agent("center", sample_sources, claim_input, ctx)

        assert result["top_source"]["name"] == "Source C"
        assert result["top_source"]["url"] == "https://example.com/article2"

    async def test_empty_output_contract(self, ctx, sample_sources, claim_input):
        """No articles → all fields present with appropriate empty/None values."""
        with _patch_agent():
            result = await run_coverage_agent("right", sample_sources, claim_input, ctx)

        assert result["articles"] == []
        assert isinstance(result["framing"], str)
        assert isinstance(result["compound_score"], float)
        assert result["top_source"] is None
