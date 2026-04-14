"""Validation pipeline node (M4.1) -- URL validation, convergence, blindspot analysis.

Executes 5 procedural tools in fixed order (no LLM routing):
  1. extract_source_urls  -- extract URLs from upstream evidence + coverage
  2. validate_urls        -- HTTP HEAD validation with soft-404 detection
  3. compute_convergence  -- convergence scoring across agents
  4. aggregate_citations  -- combine extraction + validation + convergence
  5. analyze_blindspots   -- coverage gap detection + cross-spectrum corroboration

Reads from PipelineState: claimreview_matches, domain_sources,
coverage_left, coverage_center, coverage_right.

Returns dict with: validated_urls, convergence_score, citations,
blindspot_score, blindspot_direction.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import RunnableConfig

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
from swarm_reasoning.agents.source_validator.models import (
    ValidationResult,
    ValidationStatus,
)
from swarm_reasoning.agents.source_validator.validator import UrlValidator
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext, get_pipeline_context
from swarm_reasoning.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

_AGENT_NAME = "validation"


# ---------------------------------------------------------------------------
# Tool 1: extract_source_urls
# ---------------------------------------------------------------------------


def _build_cross_agent_data(state: PipelineState) -> dict:
    """Build the cross-agent URL data structure from PipelineState fields.

    Extracts URL entries from claimreview_matches, domain_sources, and
    coverage_left/center/right, producing the format expected by LinkExtractor.
    """
    urls: list[dict[str, str]] = []

    # ClaimReview matches — each match may have a URL
    for match in state.get("claimreview_matches", []):
        url = match.get("url") or match.get("claimReview", {}).get("url", "")
        if url:
            urls.append({
                "url": url,
                "agent": "evidence",
                "code": "CLAIMREVIEW_URL",
                "source_name": match.get("publisher", match.get("source", "ClaimReview")),
            })

    # Domain sources — each has a URL and source name
    for source in state.get("domain_sources", []):
        url = source.get("url", "")
        if url:
            urls.append({
                "url": url,
                "agent": "evidence",
                "code": "DOMAIN_SOURCE_URL",
                "source_name": source.get("name", source.get("source_name", "Domain")),
            })

    # Coverage segments — left, center, right
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

    return {"urls": urls}


async def _extract_source_urls(
    state: PipelineState, ctx: PipelineContext
) -> list[Any]:
    """Tool 1: Extract and deduplicate URLs from upstream data."""
    cross_agent_data = _build_cross_agent_data(state)
    extractor = LinkExtractor()
    extracted = extractor.extract_urls(cross_agent_data)

    for eu in extracted:
        await ctx.publish_observation(
            agent=_AGENT_NAME,
            code=ObservationCode.SOURCE_EXTRACTED_URL,
            value=eu.url,
            value_type=ValueType.ST,
        )

    logger.info("extract_source_urls: %d URLs extracted", len(extracted))
    return extracted


# ---------------------------------------------------------------------------
# Tool 2: validate_urls
# ---------------------------------------------------------------------------


async def _validate_urls(
    extracted_urls: list[Any], ctx: PipelineContext
) -> dict[str, ValidationResult]:
    """Tool 2: Validate extracted URLs via HTTP HEAD."""
    urls = [eu.url for eu in extracted_urls]
    if not urls:
        logger.info("validate_urls: no URLs to validate")
        return {}

    validator = UrlValidator()
    validations = await validator.validate_all(urls)

    for _url, result in validations.items():
        await ctx.publish_observation(
            agent=_AGENT_NAME,
            code=ObservationCode.SOURCE_VALIDATION_STATUS,
            value=result.status.to_cwe(),
            value_type=ValueType.CWE,
        )

    logger.info("validate_urls: %d URLs validated", len(validations))
    return validations


# ---------------------------------------------------------------------------
# Tool 3: compute_convergence
# ---------------------------------------------------------------------------


async def _compute_convergence(
    extracted_urls: list[Any], ctx: PipelineContext
) -> tuple[float, dict[str, int]]:
    """Tool 3: Compute source convergence score across agents."""
    analyzer = ConvergenceAnalyzer()
    score = analyzer.compute_convergence_score(extracted_urls)
    groups = analyzer.get_convergence_groups(extracted_urls)

    await ctx.publish_observation(
        agent=_AGENT_NAME,
        code=ObservationCode.SOURCE_CONVERGENCE_SCORE,
        value=str(score),
        value_type=ValueType.NM,
        units="score",
        reference_range="0.0-1.0",
    )

    logger.info("compute_convergence: score=%.4f", score)
    return score, groups


# ---------------------------------------------------------------------------
# Tool 4: aggregate_citations
# ---------------------------------------------------------------------------


async def _aggregate_citations(
    extracted_urls: list[Any],
    validations: dict[str, ValidationResult],
    convergence_groups: dict[str, int],
    ctx: PipelineContext,
) -> list[Any]:
    """Tool 4: Combine extraction, validation, and convergence into citations."""
    convergence_analyzer = ConvergenceAnalyzer()
    aggregator = CitationAggregator(convergence_analyzer)
    citations = aggregator.aggregate(extracted_urls, validations, convergence_groups)
    json_str = CitationAggregator.to_citation_list_json(citations)

    await ctx.publish_observation(
        agent=_AGENT_NAME,
        code=ObservationCode.CITATION_LIST,
        value=json_str,
        value_type=ValueType.TX,
    )

    logger.info("aggregate_citations: %d citations", len(citations))
    return citations


# ---------------------------------------------------------------------------
# Tool 5: analyze_blindspots
# ---------------------------------------------------------------------------


def _build_coverage_snapshot(
    state: PipelineState, convergence_score: float | None
) -> CoverageSnapshot:
    """Build CoverageSnapshot from PipelineState coverage fields."""

    def _segment(articles: list[dict]) -> SegmentCoverage:
        if not articles:
            return SegmentCoverage(article_count=0, framing="ABSENT")
        # Derive framing from the articles if available
        framings = [a.get("framing", "") for a in articles if a.get("framing")]
        framing = framings[0] if framings else "PRESENT"
        return SegmentCoverage(article_count=len(articles), framing=framing)

    return CoverageSnapshot(
        left=_segment(state.get("coverage_left", [])),
        center=_segment(state.get("coverage_center", [])),
        right=_segment(state.get("coverage_right", [])),
        source_convergence_score=convergence_score,
    )


async def _analyze_blindspots(
    state: PipelineState,
    convergence_score: float | None,
    ctx: PipelineContext,
) -> tuple[float, str]:
    """Tool 5: Detect coverage gaps and cross-spectrum corroboration."""
    coverage = _build_coverage_snapshot(state, convergence_score)

    score = compute_blindspot_score(coverage)
    direction = compute_blindspot_direction(coverage)
    corroboration, corroboration_note = compute_corroboration(coverage)

    await ctx.publish_observation(
        agent=_AGENT_NAME,
        code=ObservationCode.BLINDSPOT_SCORE,
        value=str(score),
        value_type=ValueType.NM,
        units="score",
        reference_range="0.0-1.0",
    )

    await ctx.publish_observation(
        agent=_AGENT_NAME,
        code=ObservationCode.BLINDSPOT_DIRECTION,
        value=direction,
        value_type=ValueType.CWE,
    )

    await ctx.publish_observation(
        agent=_AGENT_NAME,
        code=ObservationCode.CROSS_SPECTRUM_CORROBORATION,
        value=corroboration,
        value_type=ValueType.CWE,
        note=corroboration_note,
    )

    logger.info("analyze_blindspots: score=%.4f, direction=%s", score, direction)
    return score, direction


# ---------------------------------------------------------------------------
# Node entry point
# ---------------------------------------------------------------------------


async def validation_node(state: PipelineState, config: RunnableConfig) -> dict:
    """Validation node: 5-tool procedural pipeline (no LLM routing).

    Reads upstream evidence and coverage data from PipelineState, runs
    extract -> validate -> convergence -> aggregate -> blindspots in fixed
    order, publishes observations, and returns state updates.
    """
    ctx = get_pipeline_context(config)
    ctx.heartbeat(_AGENT_NAME)

    await ctx.publish_progress(_AGENT_NAME, "Starting validation pipeline")

    # Tool 1: Extract URLs from upstream data
    extracted_urls = await _extract_source_urls(state, ctx)
    ctx.heartbeat(_AGENT_NAME)

    # Tool 2: Validate extracted URLs via HTTP
    validations = await _validate_urls(extracted_urls, ctx)
    ctx.heartbeat(_AGENT_NAME)

    # Tool 3: Compute convergence score
    convergence_score, convergence_groups = await _compute_convergence(
        extracted_urls, ctx
    )
    ctx.heartbeat(_AGENT_NAME)

    # Tool 4: Aggregate citations
    citations = await _aggregate_citations(
        extracted_urls, validations, convergence_groups, ctx
    )
    ctx.heartbeat(_AGENT_NAME)

    # Tool 5: Analyze blindspots
    blindspot_score, blindspot_direction = await _analyze_blindspots(
        state, convergence_score, ctx
    )
    ctx.heartbeat(_AGENT_NAME)

    # Build validated_urls list from extraction + validation results
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

    await ctx.publish_progress(
        _AGENT_NAME,
        f"Validation complete: {len(validated_urls)} URLs, "
        f"convergence={convergence_score:.2f}, blindspot={blindspot_score:.2f}",
    )

    return {
        "validated_urls": validated_urls,
        "convergence_score": convergence_score,
        "citations": [c.to_dict() for c in citations],
        "blindspot_score": blindspot_score,
        "blindspot_direction": blindspot_direction,
    }
