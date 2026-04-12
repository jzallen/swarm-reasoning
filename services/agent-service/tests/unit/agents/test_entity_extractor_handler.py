"""Unit tests for EntityExtractorHandler."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.activities.run_agent import AgentActivityInput
from swarm_reasoning.agents._utils import StreamNotFoundError
from swarm_reasoning.agents.entity_extractor.handler import (
    AGENT_NAME,
    EntityExtractorHandler,
)
from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType
from swarm_reasoning.models.stream import ObsMessage, StartMessage, StopMessage


def _make_input(run_id: str = "run-001", claim_text: str = "Test claim") -> AgentActivityInput:
    return AgentActivityInput(
        run_id=run_id,
        claim_text=claim_text,
        agent_name="entity-extractor",
        phase="ingestion",
    )


def _mock_detector_stream(
    normalized_claim: str = "Biden signed executive order 14042 in January 2021.",
) -> list:
    """Build a mock claim-detector stream read_range response."""
    return [
        MagicMock(type="START"),
        ObsMessage(
            observation=Observation(
                runId="run-001",
                agent="claim-detector",
                seq=1,
                code=ObservationCode.CLAIM_NORMALIZED,
                value=normalized_claim,
                valueType=ValueType.ST,
                status="F",
                timestamp="2026-04-10T12:00:00Z",
                method="normalize_claim",
            )
        ),
        MagicMock(type="STOP"),
    ]


def _mock_claude_entity_response(
    persons: list[str] | None = None,
    organizations: list[str] | None = None,
    dates: list[str] | None = None,
    locations: list[str] | None = None,
    statistics: list[str] | None = None,
) -> MagicMock:
    data = {
        "persons": persons or [],
        "organizations": organizations or [],
        "dates": dates or [],
        "locations": locations or [],
        "statistics": statistics or [],
    }
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(data))]
    return resp


def _build_handler_mocks(
    detector_messages: list | None = None,
    persons: list[str] | None = None,
    organizations: list[str] | None = None,
):
    """Build mocked stream, redis, anthropic for handler construction."""
    stream_mock = AsyncMock()
    stream_mock.read_range.return_value = detector_messages or _mock_detector_stream()
    stream_mock.publish = AsyncMock()
    stream_mock.close = AsyncMock()

    redis_mock = AsyncMock()
    redis_mock.xadd = AsyncMock()
    redis_mock.aclose = AsyncMock()

    anthropic_mock = AsyncMock()
    resp = _mock_claude_entity_response(
        persons=persons or ["Joe Biden"],
        organizations=organizations or [],
    )
    anthropic_mock.messages.create = AsyncMock(return_value=resp)

    return stream_mock, redis_mock, anthropic_mock


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_returns_f_status_with_entities(self):
        stream, redis, anthropic = _build_handler_mocks(
            persons=["Joe Biden"], organizations=["White House"]
        )

        with (
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.RedisReasoningStream",
                return_value=stream,
            ),
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.aioredis.Redis",
                return_value=redis,
            ),
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.AsyncAnthropic",
                return_value=anthropic,
            ),
            patch("swarm_reasoning.agents.entity_extractor.handler.activity"),
        ):
            handler = EntityExtractorHandler(anthropic_api_key="test-key")
            result = await handler.run(_make_input())

        assert result.terminal_status == "F"
        assert result.observation_count == 2
        assert result.agent_name == "entity-extractor"

    @pytest.mark.asyncio
    async def test_stream_publishes_correct_sequence(self):
        stream, redis, anthropic = _build_handler_mocks(
            persons=["Alice", "Bob"], organizations=["Acme"]
        )

        with (
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.RedisReasoningStream",
                return_value=stream,
            ),
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.aioredis.Redis",
                return_value=redis,
            ),
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.AsyncAnthropic",
                return_value=anthropic,
            ),
            patch("swarm_reasoning.agents.entity_extractor.handler.activity"),
        ):
            handler = EntityExtractorHandler(anthropic_api_key="test-key")
            await handler.run(_make_input())

        # publish_entities calls: START + 3 OBS + STOP = 5
        calls = stream.publish.call_args_list
        assert len(calls) == 5

        # START
        start_msg = calls[0][0][1]
        assert isinstance(start_msg, StartMessage)
        assert start_msg.agent == AGENT_NAME

        # OBS 1: ENTITY_PERSON "Alice"
        obs1 = calls[1][0][1]
        assert isinstance(obs1, ObsMessage)
        assert obs1.observation.code == ObservationCode.ENTITY_PERSON
        assert obs1.observation.seq == 1

        # OBS 2: ENTITY_PERSON "Bob"
        obs2 = calls[2][0][1]
        assert obs2.observation.code == ObservationCode.ENTITY_PERSON
        assert obs2.observation.seq == 2

        # OBS 3: ENTITY_ORG "Acme"
        obs3 = calls[3][0][1]
        assert obs3.observation.code == ObservationCode.ENTITY_ORG
        assert obs3.observation.seq == 3

        # STOP
        stop_msg = calls[4][0][1]
        assert isinstance(stop_msg, StopMessage)
        assert stop_msg.final_status == "F"
        assert stop_msg.observation_count == 3


class TestEmptyEntities:
    @pytest.mark.asyncio
    async def test_no_entities_returns_zero_count(self):
        stream, redis, anthropic = _build_handler_mocks(persons=[], organizations=[])
        # Override to return empty entities
        anthropic.messages.create = AsyncMock(
            return_value=_mock_claude_entity_response()
        )

        with (
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.RedisReasoningStream",
                return_value=stream,
            ),
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.aioredis.Redis",
                return_value=redis,
            ),
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.AsyncAnthropic",
                return_value=anthropic,
            ),
            patch("swarm_reasoning.agents.entity_extractor.handler.activity"),
        ):
            handler = EntityExtractorHandler(anthropic_api_key="test-key")
            result = await handler.run(_make_input())

        assert result.observation_count == 0
        assert result.terminal_status == "F"

        # START + STOP only
        calls = stream.publish.call_args_list
        assert len(calls) == 2


class TestStreamNotFound:
    @pytest.mark.asyncio
    async def test_missing_detector_stream_raises(self):
        stream, redis, anthropic = _build_handler_mocks()
        stream.read_range.return_value = []  # Empty stream

        with (
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.RedisReasoningStream",
                return_value=stream,
            ),
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.aioredis.Redis",
                return_value=redis,
            ),
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.AsyncAnthropic",
                return_value=anthropic,
            ),
            patch("swarm_reasoning.agents.entity_extractor.handler.activity"),
        ):
            handler = EntityExtractorHandler(anthropic_api_key="test-key")
            with pytest.raises(StreamNotFoundError):
                await handler.run(_make_input())


class TestLLMFailure:
    @pytest.mark.asyncio
    async def test_llm_failure_publishes_error_stop(self):
        from swarm_reasoning.agents.entity_extractor.extractor import LLMUnavailableError

        stream, redis, anthropic = _build_handler_mocks()
        anthropic.messages.create = AsyncMock(
            side_effect=Exception("connection failed")
        )

        with (
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.RedisReasoningStream",
                return_value=stream,
            ),
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.aioredis.Redis",
                return_value=redis,
            ),
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.AsyncAnthropic",
                return_value=anthropic,
            ),
            patch("swarm_reasoning.agents.entity_extractor.handler.activity"),
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.extract_entities_llm",
                side_effect=LLMUnavailableError("API down"),
            ),
        ):
            handler = EntityExtractorHandler(anthropic_api_key="test-key")
            with pytest.raises(LLMUnavailableError):
                await handler.run(_make_input())

        # Should have published START + error STOP
        publish_calls = stream.publish.call_args_list
        assert len(publish_calls) == 2
        assert isinstance(publish_calls[0][0][1], StartMessage)
        stop_msg = publish_calls[1][0][1]
        assert isinstance(stop_msg, StopMessage)
        assert stop_msg.final_status == "X"


class TestProgressEvents:
    @pytest.mark.asyncio
    async def test_progress_events_published(self):
        stream, redis, anthropic = _build_handler_mocks(
            persons=["Alice"], organizations=["Acme"]
        )

        with (
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.RedisReasoningStream",
                return_value=stream,
            ),
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.aioredis.Redis",
                return_value=redis,
            ),
            patch(
                "swarm_reasoning.agents.entity_extractor.handler.AsyncAnthropic",
                return_value=anthropic,
            ),
            patch("swarm_reasoning.agents.entity_extractor.handler.activity"),
        ):
            handler = EntityExtractorHandler(anthropic_api_key="test-key")
            await handler.run(_make_input())

        progress_calls = [
            c for c in redis.xadd.call_args_list if c[0][0].startswith("progress:")
        ]

        assert len(progress_calls) == 3
        messages = [c[0][1]["message"] for c in progress_calls]
        assert "Extracting named entities..." in messages[0]
        assert "Found 2 entities:" in messages[1]
        assert "Entity extraction complete" in messages[2]
