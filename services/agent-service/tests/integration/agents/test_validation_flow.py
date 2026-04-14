"""Integration tests for validation agent full flow."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.validation.handler import ValidationHandler
from swarm_reasoning.models.observation import ObservationCode
from swarm_reasoning.models.stream import ObsMessage, StartMessage, StopMessage


def _make_input(cross_agent_data: dict | None = None) -> MagicMock:
    inp = MagicMock()
    inp.run_id = "run-val-001"
    inp.agent_name = "validation"
    inp.claim_text = "Test claim"
    inp.cross_agent_data = cross_agent_data
    return inp


def _make_stream_mock() -> AsyncMock:
    stream_mock = AsyncMock()
    stream_mock.read_range = AsyncMock(return_value=[])
    stream_mock.publish = AsyncMock()
    stream_mock.close = AsyncMock()
    return stream_mock


def _coverage_data() -> dict:
    """Coverage segments from upstream coverage agents."""
    return {
        "left": {"article_count": 3, "framing": "SUPPORTIVE^Supportive^FCK"},
        "center": {"article_count": 5, "framing": "NEUTRAL^Neutral^FCK"},
        "right": {"article_count": 0, "framing": "ABSENT"},
    }


def _url_data(converging: bool = False) -> list[dict]:
    """URL association data from upstream agents."""
    urls = [
        {
            "url": "https://reuters.com/article/1",
            "associations": [
                {"agent": "coverage-left", "observation_code": "COVERAGE_TOP_SOURCE_URL", "source_name": "Reuters"},
            ],
        },
        {
            "url": "https://apnews.com/article/2",
            "associations": [
                {"agent": "coverage-center", "observation_code": "COVERAGE_TOP_SOURCE_URL", "source_name": "AP"},
            ],
        },
    ]
    if converging:
        # Same URL cited by multiple agents → convergence > 0
        urls.append({
            "url": "https://reuters.com/article/1",
            "associations": [
                {"agent": "domain-evidence", "observation_code": "DOMAIN_SOURCE_URL", "source_name": "Reuters"},
            ],
        })
    return urls


def _standard_cross_agent_data(converging: bool = False) -> dict:
    return {
        "urls": _url_data(converging=converging),
        "coverage": _coverage_data(),
    }


def _collect_obs(stream_mock: AsyncMock) -> list[ObsMessage]:
    """Extract ObsMessage objects from stream publish calls."""
    msgs = []
    for call in stream_mock.publish.call_args_list:
        msg = call[0][1]
        if isinstance(msg, ObsMessage):
            msgs.append(msg)
    return msgs


def _obs_codes(stream_mock: AsyncMock) -> list[ObservationCode]:
    return [m.observation.code for m in _collect_obs(stream_mock)]


class TestValidationFullFlow:
    @pytest.mark.asyncio
    async def test_happy_path_publishes_all_observations(self):
        """Full flow: convergence + 3 blindspot observations, STOP with F."""
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        with (
            patch("swarm_reasoning.agents.fanout_base.RedisReasoningStream", return_value=stream_mock),
            patch("swarm_reasoning.agents.fanout_base.aioredis.Redis", return_value=redis_mock),
            patch("swarm_reasoning.agents.fanout_base.activity"),
        ):
            handler = ValidationHandler()
            result = await handler.run(_make_input(_standard_cross_agent_data()))

        assert result.terminal_status == "F"
        assert result.agent_name == "validation"

        codes = _obs_codes(stream_mock)
        # 1 convergence + 3 blindspot = 4 observations
        assert ObservationCode.SOURCE_CONVERGENCE_SCORE in codes
        assert ObservationCode.BLINDSPOT_SCORE in codes
        assert ObservationCode.BLINDSPOT_DIRECTION in codes
        assert ObservationCode.CROSS_SPECTRUM_CORROBORATION in codes
        assert result.observation_count == 4

    @pytest.mark.asyncio
    async def test_convergence_score_passed_to_blindspots(self):
        """Convergence score from step 1 appears in blindspot analysis input."""
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        cross_data = _standard_cross_agent_data(converging=True)

        with (
            patch("swarm_reasoning.agents.fanout_base.RedisReasoningStream", return_value=stream_mock),
            patch("swarm_reasoning.agents.fanout_base.aioredis.Redis", return_value=redis_mock),
            patch("swarm_reasoning.agents.fanout_base.activity"),
        ):
            handler = ValidationHandler()
            result = await handler.run(_make_input(cross_data))

        assert result.terminal_status == "F"

        # Convergence score should be > 0 with converging URLs
        for obs in _collect_obs(stream_mock):
            if obs.observation.code == ObservationCode.SOURCE_CONVERGENCE_SCORE:
                assert float(obs.observation.value) > 0.0

    @pytest.mark.asyncio
    async def test_empty_urls_produces_zero_convergence(self):
        """No URLs → convergence 0.0, blindspot analysis still runs."""
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        cross_data = {"urls": [], "coverage": _coverage_data()}

        with (
            patch("swarm_reasoning.agents.fanout_base.RedisReasoningStream", return_value=stream_mock),
            patch("swarm_reasoning.agents.fanout_base.aioredis.Redis", return_value=redis_mock),
            patch("swarm_reasoning.agents.fanout_base.activity"),
        ):
            handler = ValidationHandler()
            result = await handler.run(_make_input(cross_data))

        assert result.terminal_status == "F"
        assert result.observation_count == 4

        for obs in _collect_obs(stream_mock):
            if obs.observation.code == ObservationCode.SOURCE_CONVERGENCE_SCORE:
                assert obs.observation.value == "0.0"

    @pytest.mark.asyncio
    async def test_missing_coverage_defaults_to_absent(self):
        """Missing coverage segments default to absent (score=1.0)."""
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        cross_data = {"urls": _url_data(), "coverage": {}}

        with (
            patch("swarm_reasoning.agents.fanout_base.RedisReasoningStream", return_value=stream_mock),
            patch("swarm_reasoning.agents.fanout_base.aioredis.Redis", return_value=redis_mock),
            patch("swarm_reasoning.agents.fanout_base.activity"),
        ):
            handler = ValidationHandler()
            result = await handler.run(_make_input(cross_data))

        assert result.terminal_status == "F"

        # All segments absent → blindspot score = 1.0
        for obs in _collect_obs(stream_mock):
            if obs.observation.code == ObservationCode.BLINDSPOT_SCORE:
                assert float(obs.observation.value) == 1.0

    @pytest.mark.asyncio
    async def test_no_cross_agent_data(self):
        """None cross_agent_data → convergence 0.0, all segments absent."""
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        with (
            patch("swarm_reasoning.agents.fanout_base.RedisReasoningStream", return_value=stream_mock),
            patch("swarm_reasoning.agents.fanout_base.aioredis.Redis", return_value=redis_mock),
            patch("swarm_reasoning.agents.fanout_base.activity"),
        ):
            handler = ValidationHandler()
            result = await handler.run(_make_input(None))

        assert result.terminal_status == "F"
        assert result.observation_count == 4

    @pytest.mark.asyncio
    async def test_start_stop_lifecycle(self):
        """START and STOP messages bracket the observations."""
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        with (
            patch("swarm_reasoning.agents.fanout_base.RedisReasoningStream", return_value=stream_mock),
            patch("swarm_reasoning.agents.fanout_base.aioredis.Redis", return_value=redis_mock),
            patch("swarm_reasoning.agents.fanout_base.activity"),
        ):
            handler = ValidationHandler()
            await handler.run(_make_input(_standard_cross_agent_data()))

        calls = stream_mock.publish.call_args_list
        assert isinstance(calls[0][0][1], StartMessage)
        assert isinstance(calls[-1][0][1], StopMessage)

        stop = calls[-1][0][1]
        assert stop.final_status == "F"
        assert stop.observation_count == 4

    @pytest.mark.asyncio
    async def test_progress_events(self):
        """Progress events published to progress:{runId}."""
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        with (
            patch("swarm_reasoning.agents.fanout_base.RedisReasoningStream", return_value=stream_mock),
            patch("swarm_reasoning.agents.fanout_base.aioredis.Redis", return_value=redis_mock),
            patch("swarm_reasoning.agents.fanout_base.activity"),
        ):
            handler = ValidationHandler()
            await handler.run(_make_input(_standard_cross_agent_data()))

        progress_messages = []
        for call in redis_mock.xadd.call_args_list:
            key = call[0][0]
            if key.startswith("progress:"):
                progress_messages.append(call[0][1]["message"])

        assert any("convergence" in m.lower() for m in progress_messages)
        assert any("blindspot" in m.lower() for m in progress_messages)

    @pytest.mark.asyncio
    async def test_observation_sequence_numbers(self):
        """Observations have sequential seq numbers 1..4."""
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        with (
            patch("swarm_reasoning.agents.fanout_base.RedisReasoningStream", return_value=stream_mock),
            patch("swarm_reasoning.agents.fanout_base.aioredis.Redis", return_value=redis_mock),
            patch("swarm_reasoning.agents.fanout_base.activity"),
        ):
            handler = ValidationHandler()
            await handler.run(_make_input(_standard_cross_agent_data()))

        seqs = [m.observation.seq for m in _collect_obs(stream_mock)]
        assert seqs == [1, 2, 3, 4]
