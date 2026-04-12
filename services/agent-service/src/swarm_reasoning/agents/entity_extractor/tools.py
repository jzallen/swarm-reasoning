"""Entity-extractor @tool definition for LangChain agents (ADR-004).

Provides extract_entities as a @tool-decorated async function that a LangChain
agent can invoke. The tool calls Claude structured output for NER, publishes
entity observations via AgentContext, and returns a summary. The Anthropic
client is injected at runtime via InjectedToolArg so the LLM only sees
claim_text as an input parameter.
"""

from __future__ import annotations

import logging
from typing import Annotated

from anthropic import AsyncAnthropic
from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.entity_extractor.extractor import (
    EntityExtractionResult,
    extract_entities_llm,
)
from swarm_reasoning.agents.entity_extractor.publisher import normalize_date
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType

logger = logging.getLogger(__name__)

# Deterministic publish order matching publisher.py
_ENTITY_ORDER: list[tuple[str, ObservationCode]] = [
    ("persons", ObservationCode.ENTITY_PERSON),
    ("organizations", ObservationCode.ENTITY_ORG),
    ("dates", ObservationCode.ENTITY_DATE),
    ("locations", ObservationCode.ENTITY_LOCATION),
    ("statistics", ObservationCode.ENTITY_STATISTIC),
]


async def _publish_entity_observations(
    result: EntityExtractionResult,
    context: AgentContext,
) -> int:
    """Publish entity observations in deterministic order via AgentContext.

    Returns the number of observations published.
    """
    count = 0
    for field_name, obs_code in _ENTITY_ORDER:
        entities: list[str] = getattr(result, field_name)
        for entity_value in entities:
            value = entity_value
            note: str | None = None

            if obs_code == ObservationCode.ENTITY_DATE:
                value, note = normalize_date(entity_value)

            await context.publish_obs(
                code=obs_code,
                value=value,
                value_type=ValueType.ST,
                status="F",
                method="extract_entities",
                note=note,
            )
            count += 1
    return count


@tool
async def extract_entities(
    claim_text: str,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
    anthropic_client: Annotated[AsyncAnthropic, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Extract named entities from a claim and publish them as observations.

    Performs named entity recognition (NER) on the given claim text, extracting
    persons, organizations, dates, locations, and statistics. Each entity is
    published as a typed observation to the agent's reasoning stream.

    Args:
        claim_text: The normalized claim text to extract entities from.
        context: Injected AgentContext — not exposed to the LLM.
        anthropic_client: Injected Anthropic client — not exposed to the LLM.

    Returns:
        Summary of extracted entities (counts per type).
    """
    result = await extract_entities_llm(claim_text, anthropic_client)

    count = await _publish_entity_observations(result, context)

    # Build summary
    parts = []
    if result.persons:
        parts.append(f"{len(result.persons)} person(s)")
    if result.organizations:
        parts.append(f"{len(result.organizations)} org(s)")
    if result.dates:
        parts.append(f"{len(result.dates)} date(s)")
    if result.locations:
        parts.append(f"{len(result.locations)} location(s)")
    if result.statistics:
        parts.append(f"{len(result.statistics)} statistic(s)")

    summary = ", ".join(parts) if parts else "none"
    return f"Extracted {count} entities: {summary}"
