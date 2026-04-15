"""Unit tests for the evidence ReAct agent (agents/evidence/agent.py).

Tests cover:
- run_evidence_agent: delegation to LLM agent, result accumulation, output format
- _publish_claimreview_observations: observation publishing with/without matches
- _publish_domain_observations: observation publishing with/without sources
- _Results accumulator behavior
- _build_tools: tool list construction
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.evidence.agent import (
    AGENT_NAME,
    _build_tools,
    _publish_claimreview_observations,
    _publish_domain_observations,
    _Results,
    run_evidence_agent,
)
from swarm_reasoning.agents.evidence.models import EvidenceInput
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext


def _find_obs(calls, code: ObservationCode):
    """Find the first publish_observation call matching the given code."""
    return next(c for c in calls if c.kwargs["code"] == code)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ctx():
    """Create a mock PipelineContext."""
    ctx = MagicMock(spec=PipelineContext)
    ctx.run_id = "run-test"
    ctx.session_id = "sess-test"
    ctx.redis_client = AsyncMock()
    ctx.publish_observation = AsyncMock()
    ctx.publish_progress = AsyncMock()
    ctx.heartbeat = MagicMock()
    return ctx


@pytest.fixture
def base_input() -> EvidenceInput:
    """Standard EvidenceInput for testing."""
    return EvidenceInput(
        normalized_claim="the unemployment rate dropped to 3.5% in 2024",
        claim_domain="ECONOMICS",
        persons=["Joe Biden"],
        organizations=["BLS"],
    )


@pytest.fixture
def matched_results() -> _Results:
    """Results with ClaimReview match and domain source."""
    r = _Results()
    r.claimreview_matches = [{
        "source": "PolitiFact", "rating": "Mostly True",
        "url": "https://politifact.com/1", "score": 0.85,
    }]
    r.domain_sources = [{
        "name": "BLS", "url": "https://bls.gov/search?q=test",
        "alignment": "SUPPORTS", "confidence": 0.90,
    }]
    r.best_confidence = 0.90
    return r


@pytest.fixture
def empty_results() -> _Results:
    """Results with no matches and no sources."""
    return _Results()


# ---------------------------------------------------------------------------
# _Results accumulator
# ---------------------------------------------------------------------------


class TestResults:
    """Tests for the _Results dataclass."""

    def test_defaults_empty(self):
        r = _Results()
        assert r.claimreview_matches == []
        assert r.domain_sources == []
        assert r.best_confidence == 0.0

    def test_accumulates_matches(self):
        r = _Results()
        r.claimreview_matches.append(
            {"source": "Snopes", "rating": "True", "url": "u", "score": 0.9}
        )
        assert len(r.claimreview_matches) == 1

    def test_independent_instances(self):
        r1 = _Results()
        r2 = _Results()
        r1.claimreview_matches.append({"x": 1})
        assert len(r2.claimreview_matches) == 0


# ---------------------------------------------------------------------------
# _build_tools
# ---------------------------------------------------------------------------


class TestBuildTools:
    """Tests for LangChain tool construction."""

    def test_returns_four_tools(self, base_input):
        tools = _build_tools(base_input, _Results())
        assert len(tools) == 4

    def test_tool_names(self, base_input):
        tools = _build_tools(base_input, _Results())
        names = {t.name for t in tools}
        expected = {
            "search_factchecks", "lookup_domain_sources",
            "fetch_source_content", "score_evidence",
        }
        assert names == expected

    def test_tools_have_invoke_method(self, base_input):
        results = _Results()
        tools = _build_tools(base_input, results)
        # LangChain tools are StructuredTool objects with invoke/ainvoke
        for tool in tools:
            assert hasattr(tool, "invoke") or hasattr(tool, "ainvoke")


# ---------------------------------------------------------------------------
# _publish_claimreview_observations — with matches
# ---------------------------------------------------------------------------


class TestPublishClaimreviewObservationsWithMatches:
    """Observation publishing when ClaimReview matches exist."""

    async def test_publishes_five_observations(self, mock_ctx, matched_results):
        await _publish_claimreview_observations(matched_results, mock_ctx)
        assert mock_ctx.publish_observation.call_count == 5

    async def test_publishes_match_true(self, mock_ctx, matched_results):
        await _publish_claimreview_observations(matched_results, mock_ctx)
        calls = mock_ctx.publish_observation.call_args_list
        match_call = _find_obs(calls, ObservationCode.CLAIMREVIEW_MATCH)
        assert "TRUE" in match_call.kwargs["value"]
        assert match_call.kwargs["value_type"] == ValueType.CWE

    async def test_publishes_verdict(self, mock_ctx, matched_results):
        await _publish_claimreview_observations(matched_results, mock_ctx)
        calls = mock_ctx.publish_observation.call_args_list
        verdict_call = _find_obs(calls, ObservationCode.CLAIMREVIEW_VERDICT)
        assert "MOSTLY_TRUE" in verdict_call.kwargs["value"]

    async def test_publishes_source(self, mock_ctx, matched_results):
        await _publish_claimreview_observations(matched_results, mock_ctx)
        calls = mock_ctx.publish_observation.call_args_list
        source_call = _find_obs(calls, ObservationCode.CLAIMREVIEW_SOURCE)
        assert source_call.kwargs["value"] == "PolitiFact"

    async def test_publishes_url(self, mock_ctx, matched_results):
        await _publish_claimreview_observations(matched_results, mock_ctx)
        calls = mock_ctx.publish_observation.call_args_list
        url_call = _find_obs(calls, ObservationCode.CLAIMREVIEW_URL)
        assert url_call.kwargs["value"] == "https://politifact.com/1"

    async def test_publishes_match_score(self, mock_ctx, matched_results):
        await _publish_claimreview_observations(matched_results, mock_ctx)
        calls = mock_ctx.publish_observation.call_args_list
        score_call = _find_obs(calls, ObservationCode.CLAIMREVIEW_MATCH_SCORE)
        assert score_call.kwargs["value"] == "0.85"
        assert score_call.kwargs["value_type"] == ValueType.NM

    async def test_all_observations_use_evidence_agent(self, mock_ctx, matched_results):
        await _publish_claimreview_observations(matched_results, mock_ctx)
        for call in mock_ctx.publish_observation.call_args_list:
            assert call.kwargs["agent"] == "evidence"


# ---------------------------------------------------------------------------
# _publish_claimreview_observations — no matches
# ---------------------------------------------------------------------------


class TestPublishClaimreviewObservationsNoMatches:
    """Observation publishing when no ClaimReview matches found."""

    async def test_publishes_two_observations(self, mock_ctx, empty_results):
        await _publish_claimreview_observations(empty_results, mock_ctx)
        assert mock_ctx.publish_observation.call_count == 2

    async def test_publishes_match_false(self, mock_ctx, empty_results):
        await _publish_claimreview_observations(empty_results, mock_ctx)
        calls = mock_ctx.publish_observation.call_args_list
        match_call = _find_obs(calls, ObservationCode.CLAIMREVIEW_MATCH)
        assert "FALSE" in match_call.kwargs["value"]

    async def test_publishes_zero_score(self, mock_ctx, empty_results):
        await _publish_claimreview_observations(empty_results, mock_ctx)
        calls = mock_ctx.publish_observation.call_args_list
        score_call = _find_obs(calls, ObservationCode.CLAIMREVIEW_MATCH_SCORE)
        assert score_call.kwargs["value"] == "0.0"


# ---------------------------------------------------------------------------
# _publish_domain_observations — with sources
# ---------------------------------------------------------------------------


class TestPublishDomainObservationsWithSources:
    """Observation publishing when domain sources exist."""

    async def test_publishes_four_observations(self, mock_ctx, matched_results):
        await _publish_domain_observations(matched_results, mock_ctx)
        assert mock_ctx.publish_observation.call_count == 4

    async def test_publishes_source_name(self, mock_ctx, matched_results):
        await _publish_domain_observations(matched_results, mock_ctx)
        calls = mock_ctx.publish_observation.call_args_list
        name_call = _find_obs(calls, ObservationCode.DOMAIN_SOURCE_NAME)
        assert name_call.kwargs["value"] == "BLS"

    async def test_publishes_source_url(self, mock_ctx, matched_results):
        await _publish_domain_observations(matched_results, mock_ctx)
        calls = mock_ctx.publish_observation.call_args_list
        url_call = _find_obs(calls, ObservationCode.DOMAIN_SOURCE_URL)
        assert url_call.kwargs["value"] == "https://bls.gov/search?q=test"

    async def test_publishes_alignment(self, mock_ctx, matched_results):
        await _publish_domain_observations(matched_results, mock_ctx)
        calls = mock_ctx.publish_observation.call_args_list
        align_call = _find_obs(calls, ObservationCode.DOMAIN_EVIDENCE_ALIGNMENT)
        assert "SUPPORTS" in align_call.kwargs["value"]
        assert align_call.kwargs["value_type"] == ValueType.CWE

    async def test_publishes_confidence(self, mock_ctx, matched_results):
        await _publish_domain_observations(matched_results, mock_ctx)
        calls = mock_ctx.publish_observation.call_args_list
        conf_call = _find_obs(calls, ObservationCode.DOMAIN_CONFIDENCE)
        assert conf_call.kwargs["value"] == "0.90"
        assert conf_call.kwargs["value_type"] == ValueType.NM

    async def test_all_observations_use_evidence_agent(self, mock_ctx, matched_results):
        await _publish_domain_observations(matched_results, mock_ctx)
        for call in mock_ctx.publish_observation.call_args_list:
            assert call.kwargs["agent"] == "evidence"


# ---------------------------------------------------------------------------
# _publish_domain_observations — no sources
# ---------------------------------------------------------------------------


class TestPublishDomainObservationsNoSources:
    """Observation publishing when no domain sources found."""

    async def test_publishes_four_observations(self, mock_ctx, empty_results):
        await _publish_domain_observations(empty_results, mock_ctx)
        assert mock_ctx.publish_observation.call_count == 4

    async def test_source_name_na(self, mock_ctx, empty_results):
        await _publish_domain_observations(empty_results, mock_ctx)
        calls = mock_ctx.publish_observation.call_args_list
        name_call = _find_obs(calls, ObservationCode.DOMAIN_SOURCE_NAME)
        assert name_call.kwargs["value"] == "N/A"

    async def test_source_url_na(self, mock_ctx, empty_results):
        await _publish_domain_observations(empty_results, mock_ctx)
        calls = mock_ctx.publish_observation.call_args_list
        url_call = _find_obs(calls, ObservationCode.DOMAIN_SOURCE_URL)
        assert url_call.kwargs["value"] == "N/A"

    async def test_alignment_absent(self, mock_ctx, empty_results):
        await _publish_domain_observations(empty_results, mock_ctx)
        calls = mock_ctx.publish_observation.call_args_list
        align_call = _find_obs(calls, ObservationCode.DOMAIN_EVIDENCE_ALIGNMENT)
        assert "ABSENT" in align_call.kwargs["value"]

    async def test_confidence_zero(self, mock_ctx, empty_results):
        await _publish_domain_observations(empty_results, mock_ctx)
        calls = mock_ctx.publish_observation.call_args_list
        conf_call = _find_obs(calls, ObservationCode.DOMAIN_CONFIDENCE)
        assert conf_call.kwargs["value"] == "0.00"


# ---------------------------------------------------------------------------
# run_evidence_agent — full integration (mocked LLM)
# ---------------------------------------------------------------------------


class TestRunEvidenceAgent:
    """Integration tests for run_evidence_agent with mocked LLM."""

    async def test_returns_evidence_output(self, mock_ctx, base_input):
        mock_agent = AsyncMock()
        mock_agent.ainvoke = AsyncMock(return_value={"messages": []})
        with patch(
            "swarm_reasoning.agents.evidence.agent.build_evidence_agent",
            return_value=mock_agent,
        ):
            result = await run_evidence_agent(base_input, mock_ctx)
        assert isinstance(result, dict)
        assert "claimreview_matches" in result
        assert "domain_sources" in result
        assert "evidence_confidence" in result

    async def test_sends_heartbeats(self, mock_ctx, base_input):
        mock_agent = AsyncMock()
        mock_agent.ainvoke = AsyncMock(return_value={"messages": []})
        with patch(
            "swarm_reasoning.agents.evidence.agent.build_evidence_agent",
            return_value=mock_agent,
        ):
            await run_evidence_agent(base_input, mock_ctx)
        # Should heartbeat at start and after agent completes
        assert mock_ctx.heartbeat.call_count >= 2
        mock_ctx.heartbeat.assert_any_call(AGENT_NAME)

    async def test_publishes_progress_messages(self, mock_ctx, base_input):
        mock_agent = AsyncMock()
        mock_agent.ainvoke = AsyncMock(return_value={"messages": []})
        with patch(
            "swarm_reasoning.agents.evidence.agent.build_evidence_agent",
            return_value=mock_agent,
        ):
            await run_evidence_agent(base_input, mock_ctx)
        progress_calls = [call.args[1] for call in mock_ctx.publish_progress.call_args_list]
        assert any("Gathering evidence" in msg for msg in progress_calls)
        assert any("Evidence complete" in msg for msg in progress_calls)

    async def test_empty_results_when_no_tools_invoked(self, mock_ctx, base_input):
        mock_agent = AsyncMock()
        mock_agent.ainvoke = AsyncMock(return_value={"messages": []})
        with patch(
            "swarm_reasoning.agents.evidence.agent.build_evidence_agent",
            return_value=mock_agent,
        ):
            result = await run_evidence_agent(base_input, mock_ctx)
        assert result["claimreview_matches"] == []
        assert result["domain_sources"] == []
        assert result["evidence_confidence"] == 0.0

    async def test_publishes_claimreview_and_domain_observations(self, mock_ctx, base_input):
        mock_agent = AsyncMock()
        mock_agent.ainvoke = AsyncMock(return_value={"messages": []})
        with patch(
            "swarm_reasoning.agents.evidence.agent.build_evidence_agent",
            return_value=mock_agent,
        ):
            await run_evidence_agent(base_input, mock_ctx)
        # With empty results: 2 claimreview obs + 4 domain obs = 6
        assert mock_ctx.publish_observation.call_count == 6

    async def test_agent_name_is_evidence(self):
        assert AGENT_NAME == "evidence"

    async def test_invokes_agent_with_claim_message(self, mock_ctx, base_input):
        mock_agent = AsyncMock()
        mock_agent.ainvoke = AsyncMock(return_value={"messages": []})
        with patch(
            "swarm_reasoning.agents.evidence.agent.build_evidence_agent",
            return_value=mock_agent,
        ):
            await run_evidence_agent(base_input, mock_ctx)
        call_args = mock_agent.ainvoke.call_args
        messages = call_args.args[0]["messages"]
        assert len(messages) == 1
        msg_content = messages[0].content
        assert "unemployment rate" in msg_content
        assert "ECONOMICS" in msg_content
        assert "Joe Biden" in msg_content
        assert "BLS" in msg_content


# ---------------------------------------------------------------------------
# Module exports
# ---------------------------------------------------------------------------


class TestModuleExports:
    """Tests for the evidence __init__.py re-exports."""

    def test_imports_from_package(self):
        import swarm_reasoning.agents.evidence as ev

        assert ev.AGENT_NAME == "evidence"
        assert ev.EvidenceInput is not None
        assert ev.EvidenceOutput is not None
        assert callable(ev.build_evidence_agent)
        assert callable(ev.run_evidence_agent)
