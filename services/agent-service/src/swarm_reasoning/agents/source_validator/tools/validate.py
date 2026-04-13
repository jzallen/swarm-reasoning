"""validate-urls tool: validates URLs via HTTP HEAD with soft-404 detection."""

from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.source_validator.validator import UrlValidator
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType


@tool
async def validate_urls(
    urls_json: str,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Validate source URLs via HTTP HEAD with redirect following and soft-404 detection.

    Validates all URLs concurrently with bounded concurrency (max 10). Each URL
    is checked via HEAD request; 405 responses fall back to GET. Publishes a
    SOURCE_VALIDATION_STATUS observation (CWE-coded) for each URL.

    Args:
        urls_json: JSON array of URL strings to validate.
        context: Injected AgentContext — not exposed to the LLM.

    Returns:
        JSON object mapping each URL to its validation status
        (LIVE, DEAD, REDIRECT, SOFT404, or TIMEOUT).
    """
    urls = json.loads(urls_json) if isinstance(urls_json, str) else urls_json

    validator = UrlValidator()
    validations = await validator.validate_all(urls)

    for url, result in validations.items():
        await context.publish_obs(
            code=ObservationCode.SOURCE_VALIDATION_STATUS,
            value=result.status.to_cwe(),
            value_type=ValueType.CWE,
        )

    return json.dumps({
        url: result.status.value for url, result in validations.items()
    })
