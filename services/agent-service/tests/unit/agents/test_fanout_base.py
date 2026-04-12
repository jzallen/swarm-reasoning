"""Unit tests for FanoutBase shared base class."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.fanout_base import FanoutBase, StreamNotFoundError
from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType
from swarm_reasoning.models.stream import ObsMessage, StartMessage, StopMessage


def _mock_upstream_streams(
    normalized_claim: str = "unemployment rate fell to 3.4%",
    domain: str = "ECONOMICS",
    persons: list[str] | None = None,
    orgs: list[str] | None = None,
) -> dict[str, list]:
    """Build mock stream responses for Phase 1 agents."""
    # claim-detector stream
    detector = [
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

    # ingestion-agent stream
    ingestion = [
        MagicMock(type="START"),
        ObsMessage(
            observation=Observation(
                runId="run-001",
                agent="ingestion-agent",
                seq=1,
                code=ObservationCode.CLAIM_DOMAIN,
                value=domain,
                valueType=ValueType.ST,
                status="F",
                timestamp="2026-04-10T12:00:00Z",
                method="classify_domain",
            )
        ),
        MagicMock(type="STOP"),
    ]

    # entity-extractor stream
    extractor_msgs: list = [MagicMock(type="START")]
    seq = 0
    for person in (persons or []):
        seq += 1
        extractor_msgs.append(
            ObsMessage(
                observation=Observation(
                    runId="run-001",
                    agent="entity-extractor",
                    seq=seq,
                    code=ObservationCode.ENTITY_PERSON,
                    value=person,
                    valueType=ValueType.ST,
                    status="F",
                    timestamp="2026-04-10T12:00:00Z",
                    method="extract_entities",
                )
            )
        )
    for org in (orgs or []):
        seq += 1
        extractor_msgs.append(
            ObsMessage(
                observation=Observation(
                    runId="run-001",
                    agent="entity-extractor",
                    seq=seq,
                    code=ObservationCode.ENTITY_ORG,
                    value=org,
                    valueType=ValueType.ST,
                    status="F",
                    timestamp="2026-04-10T12:00:00Z",
                    method="extract_entities",
                )
            )
        )
    extractor_msgs.append(MagicMock(type="STOP"))

    return {
        "reasoning:run-001:claim-detector": detector,
        "reasoning:run-001:ingestion-agent": ingestion,
        "reasoning:run-001:entity-extractor": extractor_msgs,
    }


def _make_stream_mock(streams: dict[str, list]) -> AsyncMock:
    """Create a stream mock that routes read_range by key."""
    stream_mock = AsyncMock()

    async def read_range(key, **kwargs):
        return streams.get(key, [])

    stream_mock.read_range = AsyncMock(side_effect=read_range)
    stream_mock.publish = AsyncMock()
    stream_mock.close = AsyncMock()
    return stream_mock


def _make_input(run_id: str = "run-001") -> MagicMock:
    """Create a mock AgentActivityInput."""
    inp = MagicMock()
    inp.run_id = run_id
    inp.agent_name = "test-agent"
    inp.claim_text = "Test claim"
    return inp


class ConcreteFanout(FanoutBase):
    """Concrete test implementation of FanoutBase."""

    AGENT_NAME = "test-agent"
    execute_called = False

    async def _execute(self, stream, redis_client, run_id, sk, context):
        self.execute_called = True
        self.received_context = context

    def _primary_code(self):
        return ObservationCode.CLAIMREVIEW_MATCH


class TestUpstreamContextLoading:
    @pytest.mark.asyncio
    async def test_loads_claim_context(self):
        streams = _mock_upstream_streams(
            normalized_claim="test claim text",
            domain="HEALTHCARE",
            persons=["Alice"],
            orgs=["CDC"],
        )
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream",
                return_value=stream_mock,
            ),
            patch(
                "swarm_reasoning.agents.fanout_base.aioredis.Redis",
                return_value=redis_mock,
            ),
            patch("swarm_reasoning.agents.fanout_base.activity"),
        ):
            handler = ConcreteFanout()
            await handler.run(_make_input())

        assert handler.execute_called
        ctx = handler.received_context
        assert ctx.normalized_claim == "test claim text"
        assert ctx.domain == "HEALTHCARE"
        assert ctx.persons == ["Alice"]
        assert ctx.organizations == ["CDC"]

    @pytest.mark.asyncio
    async def test_missing_claim_raises_stream_not_found(self):
        streams = {
            "reasoning:run-001:claim-detector": [],
            "reasoning:run-001:ingestion-agent": [],
            "reasoning:run-001:entity-extractor": [],
        }
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream",
                return_value=stream_mock,
            ),
            patch(
                "swarm_reasoning.agents.fanout_base.aioredis.Redis",
                return_value=redis_mock,
            ),
            patch("swarm_reasoning.agents.fanout_base.activity"),
        ):
            handler = ConcreteFanout()
            with pytest.raises(StreamNotFoundError):
                await handler.run(_make_input())


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_publishes_start_and_stop(self):
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream",
                return_value=stream_mock,
            ),
            patch(
                "swarm_reasoning.agents.fanout_base.aioredis.Redis",
                return_value=redis_mock,
            ),
            patch("swarm_reasoning.agents.fanout_base.activity"),
        ):
            handler = ConcreteFanout()
            result = await handler.run(_make_input())

        calls = stream_mock.publish.call_args_list
        # START + STOP
        assert len(calls) == 2

        start_msg = calls[0][0][1]
        assert isinstance(start_msg, StartMessage)
        assert start_msg.agent == "test-agent"

        stop_msg = calls[1][0][1]
        assert isinstance(stop_msg, StopMessage)
        assert stop_msg.final_status == "F"
        assert stop_msg.observation_count == 0

        assert result.terminal_status == "F"

    @pytest.mark.asyncio
    async def test_timeout_produces_x_status(self):
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        class SlowFanout(FanoutBase):
            AGENT_NAME = "test-slow"

            async def _execute(self, stream, redis_client, run_id, sk, context):
                import asyncio
                await asyncio.sleep(100)

            def _primary_code(self):
                return ObservationCode.CLAIMREVIEW_MATCH

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream",
                return_value=stream_mock,
            ),
            patch(
                "swarm_reasoning.agents.fanout_base.aioredis.Redis",
                return_value=redis_mock,
            ),
            patch("swarm_reasoning.agents.fanout_base.activity"),
            patch("swarm_reasoning.agents.fanout_base.INTERNAL_TIMEOUT_S", 0.1),
        ):
            handler = SlowFanout()
            result = await handler.run(_make_input())

        assert result.terminal_status == "X"
        # START + timeout OBS + STOP
        calls = stream_mock.publish.call_args_list
        assert len(calls) == 3
        stop_msg = calls[-1][0][1]
        assert isinstance(stop_msg, StopMessage)
        assert stop_msg.final_status == "X"


class TestProgressEvents:
    @pytest.mark.asyncio
    async def test_progress_events_published(self):
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream",
                return_value=stream_mock,
            ),
            patch(
                "swarm_reasoning.agents.fanout_base.aioredis.Redis",
                return_value=redis_mock,
            ),
            patch("swarm_reasoning.agents.fanout_base.activity"),
        ):
            handler = ConcreteFanout()
            await handler.run(_make_input())

        progress_calls = [
            c for c in redis_mock.xadd.call_args_list
            if c[0][0].startswith("progress:")
        ]
        assert len(progress_calls) >= 2  # start + completion
