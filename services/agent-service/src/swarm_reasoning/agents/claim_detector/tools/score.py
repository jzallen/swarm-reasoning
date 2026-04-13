"""score-check-worthiness tool: LLM-powered scoring with gate decision."""

from __future__ import annotations

import json
import os
from typing import Annotated

from anthropic import AsyncAnthropic
from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.claim_detector.scorer import (
    CHECK_WORTHY_THRESHOLD,
    score_claim_text,
)
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.temporal.errors import MissingApiKeyError


@tool
async def score_check_worthiness(
    normalized_text: str,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
    anthropic_client: Annotated[AsyncAnthropic, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Score how check-worthy a normalized claim is using a two-pass LLM protocol.

    Call this tool AFTER normalizing the claim text. It performs:
    1. An initial scoring pass (0.0-1.0)
    2. A self-consistency confirmation pass
    3. A gate decision (proceed if score >= 0.4)

    Publishes CHECK_WORTHY_SCORE observations with P (preliminary) and F (final)
    epistemic statuses.

    Args:
        normalized_text: The normalized claim text to score.
        context: Injected AgentContext — not exposed to the LLM.
        anthropic_client: Injected Anthropic client — not exposed to the LLM.

    Returns:
        JSON string with score, rationale, proceed flag, and gate threshold.
    """
    client = anthropic_client
    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise MissingApiKeyError("ANTHROPIC_API_KEY is required for score_check_worthiness")
        client = AsyncAnthropic(api_key=api_key)

    score_result = await score_claim_text(normalized_text, client)

    score_note = (
        f"LLM rationale: {score_result.rationale[:480]}"
        if score_result.rationale
        else None
    )

    # Publish preliminary score (pass-1)
    if score_result.passes:
        await context.publish_obs(
            code=ObservationCode.CHECK_WORTHY_SCORE,
            value=f"{score_result.passes[0]:.2f}",
            value_type=ValueType.NM,
            status="P",
            method="score_claim",
            note=score_note,
            units="score",
            reference_range="0.0-1.0",
        )

    # Publish final resolved score
    await context.publish_obs(
        code=ObservationCode.CHECK_WORTHY_SCORE,
        value=f"{score_result.score:.2f}",
        value_type=ValueType.NM,
        status="F",
        method="score_claim",
        note=score_note,
        units="score",
        reference_range="0.0-1.0",
    )

    return json.dumps({
        "score": score_result.score,
        "rationale": score_result.rationale,
        "proceed": score_result.proceed,
        "threshold": CHECK_WORTHY_THRESHOLD,
    })
