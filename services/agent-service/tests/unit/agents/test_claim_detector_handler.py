"""Unit tests for ClaimDetectorHandler."""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from anthropic import AsyncAnthropic

from swarm_reasoning.activities.run_agent import AgentActivityInput
from swarm_reasoning.agents._utils import StreamNotFoundError
from swarm_reasoning.agents.claim_detector.handler import (
    AGENT_NAME,
    ClaimDetectorHandler,
)
from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType
from swarm_reasoning.models.stream import ObsMessage, StartMessage, StopMessage

_MODULE = "swarm_reasoning.agents.claim_detector.handler"
_RUN_ID = "run-001"


def _make_input(run_id: str = _RUN_ID, claim_text: str = "Test claim") -> AgentActivityInput:
    return AgentActivityInput(
        run_id=run_id,
        claim_text=claim_text,
        agent_name="claim-detector",
        phase="ingestion",
    )


def _mock_ingestion_stream(
    claim_text: str = "Biden signed executive order 14042.",
    run_id: str = _RUN_ID,
) -> list:
    """Build a mock ingestion stream read_range response."""
    return [
        MagicMock(type="START"),
        ObsMessage(
            observation=Observation(
                runId=run_id,
                agent="ingestion-agent",
                seq=1,
                code=ObservationCode.CLAIM_TEXT,
                value=claim_text,
                valueType=ValueType.ST,
                status="F",
                timestamp="2026-04-10T12:00:00Z",
                method="ingest_claim",
            )
        ),
        MagicMock(type="STOP"),
    ]


def _mock_claude_response(score: float, rationale: str = "test rationale") -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps({"score": score, "rationale": rationale}))]
    return resp


def _build_handler_mocks(
    ingestion_messages: list | None = None,
    claude_score: float = 0.82,
):
    """Build mocked stream, redis, anthropic for handler construction."""
    stream_mock = AsyncMock()
    stream_mock.read_range.return_value = ingestion_messages or _mock_ingestion_stream()
    stream_mock.publish = AsyncMock()
    stream_mock.close = AsyncMock()

    redis_mock = AsyncMock()
    redis_mock.xadd = AsyncMock()
    redis_mock.aclose = AsyncMock()

    anthropic_mock = AsyncMock(spec=AsyncAnthropic)
    resp = _mock_claude_response(claude_score)
    anthropic_mock.messages.create = AsyncMock(return_value=resp)

    return stream_mock, redis_mock, anthropic_mock


@contextmanager
def _patched_handler(stream, redis, anthropic):
    """Patch handler dependencies and yield a ready-to-use handler."""
    with (
        patch(f"{_MODULE}.RedisReasoningStream", return_value=stream),
        patch(f"{_MODULE}.aioredis.Redis", return_value=redis),
        patch(f"{_MODULE}.AsyncAnthropic", return_value=anthropic),
        patch(f"{_MODULE}.activity"),
    ):
        yield ClaimDetectorHandler(anthropic_api_key="test-key")


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_check_worthy_claim_returns_f_status(self):
        stream, redis, anthropic = _build_handler_mocks(claude_score=0.82)

        with _patched_handler(stream, redis, anthropic) as handler:
            result = await handler.run(_make_input())

        assert result.terminal_status == "F"
        assert result.observation_count == 3
        assert result.check_worthiness_score == 0.82
        assert result.agent_name == "claim-detector"

    @pytest.mark.asyncio
    async def test_stream_publishes_correct_sequence(self):
        stream, redis, anthropic = _build_handler_mocks(claude_score=0.75)

        with _patched_handler(stream, redis, anthropic) as handler:
            await handler.run(_make_input())

        # Expect: START, CLAIM_NORMALIZED, CHECK_WORTHY_SCORE(P), CHECK_WORTHY_SCORE(F), STOP
        calls = stream.publish.call_args_list
        assert len(calls) == 5

        # START
        start_msg = calls[0][0][1]
        assert isinstance(start_msg, StartMessage)
        assert start_msg.agent == AGENT_NAME

        # CLAIM_NORMALIZED (seq=1, F)
        norm_msg = calls[1][0][1]
        assert isinstance(norm_msg, ObsMessage)
        assert norm_msg.observation.code == ObservationCode.CLAIM_NORMALIZED
        assert norm_msg.observation.seq == 1
        assert norm_msg.observation.status == "F"

        # CHECK_WORTHY_SCORE (seq=2, P)
        score_p = calls[2][0][1]
        assert isinstance(score_p, ObsMessage)
        assert score_p.observation.code == ObservationCode.CHECK_WORTHY_SCORE
        assert score_p.observation.seq == 2
        assert score_p.observation.status == "P"

        # CHECK_WORTHY_SCORE (seq=3, F)
        score_f = calls[3][0][1]
        assert isinstance(score_f, ObsMessage)
        assert score_f.observation.code == ObservationCode.CHECK_WORTHY_SCORE
        assert score_f.observation.seq == 3
        assert score_f.observation.status == "F"

        # STOP
        stop_msg = calls[4][0][1]
        assert isinstance(stop_msg, StopMessage)
        assert stop_msg.final_status == "F"
        assert stop_msg.observation_count == 3


class TestBelowThresholdCancellation:
    @pytest.mark.asyncio
    async def test_below_threshold_returns_x_status(self):
        stream, redis, anthropic = _build_handler_mocks(claude_score=0.25)

        with _patched_handler(stream, redis, anthropic) as handler:
            result = await handler.run(_make_input())

        assert result.terminal_status == "X"
        assert result.check_worthiness_score == 0.25

        # STOP should have finalStatus="X"
        stop_call = stream.publish.call_args_list[-1]
        stop_msg = stop_call[0][1]
        assert isinstance(stop_msg, StopMessage)
        assert stop_msg.final_status == "X"


class TestStreamNotFound:
    @pytest.mark.asyncio
    async def test_missing_ingestion_stream_raises(self):
        stream, redis, anthropic = _build_handler_mocks()
        stream.read_range.return_value = []  # Empty stream

        with _patched_handler(stream, redis, anthropic) as handler:
            with pytest.raises(StreamNotFoundError):
                await handler.run(_make_input())


class TestProgressEvents:
    @pytest.mark.asyncio
    async def test_progress_events_published_in_order(self):
        stream, redis, anthropic = _build_handler_mocks(claude_score=0.82)

        with _patched_handler(stream, redis, anthropic) as handler:
            await handler.run(_make_input())

        progress_calls = [c for c in redis.xadd.call_args_list if c[0][0].startswith("progress:")]

        # Should have 4 progress events: normalizing, scoring, score value, gate decision
        assert len(progress_calls) == 4
        messages = [c[0][1]["message"] for c in progress_calls]
        assert "Normalizing claim text..." in messages[0]
        assert "Scoring check-worthiness..." in messages[1]
        assert "Check-worthiness score:" in messages[2]
        assert "check-worthy" in messages[3].lower()
