"""Unit tests for claim-detector @tool definitions."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from anthropic import AsyncAnthropic

from swarm_reasoning.agents.claim_detector.tools.normalize import normalize_claim
from swarm_reasoning.agents.claim_detector.tools.score import score_check_worthiness
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType


def _make_context() -> AgentContext:
    """Build a mock AgentContext for tool testing."""
    stream = AsyncMock()
    redis_client = AsyncMock()
    ctx = AgentContext(
        stream=stream,
        redis_client=redis_client,
        run_id="run-test-001",
        sk="reasoning:run-test-001:claim-detector",
        agent_name="claim-detector",
    )
    ctx.publish_obs = AsyncMock()
    return ctx


def _mock_anthropic_client(score: float = 0.82, rationale: str = "Verifiable claim") -> AsyncMock:
    """Build a mock Anthropic client returning a fixed score response."""
    mock_response = MagicMock()
    mock_response.content = [
        MagicMock(text=json.dumps({"score": score, "rationale": rationale}))
    ]
    mock_client = AsyncMock(spec=AsyncAnthropic)
    mock_client.messages.create = AsyncMock(return_value=mock_response)
    return mock_client


class TestNormalizeClaim:
    @pytest.mark.asyncio
    async def test_normalizes_and_publishes_observation(self):
        ctx = _make_context()
        result = await normalize_claim.ainvoke(
            {"claim_text": "Biden REPORTEDLY signed an order", "context": ctx}
        )

        assert "reportedly" not in result
        assert "biden" in result.lower()

        ctx.publish_obs.assert_called_once()
        call_kwargs = ctx.publish_obs.call_args[1]
        assert call_kwargs["code"] == ObservationCode.CLAIM_NORMALIZED
        assert call_kwargs["value_type"] == ValueType.ST
        assert call_kwargs["status"] == "F"
        assert call_kwargs["method"] == "normalize_claim"

    @pytest.mark.asyncio
    async def test_fallback_note_on_empty_normalization(self):
        ctx = _make_context()
        # "reportedly" by itself normalizes to empty, triggering fallback
        result = await normalize_claim.ainvoke(
            {"claim_text": "reportedly", "context": ctx}
        )

        assert result  # Should return fallback text
        call_kwargs = ctx.publish_obs.call_args[1]
        assert "fallback" in (call_kwargs["note"] or "")

    @pytest.mark.asyncio
    async def test_pronoun_resolution_with_entities(self):
        ctx = _make_context()
        result = await normalize_claim.ainvoke(
            {
                "claim_text": "He signed an executive order",
                "entity_persons": ["Biden"],
                "context": ctx,
            }
        )

        assert "biden" in result.lower()

    @pytest.mark.asyncio
    async def test_hedge_removal_noted(self):
        ctx = _make_context()
        await normalize_claim.ainvoke(
            {"claim_text": "Sources say the deficit will increase", "context": ctx}
        )

        call_kwargs = ctx.publish_obs.call_args[1]
        assert call_kwargs["note"] is not None
        assert "hedges removed" in call_kwargs["note"]


class TestScoreCheckWorthiness:
    @pytest.mark.asyncio
    async def test_publishes_preliminary_and_final_scores(self):
        ctx = _make_context()
        mock_client = _mock_anthropic_client(score=0.82)

        result_str = await score_check_worthiness.ainvoke(
            {
                "normalized_text": "biden signed executive order 14042",
                "context": ctx,
                "anthropic_client": mock_client,
            }
        )

        result = json.loads(result_str)
        assert result["score"] == 0.82
        assert result["proceed"] is True
        assert result["threshold"] == 0.4

        # Should have published both P and F observations
        assert ctx.publish_obs.call_count == 2
        first_call = ctx.publish_obs.call_args_list[0][1]
        assert first_call["status"] == "P"
        assert first_call["code"] == ObservationCode.CHECK_WORTHY_SCORE
        assert first_call["units"] == "score"
        assert first_call["reference_range"] == "0.0-1.0"

        second_call = ctx.publish_obs.call_args_list[1][1]
        assert second_call["status"] == "F"
        assert second_call["code"] == ObservationCode.CHECK_WORTHY_SCORE

    @pytest.mark.asyncio
    async def test_below_threshold_returns_proceed_false(self):
        ctx = _make_context()
        mock_client = _mock_anthropic_client(score=0.2, rationale="Opinion statement")

        result_str = await score_check_worthiness.ainvoke(
            {
                "normalized_text": "politicians are all corrupt",
                "context": ctx,
                "anthropic_client": mock_client,
            }
        )

        result = json.loads(result_str)
        assert result["score"] == 0.2
        assert result["proceed"] is False

    @pytest.mark.asyncio
    async def test_missing_api_key_raises_when_no_client(self):
        ctx = _make_context()

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(Exception, match="ANTHROPIC_API_KEY"):
                await score_check_worthiness.ainvoke(
                    {"normalized_text": "test claim", "context": ctx}
                )

    @pytest.mark.asyncio
    async def test_env_fallback_when_no_client_injected(self):
        ctx = _make_context()

        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(text=json.dumps({"score": 0.7, "rationale": "test"}))
        ]

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            with patch(
                "swarm_reasoning.agents.claim_detector.tools.score.AsyncAnthropic"
            ) as mock_anthropic:
                mock_client = AsyncMock()
                mock_client.messages.create = AsyncMock(return_value=mock_response)
                mock_anthropic.return_value = mock_client

                result_str = await score_check_worthiness.ainvoke(
                    {"normalized_text": "test claim", "context": ctx}
                )

        result = json.loads(result_str)
        assert result["score"] == 0.7
