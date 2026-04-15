"""Validation agent -- procedural 5-tool chain (no LLM).

Executes in fixed order:
  1. extract_source_urls  -- extract + deduplicate URLs from upstream data
  2. validate_urls        -- HTTP HEAD validation with soft-404 detection
  3. compute_convergence  -- convergence scoring across agents
  4. aggregate_citations  -- combine extraction + validation + convergence
  5. analyze_blindspots   -- coverage gap detection + cross-spectrum corroboration

Accepts ValidationInput + PipelineContext, returns ValidationOutput.
Publishes observations as side effects via PipelineContext.
"""

from __future__ import annotations

import logging
from typing import Any

from swarm_reasoning.agents.blindspot_detector.analysis import (
    compute_blindspot_direction,
    compute_blindspot_score,
    compute_corroboration,
)
from swarm_reasoning.agents.blindspot_detector.models import (
    CoverageSnapshot,
    SegmentCoverage,
)
from swarm_reasoning.agents.source_validator.aggregator import CitationAggregator
from swarm_reasoning.agents.source_validator.convergence import ConvergenceAnalyzer
from swarm_reasoning.agents.source_validator.extractor import LinkExtractor
from swarm_reasoning.agents.source_validator.models import ValidationResult
from swarm_reasoning.agents.source_validator.validator import UrlValidator
from swarm_reasoning.agents.validation.models import ValidationInput, ValidationOutput
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext

logger = logging.getLogger(__name__)

AGENT_NAME = "validation"


# ---------------------------------------------------------------------------
# Step 1: extract source URLs
# ---------------------------------------------------------------------------


async def _extract_source_urls(
    cross_agent_urls: list[dict], ctx: PipelineContext
) -> list[Any]:
    """Extract and deduplicate URLs from upstream cross-agent data."""
    extractor = LinkExtractor()
    extracted = extractor.extract_urls({"urls": cross_agent_urls})

    for eu in extracted:
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.SOURCE_EXTRACTED_URL,
            value=eu.url,
            value_type=ValueType.ST,
        )

    logger.info("extract_source_urls: %d URLs extracted", len(extracted))
    return extracted


# ---------------------------------------------------------------------------
# Step 2: validate URLs
# ---------------------------------------------------------------------------


async def _validate_urls(
    extracted_urls: list[Any], ctx: PipelineContext
) -> dict[str, ValidationResult]:
    """Validate extracted URLs via HTTP HEAD with soft-404 detection."""
    urls = [eu.url for eu in extracted_urls]
    if not urls:
        logger.info("validate_urls: no URLs to validate")
        return {}

    validator = UrlValidator()
    validations = await validator.validate_all(urls)

    for _url, result in validations.items():
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.SOURCE_VALIDATION_STATUS,
            value=result.status.to_cwe(),
            value_type=ValueType.CWE,
        )

    logger.info("validate_urls: %d URLs validated", len(validations))
    return validations


# ---------------------------------------------------------------------------
# Step 3: compute convergence
# ---------------------------------------------------------------------------


async def _compute_convergence(
    extracted_urls: list[Any], ctx: PipelineContext
) -> tuple[float, dict[str, int]]:
    """Compute source convergence score across agents."""
    analyzer = ConvergenceAnalyzer()
    score = analyzer.compute_convergence_score(extracted_urls)
    groups = analyzer.get_convergence_groups(extracted_urls)

    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.SOURCE_CONVERGENCE_SCORE,
        value=str(score),
        value_type=ValueType.NM,
        units="score",
        reference_range="0.0-1.0",
    )

    logger.info("compute_convergence: score=%.4f", score)
    return score, groups


# ---------------------------------------------------------------------------
# Step 4: aggregate citations
# ---------------------------------------------------------------------------


async def _aggregate_citations(
    extracted_urls: list[Any],
    validations: dict[str, ValidationResult],
    convergence_groups: dict[str, int],
    ctx: PipelineContext,
) -> list[Any]:
    """Combine extraction, validation, and convergence into citations."""
    convergence_analyzer = ConvergenceAnalyzer()
    aggregator = CitationAggregator(convergence_analyzer)
    citations = aggregator.aggregate(extracted_urls, validations, convergence_groups)
    json_str = CitationAggregator.to_citation_list_json(citations)

    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CITATION_LIST,
        value=json_str,
        value_type=ValueType.TX,
    )

    logger.info("aggregate_citations: %d citations", len(citations))
    return citations


