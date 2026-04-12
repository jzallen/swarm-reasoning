"""Shared observation @tool definitions for LangChain agents (ADR-004).

Provides publish_observation and publish_progress as @tool-decorated functions
that LangChain agents can invoke. Tools enforce the observation schema so LLMs
never generate raw observations directly. AgentContext is injected at runtime
via InjectedToolArg.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@tool
async def publish_observation(
    code: str,
    value: str,
    status: str = "F",
    method: str | None = None,
    note: str | None = None,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Publish a typed observation to the agent's reasoning stream.

    Args:
        code: Observation code from the OBX registry (e.g. CLAIM_TEXT,
              CHECK_WORTHY_SCORE, VERDICT).
        value: The observation value. Format depends on the code's value type:
               ST — short string (<= 200 chars),
               NM — numeric string parseable as float,
               CWE — coded value in CODE^Display^System format,
               TX — long text (> 200 chars).
        status: Epistemic status. P=preliminary, F=final, C=corrected,
                X=cancelled. Defaults to F.
        method: Optional method name that produced this observation.
        note: Optional free-text note (max 512 chars).
        context: Injected AgentContext — not exposed to the LLM.

    Returns:
        Confirmation message with the observation code and sequence number.
    """
    obs_code = ObservationCode(code)
    from swarm_reasoning.models.observation import get_code_metadata

    metadata = get_code_metadata(obs_code)
    value_type: ValueType = metadata["value_type"]

    await context.publish_obs(
        code=obs_code,
        value=value,
        value_type=value_type,
        status=status,
        method=method,
        note=note,
        units=metadata.get("units"),
        reference_range=metadata.get("reference_range"),
    )

    return f"Published {code} (seq={context.seq_counter}, status={status})"


@tool
async def publish_progress(
    message: str,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Publish a human-readable progress message for the frontend SSE stream.

    Args:
        message: Progress message displayed to the user (e.g. "Analyzing
                 coverage from left-leaning sources...").
        context: Injected AgentContext — not exposed to the LLM.

    Returns:
        Confirmation that the progress message was published.
    """
    try:
        await context.redis_client.xadd(
            f"progress:{context.run_id}",
            {
                "agent": context.agent_name,
                "message": message,
                "timestamp": _now_iso(),
            },
        )
    except Exception:
        logger.warning("Failed to publish progress for %s", context.agent_name)
        return f"Failed to publish progress: {message}"

    return f"Progress published: {message}"
