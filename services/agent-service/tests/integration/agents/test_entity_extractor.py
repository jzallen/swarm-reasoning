"""Integration tests for entity-extractor agent flow.

These tests use mocked Claude but live ReasoningStream mocks
to verify the full START -> OBS -> STOP flow.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.activities.run_agent import AgentActivityInput
from swarm_reasoning.agents.entity_extractor.handler import EntityExtractorHandler
from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType
from swarm_reasoning.models.stream import ObsMessage, StartMessage, StopMessage


def _make_input(run_id: str = "run-int-001") -> AgentActivityInput:
    return AgentActivityInput(
        run_id=run_id,
        claim_text="Biden signed the infrastructure bill in November 2021.",
        agent_name="entity-extractor",
        phase="ingestion",
    )


def _mock_detector_stream(
    run_id: str = "run-int-001",
    normalized_claim: str = "Biden signed the infrastructure bill in November 2021.",
) -> list:
    return [
        MagicMock(type="START"),
        ObsMessage(
            observation=Observation(
                runId=run_id,
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


def _mock_claude_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(data))]
    return resp


class TestFullFlow:
    @pytest.mark.asyncio
    async def test_start_obs_stop_sequence(self):
        """Verify stream contains START, N OBS, STOP in order."""
        stream = AsyncMock()
        stream.read_range.return_value = _mock_detector_stream()
        stream.publish = AsyncMock()
        stream.close = AsyncMock()

        redis = AsyncMock()
        redis.xadd = AsyncMock()
        redis.aclose = AsyncMock()

        anthropic = AsyncMock()
        anthropic.messages.create = AsyncMock(
            return_value=_mock_claude_response(
                {
                    "persons": ["Joe Biden"],
                    "organizations": [],
                    "dates": ["20211100"],
                    "locations": [],
                    "statistics": [],
                }
            )
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

        calls = stream.publish.call_args_list
        assert result.terminal_status == "F"
        assert result.observation_count == 2  # 1 person + 1 date

        # Verify message types in order: START, OBS..., STOP
        msg_types = []
        for c in calls:
            msg = c[0][1]
            if isinstance(msg, StartMessage):
                msg_types.append("START")
            elif isinstance(msg, ObsMessage):
                msg_types.append("OBS")
            elif isinstance(msg, StopMessage):
                msg_types.append("STOP")

        assert msg_types[0] == "START"
        assert msg_types[-1] == "STOP"
        assert all(t == "OBS" for t in msg_types[1:-1])

        # Verify STOP observationCount matches actual OBS count
        stop_msg = calls[-1][0][1]
        obs_count = sum(1 for t in msg_types if t == "OBS")
        assert stop_msg.observation_count == obs_count

    @pytest.mark.asyncio
    async def test_all_obs_codes_are_entity_codes(self):
        """Verify all OBS code values are valid entity codes."""
        valid_codes = {
            ObservationCode.ENTITY_PERSON,
            ObservationCode.ENTITY_ORG,
            ObservationCode.ENTITY_DATE,
            ObservationCode.ENTITY_LOCATION,
            ObservationCode.ENTITY_STATISTIC,
        }

        stream = AsyncMock()
        stream.read_range.return_value = _mock_detector_stream()
        stream.publish = AsyncMock()
        stream.close = AsyncMock()

        redis = AsyncMock()
        redis.xadd = AsyncMock()
        redis.aclose = AsyncMock()

        anthropic = AsyncMock()
        anthropic.messages.create = AsyncMock(
            return_value=_mock_claude_response(
                {
                    "persons": ["Alice"],
                    "organizations": ["NASA"],
                    "dates": ["2023"],
                    "locations": ["Houston"],
                    "statistics": ["90%"],
                }
            )
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

        for c in stream.publish.call_args_list:
            msg = c[0][1]
            if isinstance(msg, ObsMessage):
                assert msg.observation.code in valid_codes

    @pytest.mark.asyncio
    async def test_seq_is_monotonically_increasing(self):
        """Verify seq numbers are monotonically increasing with no gaps."""
        stream = AsyncMock()
        stream.read_range.return_value = _mock_detector_stream()
        stream.publish = AsyncMock()
        stream.close = AsyncMock()

        redis = AsyncMock()
        redis.xadd = AsyncMock()
        redis.aclose = AsyncMock()

        anthropic = AsyncMock()
        anthropic.messages.create = AsyncMock(
            return_value=_mock_claude_response(
                {
                    "persons": ["A", "B"],
                    "organizations": ["C"],
                    "dates": ["20230101"],
                    "locations": ["D"],
                    "statistics": ["50%"],
                }
            )
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

        seqs = []
        for c in stream.publish.call_args_list:
            msg = c[0][1]
            if isinstance(msg, ObsMessage):
                seqs.append(msg.observation.seq)

        assert seqs == list(range(1, len(seqs) + 1))


class TestEmptyEntities:
    @pytest.mark.asyncio
    async def test_no_entities_produces_start_stop_only(self):
        stream = AsyncMock()
        stream.read_range.return_value = _mock_detector_stream()
        stream.publish = AsyncMock()
        stream.close = AsyncMock()

        redis = AsyncMock()
        redis.xadd = AsyncMock()
        redis.aclose = AsyncMock()

        anthropic = AsyncMock()
        anthropic.messages.create = AsyncMock(
            return_value=_mock_claude_response(
                {
                    "persons": [],
                    "organizations": [],
                    "dates": [],
                    "locations": [],
                    "statistics": [],
                }
            )
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
        calls = stream.publish.call_args_list
        assert len(calls) == 2
        assert isinstance(calls[0][0][1], StartMessage)
        assert isinstance(calls[1][0][1], StopMessage)
        assert calls[1][0][1].observation_count == 0


class TestProgressEvents:
    @pytest.mark.asyncio
    async def test_progress_events_in_stream(self):
        stream = AsyncMock()
        stream.read_range.return_value = _mock_detector_stream()
        stream.publish = AsyncMock()
        stream.close = AsyncMock()

        redis = AsyncMock()
        redis.xadd = AsyncMock()
        redis.aclose = AsyncMock()

        anthropic = AsyncMock()
        anthropic.messages.create = AsyncMock(
            return_value=_mock_claude_response(
                {
                    "persons": ["Test Person"],
                    "organizations": [],
                    "dates": [],
                    "locations": [],
                    "statistics": [],
                }
            )
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
        assert "Found 1 entities:" in messages[1]
        assert "Entity extraction complete" in messages[2]
