"""Pipeline activity: wraps the LangGraph claim-verification pipeline in a single Temporal activity.

The run_langgraph_pipeline activity:
1. Constructs initial PipelineState from the activity input
2. Creates a PipelineContext with Redis stream transport
3. Passes heartbeat callback and pipeline context via LangGraph's RunnableConfig
4. Invokes the compiled StateGraph
5. Returns a PipelineResult constructed from the final PipelineState

Design reference: ADR-0023 §D1, §D7; openspec temporal-simplification spec.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import redis.asyncio as aioredis
from temporalio import activity
from temporalio.exceptions import ApplicationError

from swarm_reasoning.config import RedisConfig
from swarm_reasoning.pipeline.context import PipelineContext
from swarm_reasoning.stream.redis import RedisReasoningStream
from swarm_reasoning.temporal.errors import (
    InvalidClaimError,
    MissingApiKeyError,
    NotCheckWorthyError,
)

logger = logging.getLogger(__name__)

# Non-retryable error types caught at the activity boundary.
_NON_RETRYABLE_ERRORS = (InvalidClaimError, MissingApiKeyError, NotCheckWorthyError)


@dataclass
class PipelineActivityInput:
    """Input for the run_langgraph_pipeline activity."""

    run_id: str
    session_id: str
    claim_text: str
    claim_url: str | None = None
    submission_date: str | None = None


@dataclass
class PipelineResult:
    """Output from the run_langgraph_pipeline activity.

    Constructed from the final PipelineState after graph execution.
    """

    run_id: str
    verdict: str | None = None
    confidence: float | None = None
    narrative: str | None = None
    is_check_worthy: bool = True
    errors: list[str] = field(default_factory=list)
    duration_ms: int = 0


def _build_initial_state(input: PipelineActivityInput) -> dict[str, Any]:
    """Construct the initial PipelineState dict from activity input.

    Returns a plain dict matching the PipelineState TypedDict shape.
    Fields not provided by the input default to None or empty collections.
    """
    return {
        # Claim input
        "claim_text": input.claim_text,
        "claim_url": input.claim_url,
        "submission_date": input.submission_date,
        "run_id": input.run_id,
        "session_id": input.session_id,
        # Intake output (populated by intake node)
        "normalized_claim": None,
        "claim_domain": None,
        "check_worthy_score": None,
        "entities": [],
        "is_check_worthy": None,
        # Evidence output (populated by evidence node)
        "claimreview_matches": [],
        "domain_sources": [],
        "evidence_confidence": None,
        # Coverage output (populated by coverage node)
        "coverage_left": [],
        "coverage_center": [],
        "coverage_right": [],
        "framing_analysis": None,
        # Validation output (populated by validation node)
        "validated_urls": [],
        "convergence_score": None,
        "citations": [],
        "blindspot_score": None,
        "blindspot_direction": None,
        # Synthesizer output (populated by synthesizer node)
        "verdict": None,
        "confidence": None,
        "narrative": None,
        "verdict_observations": [],
        # Metadata
        "observations": [],
        "errors": [],
    }


def _build_result(
    input: PipelineActivityInput,
    final_state: dict[str, Any],
    duration_ms: int,
) -> PipelineResult:
    """Construct a PipelineResult from the final PipelineState."""
    return PipelineResult(
        run_id=input.run_id,
        verdict=final_state.get("verdict"),
        confidence=final_state.get("confidence"),
        narrative=final_state.get("narrative"),
        is_check_worthy=bool(final_state.get("is_check_worthy", True)),
        errors=final_state.get("errors", []),
        duration_ms=duration_ms,
    )


def _make_heartbeat_callback() -> Any:
    """Create a heartbeat callback that forwards to Temporal's activity.heartbeat.

    Returns a callable(node_name: str) -> None that heartbeats with
    detail 'executing:{node_name}'.
    """

    def heartbeat(node_name: str) -> None:
        activity.heartbeat(f"executing:{node_name}")

    return heartbeat


@activity.defn
async def run_langgraph_pipeline(input: PipelineActivityInput) -> PipelineResult:
    """Execute the full LangGraph claim-verification pipeline.

    This is the single Temporal activity that wraps the entire LangGraph
    StateGraph. It:
    - Builds initial PipelineState from input
    - Passes heartbeat callback via RunnableConfig
    - Invokes the compiled graph
    - Catches non-retryable errors and wraps them as ApplicationError
    - Returns PipelineResult from the final state
    """
    start_time = time.monotonic()
    logger.info("Pipeline starting for run %s", input.run_id)

    # Heartbeat on entry
    activity.heartbeat("executing:pipeline_start")

    # Build initial state
    initial_state = _build_initial_state(input)

    # Import the compiled graph (deferred to avoid import-time side effects
    # and to allow the graph module to be developed independently in M0.3)
    from swarm_reasoning.pipeline.graph import pipeline_graph

    # Create stream transport and pipeline context for observation publishing
    redis_cfg = RedisConfig()
    stream = RedisReasoningStream(redis_cfg)
    redis_client = aioredis.Redis(host=redis_cfg.host, port=redis_cfg.port, db=redis_cfg.db)

    ctx = PipelineContext(
        stream=stream,
        redis_client=redis_client,
        run_id=input.run_id,
        session_id=input.session_id,
        heartbeat_callback=_make_heartbeat_callback(),
    )

    # Configure LangGraph with heartbeat callback and pipeline context
    config = {
        "configurable": {
            "pipeline_context": ctx,
            "heartbeat_callback": ctx.heartbeat_callback,
            "run_id": input.run_id,
            "session_id": input.session_id,
        }
    }

    try:
        # Invoke the compiled LangGraph pipeline
        final_state = await pipeline_graph.ainvoke(initial_state, config=config)
    except _NON_RETRYABLE_ERRORS as exc:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        logger.warning(
            "Pipeline non-retryable error for run %s after %dms: %s",
            input.run_id,
            elapsed_ms,
            exc,
        )
        raise ApplicationError(
            str(exc),
            type=type(exc).__name__,
            non_retryable=True,
        ) from exc
    finally:
        await stream.close()
        await redis_client.aclose()

    elapsed_ms = int((time.monotonic() - start_time) * 1000)
    result = _build_result(input, final_state, elapsed_ms)

    logger.info(
        "Pipeline completed for run %s: verdict=%s confidence=%s duration=%dms",
        input.run_id,
        result.verdict,
        result.confidence,
        elapsed_ms,
    )

    # Final heartbeat
    activity.heartbeat("executing:pipeline_complete")

    return result
