"""Unit tests for shared observation @tool definitions."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from swarm_reasoning.agents.observation_tools import publish_observation, publish_progress
from swarm_reasoning.agents.tool_runtime import AgentContext, ToolRuntime
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.models.stream import ObsMessage


def _make_context(agent_name: str = "test-agent", run_id: str = "run-001") -> AgentContext:
    """Create an AgentContext with mocked stream and Redis client."""
    stream = AsyncMock()
    stream.publish = AsyncMock()
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock()

    return AgentContext(
        stream=stream,
        redis_client=redis_client,
        run_id=run_id,
        sk=f"reasoning:{run_id}:{agent_name}",
        agent_name=agent_name,
    )


class TestPublishObservation:
    async def test_publishes_st_observation(self):
        ctx = _make_context()

        result = await publish_observation.ainvoke(
            {
                "code": "CLAIM_TEXT",
                "value": "The sky is blue",
                "context": ctx,
            }
        )

        assert "CLAIM_TEXT" in result
        assert "seq=1" in result
        assert ctx.seq_counter == 1
        ctx.stream.publish.assert_awaited_once()
        call_args = ctx.stream.publish.call_args
        assert call_args[0][0] == "reasoning:run-001:test-agent"
        msg: ObsMessage = call_args[0][1]
        assert msg.observation.code == ObservationCode.CLAIM_TEXT
        assert msg.observation.value == "The sky is blue"
        assert msg.observation.value_type == ValueType.ST
        assert msg.observation.status == "F"
        assert msg.observation.agent == "test-agent"

    async def test_publishes_nm_observation(self):
        ctx = _make_context()

        result = await publish_observation.ainvoke(
            {
                "code": "CHECK_WORTHY_SCORE",
                "value": "0.85",
                "context": ctx,
            }
        )

        assert "CHECK_WORTHY_SCORE" in result
        msg: ObsMessage = ctx.stream.publish.call_args[0][1]
        assert msg.observation.value_type == ValueType.NM
        assert msg.observation.value == "0.85"

    async def test_publishes_cwe_observation(self):
        ctx = _make_context()

        result = await publish_observation.ainvoke(
            {
                "code": "VERDICT",
                "value": "TRUE^True^FCK",
                "context": ctx,
            }
        )

        assert "VERDICT" in result
        msg: ObsMessage = ctx.stream.publish.call_args[0][1]
        assert msg.observation.value_type == ValueType.CWE
        assert msg.observation.value == "TRUE^True^FCK"

    async def test_increments_seq_across_calls(self):
        ctx = _make_context()

        await publish_observation.ainvoke({"code": "CLAIM_TEXT", "value": "first", "context": ctx})
        await publish_observation.ainvoke(
            {"code": "CLAIM_SOURCE_URL", "value": "https://example.com", "context": ctx}
        )

        assert ctx.seq_counter == 2
        first_msg: ObsMessage = ctx.stream.publish.call_args_list[0][0][1]
        second_msg: ObsMessage = ctx.stream.publish.call_args_list[1][0][1]
        assert first_msg.observation.seq == 1
        assert second_msg.observation.seq == 2

    async def test_preliminary_status(self):
        ctx = _make_context()

        result = await publish_observation.ainvoke(
            {
                "code": "CLAIM_TEXT",
                "value": "preliminary finding",
                "status": "P",
                "context": ctx,
            }
        )

        assert "status=P" in result
        msg: ObsMessage = ctx.stream.publish.call_args[0][1]
        assert msg.observation.status == "P"

    async def test_with_method_and_note(self):
        ctx = _make_context()

        await publish_observation.ainvoke(
            {
                "code": "CLAIM_DOMAIN",
                "value": "HEALTHCARE",
                "method": "classify_domain",
                "note": "High confidence classification",
                "context": ctx,
            }
        )

        msg: ObsMessage = ctx.stream.publish.call_args[0][1]
        assert msg.observation.method == "classify_domain"
        assert msg.observation.note == "High confidence classification"

    async def test_invalid_code_raises(self):
        ctx = _make_context()

        with pytest.raises(ValueError):
            await publish_observation.ainvoke(
                {
                    "code": "INVALID_CODE",
                    "value": "bad",
                    "context": ctx,
                }
            )

    async def test_uses_registry_units_and_range(self):
        ctx = _make_context()

        await publish_observation.ainvoke(
            {
                "code": "CHECK_WORTHY_SCORE",
                "value": "0.92",
                "context": ctx,
            }
        )

        msg: ObsMessage = ctx.stream.publish.call_args[0][1]
        assert msg.observation.units == "score"
        assert msg.observation.reference_range == "0.0-1.0"


class TestPublishProgress:
    async def test_publishes_progress_message(self):
        ctx = _make_context()

        result = await publish_progress.ainvoke(
            {
                "message": "Analyzing claim...",
                "context": ctx,
            }
        )

        assert "Progress published" in result
        ctx.redis_client.xadd.assert_awaited_once()
        call_args = ctx.redis_client.xadd.call_args
        assert call_args[0][0] == "progress:run-001"
        fields = call_args[0][1]
        assert fields["agent"] == "test-agent"
        assert fields["message"] == "Analyzing claim..."
        assert "timestamp" in fields

    async def test_progress_failure_returns_error_message(self):
        ctx = _make_context()
        ctx.redis_client.xadd = AsyncMock(side_effect=ConnectionError("Redis down"))

        result = await publish_progress.ainvoke(
            {
                "message": "This will fail",
                "context": ctx,
            }
        )

        assert "Failed" in result


class TestToolRuntime:
    def test_wraps_context(self):
        ctx = _make_context()
        runtime = ToolRuntime(ctx)

        assert runtime.context is ctx
        assert runtime.context.agent_name == "test-agent"
        assert runtime.context.run_id == "run-001"

    def test_context_seq_counter_starts_at_zero(self):
        ctx = _make_context()
        runtime = ToolRuntime(ctx)

        assert runtime.context.seq_counter == 0
        assert runtime.context.next_seq() == 1
        assert runtime.context.next_seq() == 2


class TestAgentContext:
    def test_next_seq_is_monotonic(self):
        ctx = _make_context()

        seqs = [ctx.next_seq() for _ in range(5)]

        assert seqs == [1, 2, 3, 4, 5]

    async def test_publish_obs_delegates_to_stream(self):
        ctx = _make_context()

        await ctx.publish_obs(
            code=ObservationCode.CLAIM_TEXT,
            value="test claim",
            value_type=ValueType.ST,
        )

        assert ctx.seq_counter == 1
        ctx.stream.publish.assert_awaited_once()
        msg: ObsMessage = ctx.stream.publish.call_args[0][1]
        assert msg.observation.code == ObservationCode.CLAIM_TEXT
        assert msg.observation.value == "test claim"
        assert msg.observation.seq == 1
