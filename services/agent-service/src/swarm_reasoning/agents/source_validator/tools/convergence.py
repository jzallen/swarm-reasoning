"""compute-convergence-score tool: computes source convergence across agents."""

from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.source_validator.convergence import ConvergenceAnalyzer
from swarm_reasoning.agents.source_validator.models import ExtractedUrl, UrlAssociation
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType


def _deserialize_extracted_urls(data: list[dict]) -> list[ExtractedUrl]:
    """Reconstruct ExtractedUrl objects from serialized dicts."""
    result = []
    for entry in data:
        associations = [
            UrlAssociation(
                agent=a["agent"],
                observation_code=a["observation_code"],
                source_name=a["source_name"],
            )
            for a in entry.get("associations", [])
        ]
        result.append(ExtractedUrl(url=entry["url"], associations=associations))
    return result


@tool
async def compute_convergence_score(
    extracted_urls_json: str,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Compute source convergence score: (URLs cited by 2+ agents) / total unique URLs.

    Groups URLs by normalized form (strips www, query params, fragments, trailing
    slashes) and counts how many are cited by multiple agents. Publishes a
    SOURCE_CONVERGENCE_SCORE observation (0.0-1.0).

    Args:
        extracted_urls_json: JSON array of extracted URL objects, each with
            "url" and "associations" (list of {agent, observation_code, source_name}).
        context: Injected AgentContext — not exposed to the LLM.

    Returns:
        JSON object with convergence score and per-URL agent counts.
    """
    raw = json.loads(extracted_urls_json) if isinstance(extracted_urls_json, str) else extracted_urls_json
    extracted = _deserialize_extracted_urls(raw)

    analyzer = ConvergenceAnalyzer()
    score = analyzer.compute_convergence_score(extracted)
    groups = analyzer.get_convergence_groups(extracted)

    await context.publish_obs(
        code=ObservationCode.SOURCE_CONVERGENCE_SCORE,
        value=str(score),
        value_type=ValueType.NM,
        units="score",
        reference_range="0.0-1.0",
    )

    return json.dumps({
        "score": score,
        "convergence_groups": groups,
    })
