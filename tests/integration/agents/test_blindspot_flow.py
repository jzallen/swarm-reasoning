"""Integration tests for blindspot-detector agent full flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.blindspot_detector.activity import (
    BlindspotDetectorActivity,
)
from swarm_reasoning.models.observation import ObservationCode
from swarm_reasoning.models.stream import ObsMessage, StopMessage

# Shorthand aliases for long observation codes
_SCORE = ObservationCode.BLINDSPOT_SCORE
_DIR = ObservationCode.BLINDSPOT_DIRECTION
_CORR = ObservationCode.CROSS_SPECTRUM_CORROBORATION


def _make_input(cross_agent_data: dict | None = None) -> MagicMock:
    inp = MagicMock()
    inp.run_id = "run-bs-001"
    inp.agent_name = "blindspot-detector"
    inp.claim_text = "Test claim"
    inp.cross_agent_data = cross_agent_data
    return inp


def _make_stream_mock() -> AsyncMock:
    stream_mock = AsyncMock()
    stream_mock.read_range = AsyncMock(return_value=[])
    stream_mock.publish = AsyncMock()
    stream_mock.close = AsyncMock()
    return stream_mock


def _full_coverage_data(
    left_count: int = 12,
    left_framing: str = "SUPPORTIVE",
    center_count: int = 7,
    center_framing: str = "NEUTRAL",
    right_count: int = 3,
    right_framing: str = "CRITICAL",
    convergence: float | None = 0.35,
) -> dict:
    data: dict = {
        "coverage": {
            "left": {
                "article_count": left_count,
                "framing": left_framing,
            },
            "center": {
                "article_count": center_count,
                "framing": center_framing,
            },
            "right": {
                "article_count": right_count,
                "framing": right_framing,
            },
        },
    }
    if convergence is not None:
        data["source_convergence_score"] = convergence
    return data


def _collect_obs(stream_mock: AsyncMock) -> list[ObsMessage]:
    """Extract all ObsMessage instances from stream publish calls."""
    return [
        call[0][1]
        for call in stream_mock.publish.call_args_list
        if isinstance(call[0][1], ObsMessage)
    ]


def _obs_by_code(observations: list[ObsMessage], code: ObservationCode) -> list[ObsMessage]:
    """Filter observations by code."""
    return [o for o in observations if o.observation.code == code]


class TestBlindspotDetectorFullFlow:
    @pytest.mark.asyncio
    async def test_full_data_produces_3_observations_and_stop_f(self):
        """Full coverage data -> 3 F-status obs + STOP finalStatus=F."""
        cross_data = _full_coverage_data(right_count=0, right_framing="ABSENT")
        stream_mock = _make_stream_mock()
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
            handler = BlindspotDetectorActivity()
            result = await handler.run(_make_input(cross_data))

        assert result.terminal_status == "F"
        assert result.observation_count == 3

        observations = _collect_obs(stream_mock)
        assert len(observations) == 3

        codes = [obs.observation.code for obs in observations]
        assert _SCORE in codes
        assert _DIR in codes
        assert _CORR in codes

        # All status F
        for obs in observations:
            assert obs.observation.status == "F"

    @pytest.mark.asyncio
    async def test_empty_data_graceful_degradation(self):
        """Empty input -> score=1.0, direction=NONE, corr=FALSE, STOP F."""
        stream_mock = _make_stream_mock()
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
            handler = BlindspotDetectorActivity()
            result = await handler.run(_make_input({}))

        assert result.terminal_status == "F"
        assert result.observation_count == 3

        observations = _collect_obs(stream_mock)

        score_obs = _obs_by_code(observations, _SCORE)
        assert len(score_obs) == 1
        assert score_obs[0].observation.value == "1.0"

        dir_obs = _obs_by_code(observations, _DIR)
        assert len(dir_obs) == 1
        assert dir_obs[0].observation.value == "NONE^No Blindspot^FCK"

        corr_obs = _obs_by_code(observations, _CORR)
        assert len(corr_obs) == 1
        assert corr_obs[0].observation.value == "FALSE^Not Corroborated^FCK"

        # STOP with F
        stop_msgs = [
            call[0][1]
            for call in stream_mock.publish.call_args_list
            if isinstance(call[0][1], StopMessage)
        ]
        assert len(stop_msgs) == 1
        assert stop_msgs[0].final_status == "F"

    @pytest.mark.asyncio
    async def test_all_present_no_conflict_corroborated(self):
        """All present + no conflict -> score=0.0, corr=TRUE."""
        cross_data = _full_coverage_data(
            left_count=5,
            left_framing="SUPPORTIVE",
            center_count=3,
            center_framing="NEUTRAL",
            right_count=7,
            right_framing="NEUTRAL",
        )
        stream_mock = _make_stream_mock()
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
            handler = BlindspotDetectorActivity()
            await handler.run(_make_input(cross_data))

        observations = _collect_obs(stream_mock)

        score_obs = _obs_by_code(observations, _SCORE)
        assert score_obs[0].observation.value == "0.0"

        corr_obs = _obs_by_code(observations, _CORR)
        assert corr_obs[0].observation.value == "TRUE^Corroborated^FCK"

    @pytest.mark.asyncio
    async def test_conflicting_framing_not_corroborated(self):
        """SUPPORTIVE vs CRITICAL -> corr=FALSE even with all present."""
        cross_data = _full_coverage_data(
            left_count=5,
            left_framing="SUPPORTIVE",
            center_count=3,
            center_framing="NEUTRAL",
            right_count=7,
            right_framing="CRITICAL",
        )
        stream_mock = _make_stream_mock()
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
            handler = BlindspotDetectorActivity()
            await handler.run(_make_input(cross_data))

        observations = _collect_obs(stream_mock)
        corr_obs = _obs_by_code(observations, _CORR)
        assert corr_obs[0].observation.value == "FALSE^Not Corroborated^FCK"

    @pytest.mark.asyncio
    async def test_observation_ordering_seq_1_2_3(self):
        """Observations have sequential seq numbers 1, 2, 3."""
        cross_data = _full_coverage_data(
            right_count=0,
            right_framing="ABSENT",
        )
        stream_mock = _make_stream_mock()
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
            handler = BlindspotDetectorActivity()
            await handler.run(_make_input(cross_data))

        observations = _collect_obs(stream_mock)
        seq_numbers = [obs.observation.seq for obs in observations]
        assert seq_numbers == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_progress_events_published(self):
        """Progress events published to progress:{runId}."""
        cross_data = _full_coverage_data(
            right_count=0,
            right_framing="ABSENT",
        )
        stream_mock = _make_stream_mock()
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
            handler = BlindspotDetectorActivity()
            await handler.run(_make_input(cross_data))

        progress_messages = []
        for call in redis_mock.xadd.call_args_list:
            key = call[0][0]
            if key.startswith("progress:"):
                progress_messages.append(call[0][1]["message"])

        assert any("blindspot" in m.lower() for m in progress_messages)
        assert any("Blindspot score" in m for m in progress_messages)
        assert any("corroboration" in m.lower() for m in progress_messages)

    @pytest.mark.asyncio
    async def test_convergence_high_adds_note(self):
        """Convergence 0.8 + all present -> corroboration note."""
        cross_data = _full_coverage_data(
            left_count=5,
            left_framing="SUPPORTIVE",
            center_count=3,
            center_framing="SUPPORTIVE",
            right_count=7,
            right_framing="NEUTRAL",
            convergence=0.8,
        )
        stream_mock = _make_stream_mock()
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
            handler = BlindspotDetectorActivity()
            await handler.run(_make_input(cross_data))

        observations = _collect_obs(stream_mock)
        corr_obs = _obs_by_code(observations, _CORR)
        assert corr_obs[0].observation.value == "TRUE^Corroborated^FCK"
        assert corr_obs[0].observation.note is not None
        assert "convergence" in corr_obs[0].observation.note.lower()
        assert "0.80" in corr_obs[0].observation.note

    @pytest.mark.asyncio
    async def test_convergence_absent_no_note(self):
        """Convergence absent -> no convergence note."""
        cross_data = _full_coverage_data(
            left_count=5,
            left_framing="SUPPORTIVE",
            center_count=3,
            center_framing="SUPPORTIVE",
            right_count=7,
            right_framing="NEUTRAL",
            convergence=None,
        )
        stream_mock = _make_stream_mock()
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
            handler = BlindspotDetectorActivity()
            await handler.run(_make_input(cross_data))

        observations = _collect_obs(stream_mock)
        corr_obs = _obs_by_code(observations, _CORR)
        assert corr_obs[0].observation.value == "TRUE^Corroborated^FCK"
        assert corr_obs[0].observation.note is None
