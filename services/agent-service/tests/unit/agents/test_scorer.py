"""Unit tests for check-worthiness scorer."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from swarm_reasoning.agents.intake.tools.scorer import (
    CHECK_WORTHY_THRESHOLD,
    ScoreResult,
    is_check_worthy,
    score_claim_text,
)


def _mock_client(*responses: str) -> AsyncMock:
    """Create a mock AsyncAnthropic client returning the given response texts in order."""
    client = AsyncMock()
    side_effects = []
    for text in responses:
        resp = MagicMock()
        resp.content = [MagicMock(text=text)]
        side_effects.append(resp)
    client.messages.create = AsyncMock(side_effect=side_effects)
    return client


class TestThresholdLogic:
    def test_threshold_value(self):
        assert CHECK_WORTHY_THRESHOLD == 0.4

    def test_boundary_proceed(self):
        assert is_check_worthy(0.40) is True

    def test_boundary_cancel(self):
        assert is_check_worthy(0.39) is False

    def test_perfect_score(self):
        assert is_check_worthy(1.0) is True

    def test_zero_score(self):
        assert is_check_worthy(0.0) is False


class TestScoring:
    @pytest.mark.asyncio
    async def test_check_worthy_claim(self):
        """High-scoring factual claim should proceed."""
        resp = json.dumps({"score": 0.82, "rationale": "specific verifiable assertion"})
        client = _mock_client(resp, resp)  # pass1, pass2

        result = await score_claim_text("biden signed executive order 14042", client)

        assert isinstance(result, ScoreResult)
        assert result.score == 0.82
        assert result.proceed is True
        assert len(result.passes) == 2

    @pytest.mark.asyncio
    async def test_not_check_worthy(self):
        """Low-scoring opinion should not proceed."""
        resp = json.dumps({"score": 0.15, "rationale": "pure opinion"})
        client = _mock_client(resp, resp)

        result = await score_claim_text("politicians are all corrupt", client)

        assert result.score == 0.15
        assert result.proceed is False

    @pytest.mark.asyncio
    async def test_score_clamping_above(self):
        """Score > 1.0 should be clamped to 1.0."""
        resp = json.dumps({"score": 1.5, "rationale": "very check-worthy"})
        client = _mock_client(resp, resp)

        result = await score_claim_text("test claim", client)

        assert result.score == 1.0
        assert result.proceed is True

    @pytest.mark.asyncio
    async def test_score_clamping_below(self):
        """Score < 0.0 should be clamped to 0.0."""
        resp = json.dumps({"score": -0.5, "rationale": "not check-worthy"})
        client = _mock_client(resp, resp)

        result = await score_claim_text("test claim", client)

        assert result.score == 0.0
        assert result.proceed is False

    @pytest.mark.asyncio
    async def test_malformed_json_all_retries_exhausted(self):
        """After all retries, malformed responses yield score 0.0."""
        # 3 bad pass-1 responses (initial + 2 retries), then pass-2 never reached
        client = _mock_client(
            "not json at all",
            "still not json",
            '{"score": "high"}',  # score not parseable as float
            # pass-2 responses (needed if pass-1 succeeds)
        )

        result = await score_claim_text("test claim", client)

        assert result.score == 0.0
        assert "scorer_error" in result.rationale
        assert result.proceed is False

    @pytest.mark.asyncio
    async def test_malformed_then_valid(self):
        """First response malformed, retry succeeds."""
        bad_resp = "not json"
        good_resp = json.dumps({"score": 0.75, "rationale": "verifiable claim"})
        # pass1: bad -> good (2 calls), pass2: good (1 call)
        client = _mock_client(bad_resp, good_resp, good_resp)

        result = await score_claim_text("test claim", client)

        assert result.score == 0.75
        assert result.proceed is True

    @pytest.mark.asyncio
    async def test_self_consistency_divergent_uses_lower(self):
        """When pass1 and pass2 scores diverge > 0.1, use the lower score."""
        pass1 = json.dumps({"score": 0.80, "rationale": "high"})
        pass2 = json.dumps({"score": 0.45, "rationale": "revised down"})
        client = _mock_client(pass1, pass2)

        result = await score_claim_text("test claim", client)

        assert result.score == 0.45
        assert result.proceed is True
        assert result.passes == [0.80, 0.45]

    @pytest.mark.asyncio
    async def test_self_consistency_close_uses_pass1(self):
        """When pass1 and pass2 scores are within 0.1, use pass1 score."""
        pass1 = json.dumps({"score": 0.72, "rationale": "initial"})
        pass2 = json.dumps({"score": 0.68, "rationale": "confirmed"})
        client = _mock_client(pass1, pass2)

        result = await score_claim_text("test claim", client)

        assert result.score == 0.72
        assert result.passes == [0.72, 0.68]

    @pytest.mark.asyncio
    async def test_two_api_calls_made(self):
        """Scorer makes exactly 2 Claude API calls (pass1 + pass2)."""
        resp = json.dumps({"score": 0.60, "rationale": "test"})
        client = _mock_client(resp, resp)

        await score_claim_text("test claim", client)

        assert client.messages.create.call_count == 2
