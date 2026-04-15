"""Tests for run_langgraph_pipeline Temporal activity.

Tests cover:
- PipelineActivityInput/PipelineResult construction
- Initial state building
- Heartbeat callback behavior
- Non-retryable error wrapping
- Successful pipeline invocation with mock graph
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.activities.run_pipeline import (
    PipelineActivityInput,
    PipelineResult,
    _build_initial_state,
    _build_result,
    _make_heartbeat_callback,
    run_langgraph_pipeline,
)
from swarm_reasoning.temporal.errors import (
    InvalidClaimError,
    MissingApiKeyError,
    NotCheckWorthyError,
)


@contextmanager
def _mock_redis_infra():
    """Mock Redis stream and client so tests don't need a running Redis."""
    mock_stream = MagicMock()
    mock_stream.close = AsyncMock()
    mock_redis = MagicMock()
    mock_redis.aclose = AsyncMock()
    with (
        patch(
            "swarm_reasoning.activities.run_pipeline.RedisReasoningStream",
            return_value=mock_stream,
        ),
        patch(
            "swarm_reasoning.activities.run_pipeline.aioredis.Redis",
            return_value=mock_redis,
        ),
    ):
        yield mock_stream, mock_redis


# --- Input/Output construction tests ---


def test_pipeline_activity_input_minimal():
    """PipelineActivityInput requires run_id, session_id, claim_text."""
    inp = PipelineActivityInput(
        run_id="run-001",
        session_id="sess-001",
        claim_text="The earth is round.",
    )
    assert inp.run_id == "run-001"
    assert inp.session_id == "sess-001"
    assert inp.claim_text == "The earth is round."
    assert inp.claim_url is None
    assert inp.submission_date is None


def test_pipeline_activity_input_full():
    """PipelineActivityInput with all optional fields."""
    inp = PipelineActivityInput(
        run_id="run-002",
        session_id="sess-002",
        claim_text="Vaccines cause autism.",
        claim_url="https://example.com/claim",
        submission_date="2026-04-14",
    )
    assert inp.claim_url == "https://example.com/claim"
    assert inp.submission_date == "2026-04-14"


def test_pipeline_result_defaults():
    """PipelineResult has sensible defaults for optional fields."""
    result = PipelineResult(run_id="run-001")
    assert result.verdict is None
    assert result.confidence is None
    assert result.narrative is None
    assert result.is_check_worthy is True
    assert result.errors == []
    assert result.duration_ms == 0


# --- State building tests ---


def test_build_initial_state_minimal():
    """Initial state should populate claim input and default output fields."""
    inp = PipelineActivityInput(
        run_id="run-001",
        session_id="sess-001",
        claim_text="Test claim",
    )
    state = _build_initial_state(inp)

    # Claim input fields populated
    assert state["claim_text"] == "Test claim"
    assert state["run_id"] == "run-001"
    assert state["session_id"] == "sess-001"
    assert state["claim_url"] is None
    assert state["submission_date"] is None

    # Output fields default to None or empty
    assert state["normalized_claim"] is None
    assert state["entities"] == []
    assert state["is_check_worthy"] is None
    assert state["verdict"] is None
    assert state["confidence"] is None
    assert state["observations"] == []
    assert state["errors"] == []


def test_build_initial_state_with_optional_fields():
    """Initial state should carry optional claim_url and submission_date."""
    inp = PipelineActivityInput(
        run_id="run-002",
        session_id="sess-002",
        claim_text="Test claim",
        claim_url="https://example.com",
        submission_date="2026-04-14",
    )
    state = _build_initial_state(inp)
    assert state["claim_url"] == "https://example.com"
    assert state["submission_date"] == "2026-04-14"


def test_build_result_from_final_state():
    """PipelineResult should be constructed from the final state dict."""
    inp = PipelineActivityInput(
        run_id="run-001",
        session_id="sess-001",
        claim_text="Test claim",
    )
    final_state = {
        "verdict": "mostly-true",
        "confidence": 0.82,
        "narrative": "The claim is mostly accurate.",
        "is_check_worthy": True,
        "errors": ["coverage node failed"],
    }
    result = _build_result(inp, final_state, duration_ms=1500)

    assert result.run_id == "run-001"
    assert result.verdict == "mostly-true"
    assert result.confidence == 0.82
    assert result.narrative == "The claim is mostly accurate."
    assert result.is_check_worthy is True
    assert result.errors == ["coverage node failed"]
    assert result.duration_ms == 1500


def test_build_result_not_check_worthy():
    """PipelineResult correctly reflects is_check_worthy=False."""
    inp = PipelineActivityInput(
        run_id="run-001",
        session_id="sess-001",
        claim_text="Nice weather today.",
    )
    final_state = {
        "is_check_worthy": False,
        "verdict": None,
        "confidence": None,
    }
    result = _build_result(inp, final_state, duration_ms=200)
    assert result.is_check_worthy is False
    assert result.verdict is None


