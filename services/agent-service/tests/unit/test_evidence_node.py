"""Tests for evidence pipeline node (thin wrapper).

The evidence_node delegates to run_evidence_agent from agents/evidence.
These tests verify the PipelineState <-> EvidenceInput/EvidenceOutput
translation and the delegation contract.  Tool-level tests live in
the agents/evidence test suite.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.evidence.models import EvidenceOutput
from swarm_reasoning.pipeline.context import PipelineContext
from swarm_reasoning.pipeline.nodes.evidence import (
    AGENT_NAME,
    _apply_output,
    _extract_input,
    evidence_node,
)
from swarm_reasoning.pipeline.state import PipelineState


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
def mock_config(mock_ctx):
    """Create a mock RunnableConfig with PipelineContext."""
    return {"configurable": {"pipeline_context": mock_ctx}}


@pytest.fixture
def base_state() -> PipelineState:
    """Minimal valid PipelineState for evidence testing (post-intake)."""
    return {
        "claim_text": "The unemployment rate dropped to 3.5% in 2024",
        "run_id": "run-test",
        "session_id": "sess-test",
        "normalized_claim": "the unemployment rate dropped to 3.5% in 2024",
        "claim_domain": "ECONOMICS",
        "entities": {
            "persons": ["Joe Biden"],
            "orgs": ["BLS"],
            "dates": ["2024"],
            "locations": [],
            "statistics": ["3.5%"],
        },
        "observations": [],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# _extract_input tests
# ---------------------------------------------------------------------------


class TestExtractInput:
    """Tests for PipelineState -> EvidenceInput translation."""

    def test_extracts_normalized_claim(self, base_state):
        result = _extract_input(base_state)
        assert result["normalized_claim"] == "the unemployment rate dropped to 3.5% in 2024"

    def test_falls_back_to_claim_text(self):
        state: PipelineState = {
            "claim_text": "original claim",
            "run_id": "r",
            "session_id": "s",
            "observations": [],
            "errors": [],
        }
        result = _extract_input(state)
        assert result["normalized_claim"] == "original claim"

    def test_extracts_claim_domain(self, base_state):
        result = _extract_input(base_state)
        assert result["claim_domain"] == "ECONOMICS"

    def test_domain_defaults_to_other(self):
        state: PipelineState = {
            "claim_text": "some claim",
            "run_id": "r",
            "session_id": "s",
            "observations": [],
            "errors": [],
        }
        result = _extract_input(state)
        assert result["claim_domain"] == "OTHER"

    def test_extracts_persons(self, base_state):
        result = _extract_input(base_state)
        assert result["persons"] == ["Joe Biden"]

    def test_extracts_organizations(self, base_state):
        result = _extract_input(base_state)
        assert result["organizations"] == ["BLS"]

    def test_empty_entities(self):
        state: PipelineState = {
            "claim_text": "claim",
            "run_id": "r",
            "session_id": "s",
            "entities": {},
            "observations": [],
            "errors": [],
        }
        result = _extract_input(state)
        assert result["persons"] == []
        assert result["organizations"] == []

    def test_missing_entities(self):
        state: PipelineState = {
            "claim_text": "claim",
            "run_id": "r",
            "session_id": "s",
            "observations": [],
            "errors": [],
        }
        result = _extract_input(state)
        assert result["persons"] == []
        assert result["organizations"] == []


# ---------------------------------------------------------------------------
# _apply_output tests
# ---------------------------------------------------------------------------


class TestApplyOutput:
    """Tests for EvidenceOutput -> PipelineState update translation."""

    def test_maps_all_fields(self):
        output = EvidenceOutput(
            claimreview_matches=[{"source": "PolitiFact", "rating": "True", "url": "u", "score": 0.9}],
            domain_sources=[{"name": "CDC", "url": "u", "alignment": "SUPPORTS", "confidence": 0.85}],
            evidence_confidence=0.85,
        )
        result = _apply_output(output)
        assert result["claimreview_matches"] == output["claimreview_matches"]
        assert result["domain_sources"] == output["domain_sources"]
        assert result["evidence_confidence"] == 0.85

    def test_empty_output(self):
        output = EvidenceOutput(
            claimreview_matches=[],
            domain_sources=[],
            evidence_confidence=0.0,
        )
        result = _apply_output(output)
        assert result["claimreview_matches"] == []
        assert result["domain_sources"] == []
        assert result["evidence_confidence"] == 0.0

    def test_returns_exactly_three_keys(self):
        output = EvidenceOutput(
            claimreview_matches=[],
            domain_sources=[],
            evidence_confidence=0.0,
        )
        result = _apply_output(output)
        assert set(result.keys()) == {"claimreview_matches", "domain_sources", "evidence_confidence"}


# ---------------------------------------------------------------------------
# evidence_node integration tests
# ---------------------------------------------------------------------------


class TestEvidenceNode:
    """Integration tests for the evidence_node wrapper."""

    @pytest.mark.asyncio
    async def test_delegates_to_run_evidence_agent(self, mock_config, mock_ctx, base_state):
        """Node calls run_evidence_agent with correct EvidenceInput and ctx."""
        expected_output = EvidenceOutput(
            claimreview_matches=[{"source": "Snopes", "rating": "True", "url": "u", "score": 0.8}],
            domain_sources=[{"name": "WHO", "url": "u", "alignment": "SUPPORTS", "confidence": 0.9}],
            evidence_confidence=0.9,
        )
        with patch(
            "swarm_reasoning.pipeline.nodes.evidence.run_evidence_agent",
            new_callable=AsyncMock,
            return_value=expected_output,
        ) as mock_agent:
            result = await evidence_node(base_state, mock_config)

        mock_agent.assert_called_once()
        call_input, call_ctx = mock_agent.call_args.args
        assert call_input["normalized_claim"] == "the unemployment rate dropped to 3.5% in 2024"
        assert call_input["claim_domain"] == "ECONOMICS"
        assert call_input["persons"] == ["Joe Biden"]
        assert call_input["organizations"] == ["BLS"]
        assert call_ctx is mock_ctx

    @pytest.mark.asyncio
    async def test_returns_translated_output(self, mock_config, mock_ctx, base_state):
        """Node returns EvidenceOutput fields as PipelineState updates."""
        expected_output = EvidenceOutput(
            claimreview_matches=[{"source": "PolitiFact", "rating": "True", "url": "u", "score": 0.85}],
            domain_sources=[{"name": "CDC", "url": "u", "alignment": "SUPPORTS", "confidence": 0.9}],
            evidence_confidence=0.9,
        )
        with patch(
            "swarm_reasoning.pipeline.nodes.evidence.run_evidence_agent",
            new_callable=AsyncMock,
            return_value=expected_output,
        ):
            result = await evidence_node(base_state, mock_config)

        assert result["claimreview_matches"] == expected_output["claimreview_matches"]
        assert result["domain_sources"] == expected_output["domain_sources"]
        assert result["evidence_confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_sends_heartbeat(self, mock_config, mock_ctx, base_state):
        """Node sends a heartbeat before invoking the agent."""
        with patch(
            "swarm_reasoning.pipeline.nodes.evidence.run_evidence_agent",
            new_callable=AsyncMock,
            return_value=EvidenceOutput(
                claimreview_matches=[], domain_sources=[], evidence_confidence=0.0,
            ),
        ):
            await evidence_node(base_state, mock_config)

        mock_ctx.heartbeat.assert_called_with(AGENT_NAME)

    @pytest.mark.asyncio
    async def test_agent_name_is_evidence(self):
        assert AGENT_NAME == "evidence"