# ---------------------------------------------------------------------------
# Step 5: analyze blindspots
# ---------------------------------------------------------------------------


def _build_coverage_snapshot(
    input: ValidationInput, convergence_score: float | None
) -> CoverageSnapshot:
    """Build CoverageSnapshot from ValidationInput coverage fields."""

    def _segment(articles: list[dict]) -> SegmentCoverage:
        if not articles:
            return SegmentCoverage(article_count=0, framing="ABSENT")
        framings = [a.get("framing", "") for a in articles if a.get("framing")]
        framing = framings[0] if framings else "PRESENT"
        return SegmentCoverage(article_count=len(articles), framing=framing)

    return CoverageSnapshot(
        left=_segment(input["coverage_left"]),
        center=_segment(input["coverage_center"]),
        right=_segment(input["coverage_right"]),
        source_convergence_score=convergence_score,
    )


async def _analyze_blindspots(
    input: ValidationInput,
    convergence_score: float | None,
    ctx: PipelineContext,
) -> tuple[float, str]:
    """Detect coverage gaps and cross-spectrum corroboration."""
    coverage = _build_coverage_snapshot(input, convergence_score)

    score = compute_blindspot_score(coverage)
    direction = compute_blindspot_direction(coverage)
    corroboration, corroboration_note = compute_corroboration(coverage)

    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.BLINDSPOT_SCORE,
        value=str(score),
        value_type=ValueType.NM,
        units="score",
        reference_range="0.0-1.0",
    )

    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.BLINDSPOT_DIRECTION,
        value=direction,
        value_type=ValueType.CWE,
    )

    await ctx.publish_observation(
        agent=AGENT_NAME,
        code=ObservationCode.CROSS_SPECTRUM_CORROBORATION,
        value=corroboration,
        value_type=ValueType.CWE,
        note=corroboration_note,
    )

    logger.info("analyze_blindspots: score=%.4f, direction=%s", score, direction)
    return score, direction


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------


async def run_validation_agent(
    input: ValidationInput, ctx: PipelineContext
) -> ValidationOutput:
    """Run the validation agent: 5-step procedural pipeline (no LLM).

    Args:
        input: Pre-extracted upstream data (URLs and coverage segments).
        ctx: PipelineContext for observation publishing and heartbeats.

    Returns:
        ValidationOutput with validated_urls, convergence_score, citations,
        blindspot_score, and blindspot_direction.
    """
    ctx.heartbeat(AGENT_NAME)

    # Step 1: Extract URLs from upstream data
    extracted_urls = await _extract_source_urls(input["cross_agent_urls"], ctx)
    ctx.heartbeat(AGENT_NAME)

    # Step 2: Validate extracted URLs via HTTP
    validations = await _validate_urls(extracted_urls, ctx)
    ctx.heartbeat(AGENT_NAME)

    # Step 3: Compute convergence score
    convergence_score, convergence_groups = await _compute_convergence(
        extracted_urls, ctx
    )
    ctx.heartbeat(AGENT_NAME)

    # Step 4: Aggregate citations
    citations = await _aggregate_citations(
        extracted_urls, validations, convergence_groups, ctx
    )
    ctx.heartbeat(AGENT_NAME)

    # Step 5: Analyze blindspots
    blindspot_score, blindspot_direction = await _analyze_blindspots(
        input, convergence_score, ctx
    )
    ctx.heartbeat(AGENT_NAME)

    # Build validated_urls list
    validated_urls = []
    for eu in extracted_urls:
        validation = validations.get(eu.url)
        status = validation.status.value if validation else "NOT_VALIDATED"
        validated_urls.append({
            "url": eu.url,
            "status": status,
            "associations": [
                {
                    "agent": a.agent,
                    "observation_code": a.observation_code,
                    "source_name": a.source_name,
                }
                for a in eu.associations
            ],
        })

    return ValidationOutput(
        validated_urls=validated_urls,
        convergence_score=convergence_score,
        citations=[c.to_dict() for c in citations],
        blindspot_score=blindspot_score,
        blindspot_direction=blindspot_direction,
    )