# --- Heartbeat callback tests ---


def test_heartbeat_callback_format():
    """Heartbeat callback should call activity.heartbeat with 'executing:{node_name}'."""
    with patch("swarm_reasoning.activities.run_pipeline.activity") as mock_activity:
        callback = _make_heartbeat_callback()
        callback("intake")
        mock_activity.heartbeat.assert_called_once_with("executing:intake")


def test_heartbeat_callback_multiple_nodes():
    """Heartbeat callback should work for multiple node names."""
    with patch("swarm_reasoning.activities.run_pipeline.activity") as mock_activity:
        callback = _make_heartbeat_callback()
        callback("evidence")
        callback("coverage")
        callback("synthesizer")
        assert mock_activity.heartbeat.call_count == 3
        mock_activity.heartbeat.assert_any_call("executing:evidence")
        mock_activity.heartbeat.assert_any_call("executing:coverage")
        mock_activity.heartbeat.assert_any_call("executing:synthesizer")


# --- Activity execution tests ---


@pytest.mark.asyncio
async def test_run_pipeline_success():
    """Successful pipeline invocation returns PipelineResult with verdict."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke.return_value = {
        "verdict": "true",
        "confidence": 0.95,
        "narrative": "Verified claim.",
        "is_check_worthy": True,
        "errors": [],
    }

    inp = PipelineActivityInput(
        run_id="run-001",
        session_id="sess-001",
        claim_text="Test claim",
    )

    with (
        _mock_redis_infra(),
        patch("swarm_reasoning.activities.run_pipeline.activity"),
        patch("swarm_reasoning.pipeline.graph.pipeline_graph", mock_graph),
    ):
        result = await run_langgraph_pipeline(inp)

    assert result.run_id == "run-001"
    assert result.verdict == "true"
    assert result.confidence == 0.95
    assert result.narrative == "Verified claim."
    assert result.duration_ms >= 0

    # Verify graph was called with correct initial state and config
    call_args = mock_graph.ainvoke.call_args
    initial_state = call_args[0][0]
    assert initial_state["claim_text"] == "Test claim"
    assert initial_state["run_id"] == "run-001"

    config = call_args[1]["config"]
    assert config["configurable"]["run_id"] == "run-001"
    assert config["configurable"]["session_id"] == "sess-001"
    assert callable(config["configurable"]["heartbeat_callback"])
    assert config["configurable"]["pipeline_context"] is not None


@pytest.mark.asyncio
async def test_run_pipeline_invalid_claim_error():
    """InvalidClaimError should be wrapped as non-retryable ApplicationError."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke.side_effect = InvalidClaimError("Empty claim text")

    inp = PipelineActivityInput(
        run_id="run-001",
        session_id="sess-001",
        claim_text="",
    )

    with (
        _mock_redis_infra(),
        patch("swarm_reasoning.activities.run_pipeline.activity"),
        patch("swarm_reasoning.pipeline.graph.pipeline_graph", mock_graph),
    ):
        from temporalio.exceptions import ApplicationError

        with pytest.raises(ApplicationError) as exc_info:
            await run_langgraph_pipeline(inp)

        assert exc_info.value.non_retryable is True
        assert exc_info.value.type == "InvalidClaimError"
        assert "Empty claim text" in str(exc_info.value)


@pytest.mark.asyncio
async def test_run_pipeline_not_check_worthy_error():
    """NotCheckWorthyError should be wrapped as non-retryable ApplicationError."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke.side_effect = NotCheckWorthyError("Score 0.2 below threshold")

    inp = PipelineActivityInput(
        run_id="run-001",
        session_id="sess-001",
        claim_text="Nice weather.",
    )

    with (
        _mock_redis_infra(),
        patch("swarm_reasoning.activities.run_pipeline.activity"),
        patch("swarm_reasoning.pipeline.graph.pipeline_graph", mock_graph),
    ):
        from temporalio.exceptions import ApplicationError

        with pytest.raises(ApplicationError) as exc_info:
            await run_langgraph_pipeline(inp)

        assert exc_info.value.non_retryable is True
        assert exc_info.value.type == "NotCheckWorthyError"


@pytest.mark.asyncio
async def test_run_pipeline_missing_api_key_error():
    """MissingApiKeyError should be wrapped as non-retryable ApplicationError."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke.side_effect = MissingApiKeyError("ANTHROPIC_API_KEY not set")

    inp = PipelineActivityInput(
        run_id="run-001",
        session_id="sess-001",
        claim_text="Test claim",
    )

    with (
        _mock_redis_infra(),
        patch("swarm_reasoning.activities.run_pipeline.activity"),
        patch("swarm_reasoning.pipeline.graph.pipeline_graph", mock_graph),
    ):
        from temporalio.exceptions import ApplicationError

        with pytest.raises(ApplicationError) as exc_info:
            await run_langgraph_pipeline(inp)

        assert exc_info.value.non_retryable is True
        assert exc_info.value.type == "MissingApiKeyError"


