"""Unit tests for AgentContext and ToolRuntime adapter."""

from __future__ import annotations

import threading
from unittest.mock import AsyncMock, call

import pytest

from swarm_reasoning.agents.tool_runtime import AgentContext, ToolRuntime, _now_iso
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.models.stream import ObsMessage


def _make_context(
    agent_name: str = "test-agent",
    run_id: str = "run-001",
) -> AgentContext:
    """Create an AgentContext with mocked stream and Redis client."""
    stream = AsyncMock()
    stream.publish = AsyncMock()
    redis_client = AsyncMock()
    return AgentContext(
        stream=stream,
        redis_client=redis_client,
        run_id=run_id,
        sk=f"reasoning:{run_id}:{agent_name}",
        agent_name=agent_name,
    )


class TestAgentContextInit:
    def test_fields_stored(self):
        ctx = _make_context(agent_name="ingestion-agent", run_id="run-042")

        assert ctx.agent_name == "ingestion-agent"
        assert ctx.run_id == "run-042"
        assert ctx.sk == "reasoning:run-042:ingestion-agent"
        assert ctx.stream is not None
        assert ctx.redis_client is not None

    def test_seq_counter_defaults_to_zero(self):
        ctx = _make_context()

        assert ctx.seq_counter == 0

    def test_lock_not_in_repr(self):
        ctx = _make_context()
        r = repr(ctx)

        assert "_lock" not in r


