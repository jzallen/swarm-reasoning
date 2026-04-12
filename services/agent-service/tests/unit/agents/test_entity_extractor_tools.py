"""Unit tests for entity-extractor @tool definition."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from anthropic import AsyncAnthropic

from swarm_reasoning.agents.entity_extractor.extractor import EntityExtractionResult
from swarm_reasoning.agents.entity_extractor.tools import (
    _publish_entity_observations,
    extract_entities,
)
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.models.stream import ObsMessage


def _make_context(
    agent_name: str = "entity-extractor",
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


def _make_extraction_result(**kwargs) -> EntityExtractionResult:
    defaults = dict(persons=[], organizations=[], dates=[], locations=[], statistics=[])
    defaults.update(kwargs)
    return EntityExtractionResult(**defaults)


class TestPublishEntityObservations:
    @pytest.mark.asyncio
    async def test_publishes_in_deterministic_order(self):
        ctx = _make_context()
        result = _make_extraction_result(
            persons=["Alice"],
            organizations=["Acme"],
            dates=["20210101"],
            locations=["NYC"],
            statistics=["50%"],
        )

        count = await _publish_entity_observations(result, ctx)

        assert count == 5
        calls = ctx.stream.publish.call_args_list
        assert len(calls) == 5

        codes = [c[0][1].observation.code for c in calls]
        assert codes == [
            ObservationCode.ENTITY_PERSON,
            ObservationCode.ENTITY_ORG,
            ObservationCode.ENTITY_DATE,
            ObservationCode.ENTITY_LOCATION,
            ObservationCode.ENTITY_STATISTIC,
        ]

    @pytest.mark.asyncio
    async def test_monotonic_seq_via_context(self):
        ctx = _make_context()
        result = _make_extraction_result(persons=["Alice", "Bob"], organizations=["Acme"])

        await _publish_entity_observations(result, ctx)

        calls = ctx.stream.publish.call_args_list
        seqs = [c[0][1].observation.seq for c in calls]
        assert seqs == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_empty_result_publishes_nothing(self):
        ctx = _make_context()
        result = _make_extraction_result()

        count = await _publish_entity_observations(result, ctx)

        assert count == 0
        ctx.stream.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_date_normalization_applied(self):
        ctx = _make_context()
        result = _make_extraction_result(dates=["2021", "last Tuesday"])

        await _publish_entity_observations(result, ctx)

        calls = ctx.stream.publish.call_args_list
        # "2021" -> "20210101-20211231", note=None
        obs1: ObsMessage = calls[0][0][1]
        assert obs1.observation.value == "20210101-20211231"
        assert obs1.observation.note is None

        # "last Tuesday" -> "last Tuesday", note="date-not-normalized"
        obs2: ObsMessage = calls[1][0][1]
        assert obs2.observation.value == "last Tuesday"
        assert obs2.observation.note == "date-not-normalized"

    @pytest.mark.asyncio
    async def test_all_observations_use_st_value_type(self):
        ctx = _make_context()
        result = _make_extraction_result(persons=["Alice"], statistics=["50%"])

        await _publish_entity_observations(result, ctx)

        for c in ctx.stream.publish.call_args_list:
            msg: ObsMessage = c[0][1]
            assert msg.observation.value_type == ValueType.ST

    @pytest.mark.asyncio
    async def test_all_observations_use_final_status(self):
        ctx = _make_context()
        result = _make_extraction_result(persons=["Alice"])

        await _publish_entity_observations(result, ctx)

        msg: ObsMessage = ctx.stream.publish.call_args[0][1]
        assert msg.observation.status == "F"

    @pytest.mark.asyncio
    async def test_method_is_extract_entities(self):
        ctx = _make_context()
        result = _make_extraction_result(organizations=["NASA"])

        await _publish_entity_observations(result, ctx)

        msg: ObsMessage = ctx.stream.publish.call_args[0][1]
        assert msg.observation.method == "extract_entities"


class TestExtractEntitiesTool:
    @pytest.mark.asyncio
    async def test_calls_llm_and_publishes(self):
        ctx = _make_context()
        anthropic = AsyncMock(spec=AsyncAnthropic)
        extraction = _make_extraction_result(
            persons=["Joe Biden"], organizations=["White House"]
        )

        with patch(
            "swarm_reasoning.agents.entity_extractor.tools.extract_entities_llm",
            return_value=extraction,
        ) as mock_llm:
            result = await extract_entities.ainvoke(
                {
                    "claim_text": "Biden signed the order at the White House",
                    "context": ctx,
                    "anthropic_client": anthropic,
                }
            )

        mock_llm.assert_awaited_once_with(
            "Biden signed the order at the White House", anthropic
        )
        assert "2 entities" in result
        assert "1 person(s)" in result
        assert "1 org(s)" in result

    @pytest.mark.asyncio
    async def test_empty_extraction_returns_none_summary(self):
        ctx = _make_context()
        anthropic = AsyncMock(spec=AsyncAnthropic)
        extraction = _make_extraction_result()

        with patch(
            "swarm_reasoning.agents.entity_extractor.tools.extract_entities_llm",
            return_value=extraction,
        ):
            result = await extract_entities.ainvoke(
                {
                    "claim_text": "No entities here",
                    "context": ctx,
                    "anthropic_client": anthropic,
                }
            )

        assert "0 entities: none" in result

    @pytest.mark.asyncio
    async def test_publishes_correct_count_of_observations(self):
        ctx = _make_context()
        anthropic = AsyncMock(spec=AsyncAnthropic)
        extraction = _make_extraction_result(
            persons=["Alice", "Bob"],
            dates=["20210101"],
        )

        with patch(
            "swarm_reasoning.agents.entity_extractor.tools.extract_entities_llm",
            return_value=extraction,
        ):
            await extract_entities.ainvoke(
                {
                    "claim_text": "Alice and Bob met on Jan 1 2021",
                    "context": ctx,
                    "anthropic_client": anthropic,
                }
            )

        assert ctx.stream.publish.await_count == 3

    @pytest.mark.asyncio
    async def test_all_entity_types_in_summary(self):
        ctx = _make_context()
        anthropic = AsyncMock(spec=AsyncAnthropic)
        extraction = _make_extraction_result(
            persons=["A"],
            organizations=["B"],
            dates=["20210101"],
            locations=["C"],
            statistics=["50%"],
        )

        with patch(
            "swarm_reasoning.agents.entity_extractor.tools.extract_entities_llm",
            return_value=extraction,
        ):
            result = await extract_entities.ainvoke(
                {
                    "claim_text": "test claim",
                    "context": ctx,
                    "anthropic_client": anthropic,
                }
            )

        assert "5 entities" in result
        assert "1 person(s)" in result
        assert "1 org(s)" in result
        assert "1 date(s)" in result
        assert "1 location(s)" in result
        assert "1 statistic(s)" in result