@pytest.mark.asyncio
async def test_run_pipeline_retryable_error_propagates():
    """Generic exceptions should propagate without non-retryable wrapping."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke.side_effect = RuntimeError("Redis connection lost")

    inp = PipelineActivityInput(
        run_id="run-001",
        session_id="sess-001",
        claim_text="Test claim",
    )

    with (
        _mock_redis_infra(),
        patch("swarm_reasoning.activities.run_pipeline.activity"),
        patch("swarm_reasoning.pipeline.graph.pipeline_graph", mock_graph),
    ):
        with pytest.raises(RuntimeError, match="Redis connection lost"):
            await run_langgraph_pipeline(inp)


@pytest.mark.asyncio
async def test_run_pipeline_heartbeats_on_entry_and_exit():
    """Activity should heartbeat at start and end of execution."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke.return_value = {
        "verdict": "false",
        "confidence": 0.9,
        "is_check_worthy": True,
        "errors": [],
    }

    inp = PipelineActivityInput(
        run_id="run-001",
        session_id="sess-001",
        claim_text="Test claim",
    )

    with (
        _mock_redis_infra(),
        patch("swarm_reasoning.activities.run_pipeline.activity") as mock_activity,
        patch("swarm_reasoning.pipeline.graph.pipeline_graph", mock_graph),
    ):
        await run_langgraph_pipeline(inp)

    # Should have heartbeated at start and end
    heartbeat_calls = [call[0][0] for call in mock_activity.heartbeat.call_args_list]
    assert "executing:pipeline_start" in heartbeat_calls
    assert "executing:pipeline_complete" in heartbeat_calls


@pytest.mark.asyncio
async def test_run_pipeline_config_has_heartbeat_callback():
    """The RunnableConfig passed to the graph should include a heartbeat callback."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke.return_value = {
        "verdict": "true",
        "confidence": 0.8,
        "is_check_worthy": True,
        "errors": [],
    }

    inp = PipelineActivityInput(
        run_id="run-001",
        session_id="sess-001",
        claim_text="Test claim",
    )

    with (
        _mock_redis_infra(),
        patch("swarm_reasoning.activities.run_pipeline.activity") as mock_activity,
        patch("swarm_reasoning.pipeline.graph.pipeline_graph", mock_graph),
    ):
        await run_langgraph_pipeline(inp)

        config = mock_graph.ainvoke.call_args[1]["config"]
        heartbeat_fn = config["configurable"]["heartbeat_callback"]

        # The callback should be callable
        assert callable(heartbeat_fn)

        # When called, it should heartbeat with the correct format
        heartbeat_fn("validation")
        mock_activity.heartbeat.assert_any_call("executing:validation")


@pytest.mark.asyncio
async def test_run_pipeline_config_has_pipeline_context():
    """The RunnableConfig should include a PipelineContext for observation publishing."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke.return_value = {
        "verdict": "true",
        "confidence": 0.8,
        "is_check_worthy": True,
        "errors": [],
    }

    inp = PipelineActivityInput(
        run_id="run-001",
        session_id="sess-001",
        claim_text="Test claim",
    )

    with (
        _mock_redis_infra(),
        patch("swarm_reasoning.activities.run_pipeline.activity"),
        patch("swarm_reasoning.pipeline.graph.pipeline_graph", mock_graph),
    ):
        await run_langgraph_pipeline(inp)

        config = mock_graph.ainvoke.call_args[1]["config"]
        ctx = config["configurable"]["pipeline_context"]

        # PipelineContext should be wired with correct identifiers
        from swarm_reasoning.pipeline.context import PipelineContext

        assert isinstance(ctx, PipelineContext)
        assert ctx.run_id == "run-001"
        assert ctx.session_id == "sess-001"
        assert callable(ctx.heartbeat_callback)


@pytest.mark.asyncio
async def test_run_pipeline_cleans_up_on_error():
    """Stream and Redis client should be closed even when pipeline raises."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke.side_effect = RuntimeError("boom")

    inp = PipelineActivityInput(
        run_id="run-001",
        session_id="sess-001",
        claim_text="Test claim",
    )

    with (
        _mock_redis_infra() as (mock_stream, mock_redis),
        patch("swarm_reasoning.activities.run_pipeline.activity"),
        patch("swarm_reasoning.pipeline.graph.pipeline_graph", mock_graph),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await run_langgraph_pipeline(inp)

        mock_stream.close.assert_awaited_once()
        mock_redis.aclose.assert_awaited_once()
