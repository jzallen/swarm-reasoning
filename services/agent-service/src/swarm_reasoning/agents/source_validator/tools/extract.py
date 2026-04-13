"""extract-urls tool: extracts and deduplicates URLs from cross-agent data."""

from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.source_validator.extractor import LinkExtractor
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType


@tool
async def extract_urls(
    cross_agent_data: str,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Extract and deduplicate source URLs from cross-agent observation data.

    Parses URL entries from the cross-agent data, deduplicates by exact URL,
    rejects private/localhost/non-HTTP URLs, and publishes a SOURCE_EXTRACTED_URL
    observation for each unique valid URL.

    Args:
        cross_agent_data: JSON string of cross-agent data containing a "urls" array.
            Each entry has: url, agent, code, source_name.
        context: Injected AgentContext — not exposed to the LLM.

    Returns:
        JSON string with extracted URL count and URL list. Empty list if no valid
        URLs found.
    """
    data = json.loads(cross_agent_data) if isinstance(cross_agent_data, str) else cross_agent_data

    extractor = LinkExtractor()
    extracted = extractor.extract_urls(data)

    for eu in extracted:
        await context.publish_obs(
            code=ObservationCode.SOURCE_EXTRACTED_URL,
            value=eu.url,
            value_type=ValueType.ST,
        )

    return json.dumps({
        "count": len(extracted),
        "urls": [eu.url for eu in extracted],
    })
