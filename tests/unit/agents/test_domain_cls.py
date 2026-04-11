"""Unit tests for domain classification tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from swarm_reasoning.agents.ingestion_agent.tools.domain_cls import (
    DOMAIN_VOCABULARY,
    ClassificationResult,
    ClassificationServiceError,
    StreamStateError,
    build_prompt,
    classify_domain,
)
from swarm_reasoning.models.stream import ObsMessage, Phase, StartMessage, StopMessage


def _make_start(run_id: str = "run-1") -> StartMessage:
    return StartMessage(runId=run_id, agent="ingestion-agent", phase=Phase.INGESTION, timestamp="t")


def _make_obs_msg() -> ObsMessage:
    """Create a minimal OBS message for stream content."""
    from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType

    return ObsMessage(
        observation=Observation(
            runId="run-1",
            agent="ingestion-agent",
            seq=1,
            code=ObservationCode.CLAIM_TEXT,
            value="test claim",
            valueType=ValueType.ST,
            status="F",
            timestamp="t",
            method="ingest_claim",
        )
    )


def _make_stop(run_id: str = "run-1") -> StopMessage:
    return StopMessage(
        runId=run_id,
        agent="ingestion-agent",
        finalStatus="F",
        observationCount=3,
        timestamp="t",
    )


def _mock_claude_response(text: str) -> MagicMock:
    """Create a mock Anthropic message response."""
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_first_attempt(self):
        msgs = build_prompt("GDP grew 3%")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert "GDP grew 3%" in msgs[0]["content"]
        assert "previous response" not in msgs[0]["content"]

    def test_retry_has_suffix(self):
        msgs = build_prompt("GDP grew 3%", retry=True)
        assert "previous response was not recognized" in msgs[0]["content"]

    def test_all_codes_in_system_prompt(self):
        from swarm_reasoning.agents.ingestion_agent.tools.domain_cls import _SYSTEM_PROMPT

        for code in DOMAIN_VOCABULARY:
            assert code in _SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# classify_domain — happy path
# ---------------------------------------------------------------------------


class TestClassifyDomainHappyPath:
    @pytest.mark.asyncio
    async def test_first_attempt_success(self):
        stream = AsyncMock()
        stream.read_range.return_value = [
            _make_start(),
            _make_obs_msg(),
            _make_obs_msg(),
            _make_obs_msg(),
        ]
        stream.publish = AsyncMock()

        client = AsyncMock()
        client.messages.create.return_value = _mock_claude_response("ECONOMICS")

        redis_mock = AsyncMock()

        result = await classify_domain(
            "run-1",
            "GDP grew 3%",
            stream=stream,
            anthropic_client=client,
            redis_client=redis_mock,
        )

        assert isinstance(result, ClassificationResult)
        assert result.domain == "ECONOMICS"
        assert result.confidence == "HIGH"
        assert result.attempt_count == 1
        # Should publish: P obs, F obs, STOP = 3 publishes
        assert stream.publish.call_count == 3

    @pytest.mark.asyncio
    async def test_each_vocabulary_code(self):
        for code in DOMAIN_VOCABULARY:
            stream = AsyncMock()
            stream.read_range.return_value = [_make_start(), _make_obs_msg()]
            stream.publish = AsyncMock()

            client = AsyncMock()
            client.messages.create.return_value = _mock_claude_response(code)

            redis_mock = AsyncMock()

            result = await classify_domain(
                "run-1",
                "test claim",
                stream=stream,
                anthropic_client=client,
                redis_client=redis_mock,
            )
            assert result.domain == code


# ---------------------------------------------------------------------------
# classify_domain — retry and fallback
# ---------------------------------------------------------------------------


class TestClassifyDomainRetry:
    @pytest.mark.asyncio
    async def test_second_attempt_success(self):
        stream = AsyncMock()
        stream.read_range.return_value = [_make_start(), _make_obs_msg()]
        stream.publish = AsyncMock()

        client = AsyncMock()
        client.messages.create.side_effect = [
            _mock_claude_response("Finance"),  # invalid
            _mock_claude_response("ECONOMICS"),  # valid
        ]

        redis_mock = AsyncMock()

        result = await classify_domain(
            "run-1",
            "GDP grew 3%",
            stream=stream,
            anthropic_client=client,
            redis_client=redis_mock,
        )
        assert result.domain == "ECONOMICS"
        assert result.confidence == "HIGH"
        assert result.attempt_count == 2

    @pytest.mark.asyncio
    async def test_two_failures_fallback_to_other(self):
        stream = AsyncMock()
        stream.read_range.return_value = [_make_start(), _make_obs_msg()]
        stream.publish = AsyncMock()

        client = AsyncMock()
        client.messages.create.side_effect = [
            _mock_claude_response("Business"),
            _mock_claude_response("Business"),
        ]

        redis_mock = AsyncMock()

        result = await classify_domain(
            "run-1",
            "test claim",
            stream=stream,
            anthropic_client=client,
            redis_client=redis_mock,
        )
        assert result.domain == "OTHER"
        assert result.confidence == "LOW"
        assert result.attempt_count == 2
        # Should publish: F obs (fallback) + STOP = 2 publishes
        assert stream.publish.call_count == 2
        # Check fallback note in the observation
        obs_call = stream.publish.call_args_list[0]
        obs_msg = obs_call[0][1]
        assert obs_msg.type == "OBS"
        assert "fallback applied" in obs_msg.observation.note


# ---------------------------------------------------------------------------
# classify_domain — error cases
# ---------------------------------------------------------------------------


class TestClassifyDomainErrors:
    @pytest.mark.asyncio
    async def test_empty_stream_raises(self):
        stream = AsyncMock()
        stream.read_range.return_value = []

        with pytest.raises(StreamStateError):
            await classify_domain(
                "run-1",
                "test",
                stream=stream,
                anthropic_client=AsyncMock(),
                redis_client=AsyncMock(),
            )

    @pytest.mark.asyncio
    async def test_no_start_raises(self):
        stream = AsyncMock()
        stream.read_range.return_value = [_make_obs_msg()]

        with pytest.raises(StreamStateError, match="no START"):
            await classify_domain(
                "run-1",
                "test",
                stream=stream,
                anthropic_client=AsyncMock(),
                redis_client=AsyncMock(),
            )

    @pytest.mark.asyncio
    async def test_already_stopped_raises(self):
        stream = AsyncMock()
        stream.read_range.return_value = [_make_start(), _make_stop()]

        with pytest.raises(StreamStateError, match="already has a STOP"):
            await classify_domain(
                "run-1",
                "test",
                stream=stream,
                anthropic_client=AsyncMock(),
                redis_client=AsyncMock(),
            )

    @pytest.mark.asyncio
    async def test_api_connection_error(self):
        import anthropic

        stream = AsyncMock()
        stream.read_range.return_value = [_make_start(), _make_obs_msg()]

        client = AsyncMock()
        client.messages.create.side_effect = anthropic.APIConnectionError(request=MagicMock())

        with pytest.raises(ClassificationServiceError) as exc_info:
            await classify_domain(
                "run-1",
                "test",
                stream=stream,
                anthropic_client=client,
                redis_client=AsyncMock(),
            )
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_auth_error_non_retryable(self):
        import anthropic

        stream = AsyncMock()
        stream.read_range.return_value = [_make_start(), _make_obs_msg()]

        client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 401
        resp.headers = {}
        client.messages.create.side_effect = anthropic.AuthenticationError(
            message="Invalid key", response=resp, body=None
        )

        with pytest.raises(ClassificationServiceError) as exc_info:
            await classify_domain(
                "run-1",
                "test",
                stream=stream,
                anthropic_client=client,
                redis_client=AsyncMock(),
            )
        assert exc_info.value.retryable is False