class TestNextSeq:
    def test_first_call_returns_one(self):
        ctx = _make_context()

        assert ctx.next_seq() == 1

    def test_monotonically_increasing(self):
        ctx = _make_context()

        seqs = [ctx.next_seq() for _ in range(5)]

        assert seqs == [1, 2, 3, 4, 5]

    def test_updates_seq_counter(self):
        ctx = _make_context()

        ctx.next_seq()
        ctx.next_seq()

        assert ctx.seq_counter == 2

    def test_thread_safety(self):
        ctx = _make_context()
        results: list[int] = []
        errors: list[Exception] = []

        def call_next_seq(n: int) -> None:
            try:
                for _ in range(n):
                    results.append(ctx.next_seq())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=call_next_seq, args=(50,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 200
        assert sorted(results) == list(range(1, 201))
        assert len(set(results)) == 200  # no duplicates


class TestPublishObs:
    async def test_publishes_to_stream(self):
        ctx = _make_context()

        await ctx.publish_obs(
            code=ObservationCode.CLAIM_TEXT,
            value="The earth is round",
            value_type=ValueType.ST,
        )

        ctx.stream.publish.assert_awaited_once()

    async def test_uses_correct_stream_key(self):
        ctx = _make_context(agent_name="coverage-left", run_id="run-007")

        await ctx.publish_obs(
            code=ObservationCode.COVERAGE_ARTICLE_COUNT,
            value="5",
            value_type=ValueType.NM,
        )

        sk_arg = ctx.stream.publish.call_args[0][0]
        assert sk_arg == "reasoning:run-007:coverage-left"

    async def test_observation_fields(self):
        ctx = _make_context(agent_name="synthesizer", run_id="run-099")

        await ctx.publish_obs(
            code=ObservationCode.VERDICT,
            value="TRUE^True^FCK",
            value_type=ValueType.CWE,
            status="F",
            method="resolve_verdict",
            note="High confidence",
            units=None,
            reference_range=None,
        )

        msg: ObsMessage = ctx.stream.publish.call_args[0][1]
        obs = msg.observation
        assert obs.run_id == "run-099"
        assert obs.agent == "synthesizer"
        assert obs.seq == 1
        assert obs.code == ObservationCode.VERDICT
        assert obs.value == "TRUE^True^FCK"
        assert obs.value_type == ValueType.CWE
        assert obs.status == "F"
        assert obs.method == "resolve_verdict"
        assert obs.note == "High confidence"

    async def test_auto_increments_seq(self):
        ctx = _make_context()

        await ctx.publish_obs(
            code=ObservationCode.CLAIM_TEXT,
            value="first",
            value_type=ValueType.ST,
        )
        await ctx.publish_obs(
            code=ObservationCode.CLAIM_SOURCE_URL,
            value="https://example.com",
            value_type=ValueType.ST,
        )

        first_msg: ObsMessage = ctx.stream.publish.call_args_list[0][0][1]
        second_msg: ObsMessage = ctx.stream.publish.call_args_list[1][0][1]
        assert first_msg.observation.seq == 1
        assert second_msg.observation.seq == 2
        assert ctx.seq_counter == 2

    async def test_defaults_status_to_final(self):
        ctx = _make_context()

        await ctx.publish_obs(
            code=ObservationCode.CLAIM_TEXT,
            value="test",
            value_type=ValueType.ST,
        )

        msg: ObsMessage = ctx.stream.publish.call_args[0][1]
        assert msg.observation.status == "F"

    async def test_preliminary_status(self):
        ctx = _make_context()

        await ctx.publish_obs(
            code=ObservationCode.CLAIM_TEXT,
            value="preliminary finding",
            value_type=ValueType.ST,
            status="P",
        )

        msg: ObsMessage = ctx.stream.publish.call_args[0][1]
        assert msg.observation.status == "P"

    async def test_optional_fields_default_none(self):
        ctx = _make_context()

        await ctx.publish_obs(
            code=ObservationCode.CLAIM_TEXT,
            value="just text",
            value_type=ValueType.ST,
        )

        msg: ObsMessage = ctx.stream.publish.call_args[0][1]
        obs = msg.observation
        assert obs.method is None
        assert obs.note is None
        assert obs.units is None
        assert obs.reference_range is None

    async def test_with_units_and_reference_range(self):
        ctx = _make_context()

        await ctx.publish_obs(
            code=ObservationCode.CHECK_WORTHY_SCORE,
            value="0.85",
            value_type=ValueType.NM,
            units="score",
            reference_range="0.0-1.0",
        )

        msg: ObsMessage = ctx.stream.publish.call_args[0][1]
        assert msg.observation.units == "score"
        assert msg.observation.reference_range == "0.0-1.0"

    async def test_timestamp_is_iso_format(self):
        ctx = _make_context()

        await ctx.publish_obs(
            code=ObservationCode.CLAIM_TEXT,
            value="test",
            value_type=ValueType.ST,
        )

        msg: ObsMessage = ctx.stream.publish.call_args[0][1]
        ts = msg.observation.timestamp
        assert "T" in ts  # ISO-8601 format


class TestToolRuntime:
    def test_wraps_context(self):
        ctx = _make_context()
        runtime = ToolRuntime(ctx)

        assert runtime.context is ctx

    def test_context_identity_preserved(self):
        ctx = _make_context(agent_name="entity-extractor", run_id="run-abc")
        runtime = ToolRuntime(ctx)

        assert runtime.context.agent_name == "entity-extractor"
        assert runtime.context.run_id == "run-abc"
        assert runtime.context.sk == "reasoning:run-abc:entity-extractor"

    def test_seq_operations_through_runtime(self):
        ctx = _make_context()
        runtime = ToolRuntime(ctx)

        assert runtime.context.next_seq() == 1
        assert runtime.context.next_seq() == 2
        assert runtime.context.seq_counter == 2

    async def test_publish_obs_through_runtime(self):
        ctx = _make_context()
        runtime = ToolRuntime(ctx)

        await runtime.context.publish_obs(
            code=ObservationCode.CLAIM_TEXT,
            value="routed through runtime",
            value_type=ValueType.ST,
        )

        ctx.stream.publish.assert_awaited_once()
        msg: ObsMessage = ctx.stream.publish.call_args[0][1]
        assert msg.observation.value == "routed through runtime"


class TestNowIso:
    def test_returns_string(self):
        result = _now_iso()

        assert isinstance(result, str)

    def test_iso_format(self):
        result = _now_iso()

        assert "T" in result
        assert "+" in result or "Z" in result or result.endswith("+00:00")
