"""Citation aggregation — combines extraction, validation, and convergence data."""

from __future__ import annotations

import json

from swarm_reasoning.agents.source_validator.convergence import ConvergenceAnalyzer
from swarm_reasoning.agents.source_validator.models import (
    Citation,
    ExtractedUrl,
    ValidationResult,
)

# Minimum length for TX observation values
_TX_MIN_LENGTH = 201


class CitationAggregator:
    """Aggregates extracted URLs, validation results, and convergence into citations."""

    def __init__(self, convergence_analyzer: ConvergenceAnalyzer) -> None:
        self._convergence = convergence_analyzer

    def aggregate(
        self,
        extracted_urls: list[ExtractedUrl],
        validations: dict[str, ValidationResult],
        convergence_groups: dict[str, int],
    ) -> list[Citation]:
        """Combine data into Citation objects, one per (url, agent, code) tuple."""
        citations: list[Citation] = []

        for eu in extracted_urls:
            validation = validations.get(eu.url)
            if validation is not None:
                status_str = validation.status.to_citation_status()
            else:
                status_str = "not-validated"

            convergence_count = self._convergence.get_convergence_count(eu.url, convergence_groups)

            for assoc in eu.associations:
                citations.append(
                    Citation(
                        source_url=eu.url,
                        source_name=assoc.source_name,
                        agent=assoc.agent,
                        observation_code=assoc.observation_code,
                        validation_status=status_str,
                        convergence_count=convergence_count,
                    )
                )

        # Sort by agent name, then observation code
        citations.sort(key=lambda c: (c.agent, c.observation_code))
        return citations

    @staticmethod
    def to_citation_list_json(citations: list[Citation]) -> str:
        """Serialize citations to sorted JSON array for CITATION_LIST observation.

        Ensures the output exceeds 200 chars (TX value type requirement).
        """
        data = [c.to_dict() for c in citations]
        json_str = json.dumps(data, indent=2)
        # TX observations require >200 chars; pad with whitespace if needed
        if len(json_str) <= 200:
            json_str = json_str + " " * (_TX_MIN_LENGTH - len(json_str))
        return json_str
