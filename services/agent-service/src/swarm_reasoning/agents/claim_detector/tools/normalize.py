"""normalize-claim tool: normalizes claim text and publishes CLAIM_NORMALIZED observation."""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.claim_detector.normalizer import normalize_claim_text
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType


@tool
async def normalize_claim(
    claim_text: str,
    entity_persons: list[str] | None = None,
    entity_orgs: list[str] | None = None,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Normalize a claim by removing hedging language, resolving pronouns, and standardizing text.

    Call this tool with the raw claim text from the ingestion stream. It applies
    a four-step normalization pipeline: lowercasing, hedge removal, pronoun
    resolution, and whitespace cleanup.

    Args:
        claim_text: The raw claim text to normalize.
        entity_persons: Named person entities for pronoun resolution (optional).
        entity_orgs: Named organization entities for pronoun resolution (optional).
        context: Injected AgentContext — not exposed to the LLM.

    Returns:
        The normalized claim text. Also publishes a CLAIM_NORMALIZED observation.
    """
    result = normalize_claim_text(
        claim_text,
        entity_persons=entity_persons,
        entity_orgs=entity_orgs,
    )

    note = None
    if result.fallback_used:
        note = "normalization: fallback to raw text"
    if result.hedges_removed:
        hedge_note = f"hedges removed: {', '.join(result.hedges_removed[:3])}"
        note = f"{note}; {hedge_note}" if note else hedge_note

    await context.publish_obs(
        code=ObservationCode.CLAIM_NORMALIZED,
        value=result.normalized,
        value_type=ValueType.ST,
        status="F",
        method="normalize_claim",
        note=note,
    )

    return result.normalized
