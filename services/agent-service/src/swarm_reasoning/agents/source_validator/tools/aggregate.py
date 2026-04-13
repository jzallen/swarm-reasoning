"""aggregate-citations tool: combines extraction, validation, and convergence into citations."""

from __future__ import annotations

import json
from typing import Annotated

from langchain_core.tools import InjectedToolArg, tool

from swarm_reasoning.agents.source_validator.aggregator import CitationAggregator
from swarm_reasoning.agents.source_validator.convergence import ConvergenceAnalyzer
from swarm_reasoning.agents.source_validator.models import (
    ExtractedUrl,
    UrlAssociation,
    ValidationResult,
    ValidationStatus,
)
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


def _deserialize_validations(data: dict[str, str]) -> dict[str, ValidationResult]:
    """Reconstruct ValidationResult objects from serialized status strings."""
    result = {}
    for url, status_str in data.items():
        result[url] = ValidationResult(url=url, status=ValidationStatus(status_str))
    return result


@tool
async def aggregate_citations(
    extracted_urls_json: str,
    validations_json: str,
    convergence_groups_json: str,
    context: Annotated[AgentContext, InjectedToolArg] = None,  # type: ignore[assignment]
) -> str:
    """Aggregate extracted URLs, validation results, and convergence into a citation list.

    Combines data from the extract, validate, and convergence tools into Citation
    objects sorted by agent and observation code. Publishes a CITATION_LIST
    observation (TX type, JSON array).

    Args:
        extracted_urls_json: JSON array of extracted URL objects from extract_urls.
        validations_json: JSON object mapping URL -> validation status from validate_urls.
        convergence_groups_json: JSON object mapping normalized URL -> agent count
            from compute_convergence_score.
        context: Injected AgentContext — not exposed to the LLM.

    Returns:
        JSON object with citation count and the full citation list.
    """
    raw_urls = json.loads(extracted_urls_json) if isinstance(extracted_urls_json, str) else extracted_urls_json
    raw_validations = json.loads(validations_json) if isinstance(validations_json, str) else validations_json
    raw_groups = json.loads(convergence_groups_json) if isinstance(convergence_groups_json, str) else convergence_groups_json

    extracted = _deserialize_extracted_urls(raw_urls)
    validations = _deserialize_validations(raw_validations)

    convergence_analyzer = ConvergenceAnalyzer()
    aggregator = CitationAggregator(convergence_analyzer)
    citations = aggregator.aggregate(extracted, validations, raw_groups)
    json_str = CitationAggregator.to_citation_list_json(citations)

    await context.publish_obs(
        code=ObservationCode.CITATION_LIST,
        value=json_str,
        value_type=ValueType.TX,
    )

    return json.dumps({
        "count": len(citations),
        "citations": [c.to_dict() for c in citations],
    })
