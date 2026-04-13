"""Unit tests for analyze_blindspots @tool (score/direction/corroboration paths)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from swarm_reasoning.agents.blindspot_detector.tools import analyze_blindspots
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.models.stream import ObsMessage


def _make_context(
    agent_name: str = "blindspot-detector", run_id: str = "run-001"
) -> AgentContext:
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


def _full_coverage(
    left_count: int = 12,
    left_framing: str = "SUPPORTIVE",
    center_count: int = 7,
    center_framing: str = "NEUTRAL",
    right_count: int = 3,
    right_framing: str = "CRITICAL",
    convergence: float | None = 0.35,
) -> str:
    data: dict = {
        "coverage": {
            "left": {"article_count": left_count, "framing": left_framing},
            "center": {"article_count": center_count, "framing": center_framing},
            "right": {"article_count": right_count, "framing": right_framing},
        },
    }
    if convergence is not None:
        data["source_convergence_score"] = convergence
    return json.dumps(data)


def _collect_obs(ctx: AgentContext) -> list[ObsMessage]:
    return [call[0][1] for call in ctx.stream.publish.call_args_list]


def _obs_by_code(observations: list[ObsMessage], code: ObservationCode) -> list[ObsMessage]:
    return [o for o in observations if o.observation.code == code]


# ---- Tool: full coverage path ----


class TestAnalyzeBlindspotsFullCoverage:
    @pytest.mark.asyncio
    async def test_all_present_publishes_3_observations(self):
        ctx = _make_context()
        coverage = _full_coverage(right_count=5, right_framing="NEUTRAL")

        result = await analyze_blindspots.ainvoke(
            {"coverage_data": coverage, "context": ctx}
        )

        assert "score: 0.00" in result
        assert ctx.stream.publish.await_count == 3
        assert ctx.seq_counter == 3

    @pytest.mark.asyncio
    async def test_observation_codes(self):
        ctx = _make_context()
        coverage = _full_coverage(right_count=0, right_framing="ABSENT")

        await analyze_blindspots.ainvoke(
            {"coverage_data": coverage, "context": ctx}
        )

        obs = _collect_obs(ctx)
        codes = [o.observation.code for o in obs]
        assert codes == [
            ObservationCode.BLINDSPOT_SCORE,
            ObservationCode.BLINDSPOT_DIRECTION,
            ObservationCode.CROSS_SPECTRUM_CORROBORATION,
        ]

    @pytest.mark.asyncio
    async def test_observation_values_one_absent(self):
        ctx = _make_context()
        coverage = _full_coverage(right_count=0, right_framing="ABSENT")

        await analyze_blindspots.ainvoke(
            {"coverage_data": coverage, "context": ctx}
        )

        obs = _collect_obs(ctx)

        # BLINDSPOT_SCORE
        score_obs = obs[0]
        assert float(score_obs.observation.value) == pytest.approx(1 / 3, abs=0.01)
        assert score_obs.observation.value_type == ValueType.NM
        assert score_obs.observation.units == "score"
        assert score_obs.observation.reference_range == "0.0-1.0"

        # BLINDSPOT_DIRECTION
        dir_obs = obs[1]
        assert dir_obs.observation.value == "RIGHT^Right Absent^FCK"
        assert dir_obs.observation.value_type == ValueType.CWE

        # CROSS_SPECTRUM_CORROBORATION
        corr_obs = obs[2]
        assert corr_obs.observation.value == "FALSE^Not Corroborated^FCK"
        assert corr_obs.observation.value_type == ValueType.CWE


# ---- Tool: empty data path ----


class TestAnalyzeBlindspotsEmpty:
    @pytest.mark.asyncio
    async def test_empty_data_produces_maximum_blindspot(self):
        ctx = _make_context()
        coverage = json.dumps({})

        result = await analyze_blindspots.ainvoke(
            {"coverage_data": coverage, "context": ctx}
        )

        assert "score: 1.00" in result
        assert "MULTIPLE" in result

        obs = _collect_obs(ctx)
        score_obs = _obs_by_code(obs, ObservationCode.BLINDSPOT_SCORE)
        assert score_obs[0].observation.value == "1.0"

        dir_obs = _obs_by_code(obs, ObservationCode.BLINDSPOT_DIRECTION)
        assert dir_obs[0].observation.value == "MULTIPLE^Multiple Absent^FCK"


# ---- Tool: corroboration ----


class TestAnalyzeBlindspotsCorroboration:
    @pytest.mark.asyncio
    async def test_no_conflict_corroborated(self):
        ctx = _make_context()
        coverage = _full_coverage(
            left_framing="SUPPORTIVE",
            center_framing="NEUTRAL",
            right_count=5,
            right_framing="NEUTRAL",
        )

        await analyze_blindspots.ainvoke(
            {"coverage_data": coverage, "context": ctx}
        )

        obs = _collect_obs(ctx)
        corr_obs = _obs_by_code(obs, ObservationCode.CROSS_SPECTRUM_CORROBORATION)
        assert corr_obs[0].observation.value == "TRUE^Corroborated^FCK"

    @pytest.mark.asyncio
    async def test_conflict_not_corroborated(self):
        ctx = _make_context()
        coverage = _full_coverage(
            left_framing="SUPPORTIVE",
            right_count=7,
            right_framing="CRITICAL",
        )

        await analyze_blindspots.ainvoke(
            {"coverage_data": coverage, "context": ctx}
        )

        obs = _collect_obs(ctx)
        corr_obs = _obs_by_code(obs, ObservationCode.CROSS_SPECTRUM_CORROBORATION)
        assert corr_obs[0].observation.value == "FALSE^Not Corroborated^FCK"
        assert corr_obs[0].observation.note is None

    @pytest.mark.asyncio
    async def test_high_convergence_adds_note(self):
        ctx = _make_context()
        coverage = _full_coverage(
            left_framing="SUPPORTIVE",
            center_framing="SUPPORTIVE",
            right_count=7,
            right_framing="NEUTRAL",
            convergence=0.8,
        )

        await analyze_blindspots.ainvoke(
            {"coverage_data": coverage, "context": ctx}
        )

        obs = _collect_obs(ctx)
        corr_obs = _obs_by_code(obs, ObservationCode.CROSS_SPECTRUM_CORROBORATION)
        assert corr_obs[0].observation.value == "TRUE^Corroborated^FCK"
        assert corr_obs[0].observation.note is not None
        assert "0.80" in corr_obs[0].observation.note


# ---- Tool: return value ----


class TestAnalyzeBlindspotsReturnValue:
    @pytest.mark.asyncio
    async def test_return_includes_all_results(self):
        ctx = _make_context()
        coverage = _full_coverage(right_count=0, right_framing="ABSENT")

        result = await analyze_blindspots.ainvoke(
            {"coverage_data": coverage, "context": ctx}
        )

        assert "score:" in result
        assert "direction:" in result
        assert "corroboration:" in result

    @pytest.mark.asyncio
    async def test_no_blindspot_return(self):
        ctx = _make_context()
        coverage = _full_coverage(
            right_count=5,
            right_framing="NEUTRAL",
            left_framing="NEUTRAL",
            center_framing="NEUTRAL",
        )

        result = await analyze_blindspots.ainvoke(
            {"coverage_data": coverage, "context": ctx}
        )

        assert "score: 0.00" in result
        assert "NONE" in result
        assert "TRUE" in result
