"""Integration tests for RedisReasoningStream.

These tests require a running Redis instance on localhost:6379.
Mark with pytest.mark.integration so they can be skipped in CI without Redis.
"""

import time
import uuid

import pytest

from swarm_reasoning.config import RedisConfig
from swarm_reasoning.models.observation import Observation
from swarm_reasoning.models.stream import ObsMessage, StartMessage, StopMessage
from swarm_reasoning.stream.key import stream_key
from swarm_reasoning.stream.redis import RedisReasoningStream


def _unique_run_id() -> str:
    return f"test-{uuid.uuid4().hex[:8]}"


def _make_start(run_id: str, agent: str = "agent-a") -> StartMessage:
    return StartMessage(
        runId=run_id,
        agent=agent,
        phase="fanout",
        timestamp="2026-04-06T12:00:01Z",
    )


def _make_obs(run_id: str, seq: int, agent: str = "ingestion-agent") -> ObsMessage:
    return ObsMessage(
        observation=Observation(
            runId=run_id,
            agent=agent,
            seq=seq,
            code="CLAIM_TEXT",
            value="Test claim text",
            valueType="ST",
            status="P",
            timestamp="2026-04-06T12:00:02Z",
            method="test_method",
        ),
    )


def _make_stop(run_id: str, count: int, agent: str = "agent-a") -> StopMessage:
    return StopMessage(
        runId=run_id,
        agent=agent,
        finalStatus="F",
        observationCount=count,
        timestamp="2026-04-06T12:00:08Z",
    )


@pytest.fixture
async def redis_stream():
    stream = RedisReasoningStream(RedisConfig())
    yield stream
    await stream.close()


@pytest.mark.integration
class TestPublishAndRead:
    async def test_start_obs_stop_sequence(self, redis_stream: RedisReasoningStream):
        run_id = _unique_run_id()
        key = stream_key(run_id, "agent-a")

        start = _make_start(run_id)
        obs = _make_obs(run_id, seq=1)
        stop = _make_stop(run_id, count=1)

        await redis_stream.publish(key, start)
        await redis_stream.publish(key, obs)
        await redis_stream.publish(key, stop)

        messages = await redis_stream.read(key)
        assert len(messages) == 3
        assert isinstance(messages[0], StartMessage)
        assert isinstance(messages[1], ObsMessage)
        assert isinstance(messages[2], StopMessage)

    async def test_ordering_preserved(self, redis_stream: RedisReasoningStream):
        run_id = _unique_run_id()
        key = stream_key(run_id, "ingestion-agent")

        for i in range(1, 6):
            await redis_stream.publish(key, _make_obs(run_id, seq=i))

        messages = await redis_stream.read(key)
        assert len(messages) == 5
        seqs = [m.observation.seq for m in messages]
        assert seqs == [1, 2, 3, 4, 5]


@pytest.mark.integration
class TestAppendOnlyIntegrity:
    async def test_no_delete_or_modify_on_interface(self):
        """ReasoningStream ABC exposes no delete or modify methods."""
        from swarm_reasoning.stream.base import ReasoningStream

        method_names = {name for name in dir(ReasoningStream) if not name.startswith("_")}
        forbidden = {"delete", "remove", "trim", "modify", "update", "xdel", "xtrim"}
        assert method_names.isdisjoint(forbidden)


@pytest.mark.integration
class TestReadRange:
    async def test_xrange_with_id_filtering(self, redis_stream: RedisReasoningStream):
        run_id = _unique_run_id()
        key = stream_key(run_id, "ingestion-agent")

        ids = []
        for i in range(1, 11):
            entry_id = await redis_stream.publish(key, _make_obs(run_id, seq=i))
            ids.append(entry_id)

        # Read range from third to fifth (inclusive)
        messages = await redis_stream.read_range(key, start=ids[2], end=ids[4])
        assert len(messages) == 3
        seqs = [m.observation.seq for m in messages]
        assert seqs == [3, 4, 5]


@pytest.mark.integration
class TestThroughput:
    async def test_1000_observations_under_10_seconds(self, redis_stream: RedisReasoningStream):
        run_id = _unique_run_id()
        key = stream_key(run_id, "ingestion-agent")

        t0 = time.monotonic()
        for i in range(1, 1001):
            await redis_stream.publish(key, _make_obs(run_id, seq=i))
        elapsed = time.monotonic() - t0

        assert elapsed < 10.0, f"Publishing 1000 observations took {elapsed:.1f}s (>10s)"

        messages = await redis_stream.read_range(key)
        assert len(messages) == 1000


@pytest.mark.integration
class TestStreamDiscovery:
    async def test_list_streams_for_run(self, redis_stream: RedisReasoningStream):
        run_id = _unique_run_id()
        agents = ["agent-a", "agent-b", "agent-c"]

        for agent in agents:
            key = stream_key(run_id, agent)
            await redis_stream.publish(key, _make_start(run_id, agent=agent))

        streams = await redis_stream.list_streams(run_id)
        assert len(streams) == 3
        for agent in agents:
            assert stream_key(run_id, agent) in streams


@pytest.mark.integration
class TestHealth:
    async def test_healthy(self, redis_stream: RedisReasoningStream):
        assert await redis_stream.health() is True

    async def test_unhealthy(self):
        bad_config = RedisConfig(host="nonexistent-host", port=1)
        stream = RedisReasoningStream(bad_config)
        try:
            result = await stream.health()
            assert result is False
        finally:
            await stream.close()


@pytest.mark.integration
class TestReadLatest:
    async def test_read_latest_returns_last_message(self, redis_stream: RedisReasoningStream):
        run_id = _unique_run_id()
        key = stream_key(run_id, "agent-a")

        await redis_stream.publish(key, _make_start(run_id))
        await redis_stream.publish(key, _make_obs(run_id, seq=1))
        stop = _make_stop(run_id, count=1)
        await redis_stream.publish(key, stop)

        latest = await redis_stream.read_latest(key)
        assert isinstance(latest, StopMessage)

    async def test_read_latest_empty_stream(self, redis_stream: RedisReasoningStream):
        run_id = _unique_run_id()
        key = stream_key(run_id, "nonexistent-agent")

        latest = await redis_stream.read_latest(key)
        assert latest is None
