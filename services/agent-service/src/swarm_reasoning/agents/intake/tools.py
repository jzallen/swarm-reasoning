"""@tool-decorated intake functions for LangChain agents (hq-423.39).

Wraps the deterministic ingest_claim and classify_domain functions as
LangChain @tool definitions. AgentContext is injected via InjectedToolArg
to provide stream, Redis, and Anthropic client access.
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.ingestion_agent.tools.claim_intake import (
    IngestionResult,
    StreamNotOpenError,
    StreamPublishError,
    ingest_claim as _ingest_claim,
)
from swarm_reasoning.agents.ingestion_agent.tools.domain_cls import (
    ClassificationServiceError,
    StreamStateError,
    classify_domain as _classify_domain,
)
from swarm_reasoning.agents.tool_runtime import AgentContext


@tool("validate_claim")
async def validate_claim(
    claim_text: str,
    source_url: str | None = None,
    source_date: str | None = None,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Validate a claim submission and publish CLAIM_TEXT/URL/DATE observations.

    Args:
        claim_text: The claim text to validate and ingest.
        source_url: Optional URL where the claim was found.
        source_date: Optional date of the claim source (any parseable format).
        context: Injected AgentContext — not exposed to the LLM.

    Returns:
        Confirmation of acceptance or rejection reason.
    """
    try:
        result: IngestionResult = await _ingest_claim(
            run_id=context.run_id,
            claim_text=claim_text,
            source_url=source_url,
            source_date=source_date,
            stream=context.stream,
            redis_client=context.redis_client,
        )
    except StreamNotOpenError as exc:
        return f"Error: stream already open — {exc}"
    except StreamPublishError as exc:
        return f"Error: failed to publish — {exc}"

    if result.accepted:
        date_info = f", normalized_date={result.normalized_date}" if result.normalized_date else ""
        return f"Claim accepted (run_id={result.run_id}{date_info})"
    return f"Claim rejected: {result.rejection_reason}"


@tool("classify_domain")
async def classify_domain(
    claim_text: str,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Classify a claim into a domain using LLM analysis.

    Must be called after validate_claim has accepted the claim for this run.

    Args:
        claim_text: The claim text to classify.
        context: Injected AgentContext — not exposed to the LLM.

    Returns:
        Domain classification with confidence level.
    """
    if context.anthropic_client is None:
        return "Error: no Anthropic client configured in AgentContext"

    try:
        result = await _classify_domain(
            run_id=context.run_id,
            claim_text=claim_text,
            stream=context.stream,
            anthropic_client=context.anthropic_client,
            redis_client=context.redis_client,
        )
    except StreamStateError as exc:
        return f"Error: stream precondition failed — {exc}"
    except ClassificationServiceError as exc:
        return f"Error: classification service — {exc}"

    return (
        f"Domain: {result.domain} "
        f"(confidence={result.confidence}, attempts={result.attempt_count})"
    )
