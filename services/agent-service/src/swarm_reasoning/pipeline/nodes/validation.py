"""Validation pipeline node -- translates PipelineState to/from ValidationInput/Output.

Thin wrapper around the validation agent module. Extracts upstream evidence
and coverage data from PipelineState, delegates to run_validation_agent(),
and returns state updates.
"""

from __future__ import annotations

import logging

from langgraph.types import RunnableConfig

from swarm_reasoning.agents.validation import (
    ValidationInput,
    run_validation_agent,
)
from swarm_reasoning.pipeline.context import get_pipeline_context
from swarm_reasoning.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

_AGENT_NAME = "validation"


# ---------------------------------------------------------------------------
# PipelineState → ValidationInput translation
# ---------------------------------------------------------------------------


def _build_cross_agent_urls(state: PipelineState) -> list[dict]:
    """Extract URL entries from PipelineState fields for the validation agent.

    Extracts URLs from claimreview_matches, domain_sources, and
    coverage_left/center/right, producing the list expected by ValidationInput.
    """
    urls: list[dict] = []

    # ClaimReview matches -- each match may have a URL
    for match in state.get("claimreview_matches", []):
        url = match.get("url") or match.get("claimReview", {}).get("url", "")
        if url:
            urls.append({
                "url": url,
                "agent": "evidence",
                "code": "CLAIMREVIEW_URL",
                "source_name": match.get("publisher", match.get("source", "ClaimReview")),
            })

    # Domain sources -- each has a URL and source name
    for source in state.get("domain_sources", []):
        url = source.get("url", "")
        if url:
            urls.append({
                "url": url,
                "agent": "evidence",
                "code": "DOMAIN_SOURCE_URL",
                "source_name": source.get("name", source.get("source_name", "Domain")),
            })

    # Coverage segments -- left, center, right
    for segment_name, state_key in [
        ("coverage-left", "coverage_left"),
        ("coverage-center", "coverage_center"),
        ("coverage-right", "coverage_right"),
    ]:
        for article in state.get(state_key, []):
            url = article.get("url", "")
            if url:
                urls.append({
                    "url": url,
                    "agent": segment_name,
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": article.get("source", article.get("source_name", segment_name)),
                })

    return urls


def _build_validation_input(state: PipelineState) -> ValidationInput:
    """Translate PipelineState into ValidationInput."""
    return ValidationInput(
        cross_agent_urls=_build_cross_agent_urls(state),
        coverage_left=state.get("coverage_left", []),
        coverage_center=state.get("coverage_center", []),
        coverage_right=state.get("coverage_right", []),
    )


# ---------------------------------------------------------------------------
# Node entry point
# ---------------------------------------------------------------------------


async def run_validation(state: PipelineState, config: RunnableConfig) -> dict:
    """Validation pipeline node: delegates to the validation agent.

    Translates PipelineState → ValidationInput, runs the procedural
    validation agent, and returns state updates.
    """
    ctx = get_pipeline_context(config)

    await ctx.publish_progress(_AGENT_NAME, "Starting validation pipeline")

    input = _build_validation_input(state)
    output = await run_validation_agent(input, ctx)

    await ctx.publish_progress(
        _AGENT_NAME,
        f"Validation complete: {len(output['validated_urls'])} URLs, "
        f"convergence={output['convergence_score']:.2f}, "
        f"blindspot={output['blindspot_score']:.2f}",
    )

    return dict(output)
