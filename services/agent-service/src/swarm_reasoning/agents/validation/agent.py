"""Validation agent -- LangGraph StateGraph (fixed 5-node sequence, no LLM).

Unlike LLM-driven agents that use create_react_agent, the validation agent
uses a fixed-sequence StateGraph because its 5 steps always execute in the
same order with deterministic routing.

Node sequence:
  1. extract_urls        -- extract + deduplicate URLs from upstream data
  2. validate_urls       -- HTTP HEAD validation with soft-404 detection
  3. compute_convergence -- convergence scoring across agents
  4. aggregate_citations -- combine extraction + validation + convergence
  5. analyze_blindspots  -- coverage gap detection + cross-spectrum corroboration

Accepts ValidationInput fields as graph state, returns ValidationOutput fields.
Publishes observations as side effects via PipelineContext.
"""

from __future__ import annotations

import logging
from typing import Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

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
from swarm_reasoning.agents.source_validator.validator import UrlValidator
from swarm_reasoning.agents.validation.models import ValidationInput, ValidationOutput
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext, get_pipeline_context

logger = logging.getLogger(__name__)

AGENT_NAME = "validation"


# ---------------------------------------------------------------------------
# Internal state for the validation StateGraph
# ---------------------------------------------------------------------------


class ValidationGraphState(TypedDict, total=False):
    """Internal state threaded through the validation StateGraph.

    Input fields are populated by the caller before invocation.
    Working fields are populated sequentially by each graph node.
    """

    # Input (provided at graph invocation)
    cross_agent_urls: list[dict]
    coverage_left: list[dict]
    coverage_center: list[dict]
    coverage_right: list[dict]

    # After extract_urls node
    extracted_urls: list  # list[ExtractedUrl] from LinkExtractor

    # After validate_urls node
    validations: dict  # dict[str, ValidationResult]
    validated_urls: list[dict]  # Output: URL validation results with status

    # After compute_convergence node
    convergence_score: float  # Output
    convergence_groups: dict  # dict[str, int]

    # After aggregate_citations node
    citations: list[dict]  # Output: serialized citation list

    # After analyze_blindspots node
    blindspot_score: float  # Output: coverage gap score
    blindspot_direction: str  # Output: CWE-coded blindspot direction


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


async def extract_urls_node(state: ValidationGraphState, config: RunnableConfig) -> dict:
    """Extract and deduplicate URLs from upstream cross-agent data.

    Publishes SOURCE_EXTRACTED_URL observation for each extracted URL.
    """
    ctx = _get_ctx(config)
    if ctx is not None:
        ctx.heartbeat(AGENT_NAME)

    cross_agent_urls = state.get("cross_agent_urls", [])

    extractor = LinkExtractor()
    extracted = extractor.extract_urls({"urls": cross_agent_urls})

    if ctx is not None:
        for eu in extracted:
            await ctx.publish_observation(
                agent=AGENT_NAME,
                code=ObservationCode.SOURCE_EXTRACTED_URL,
                value=eu.url,
                value_type=ValueType.ST,
            )

    logger.info("extract_urls_node: %d URLs extracted", len(extracted))
    return {"extracted_urls": extracted}


async def validate_urls_node(state: ValidationGraphState, config: RunnableConfig) -> dict:
    """Validate extracted URLs via HTTP HEAD with soft-404 detection.

    Publishes SOURCE_VALIDATION_STATUS for each validated URL.
    Also builds the validated_urls output list combining extraction
    associations with validation status.
    """
    ctx = _get_ctx(config)
    if ctx is not None:
        ctx.heartbeat(AGENT_NAME)

    extracted_urls: list[Any] = state.get("extracted_urls", [])

    urls = [eu.url for eu in extracted_urls]
    if not urls:
        logger.info("validate_urls_node: no URLs to validate")
        return {"validations": {}, "validated_urls": []}

    validator = UrlValidator()
    validations = await validator.validate_all(urls)

    if ctx is not None:
        for _url, result in validations.items():
            await ctx.publish_observation(
                agent=AGENT_NAME,
                code=ObservationCode.SOURCE_VALIDATION_STATUS,
                value=result.status.to_cwe(),
                value_type=ValueType.CWE,
            )

    # Build validated_urls output
    validated_urls = []
    for eu in extracted_urls:
        validation = validations.get(eu.url)
        status = validation.status.value if validation else "NOT_VALIDATED"
        validated_urls.append(
            {
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
            }
        )

    logger.info("validate_urls_node: %d URLs validated", len(validations))
    return {"validations": validations, "validated_urls": validated_urls}


async def compute_convergence_node(state: ValidationGraphState, config: RunnableConfig) -> dict:
    """Compute source convergence score across agents.

    Publishes SOURCE_CONVERGENCE_SCORE observation.
    """
    ctx = _get_ctx(config)
    if ctx is not None:
        ctx.heartbeat(AGENT_NAME)

    extracted_urls = state.get("extracted_urls", [])

    analyzer = ConvergenceAnalyzer()
    score = analyzer.compute_convergence_score(extracted_urls)
    groups = analyzer.get_convergence_groups(extracted_urls)

    if ctx is not None:
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.SOURCE_CONVERGENCE_SCORE,
            value=str(score),
            value_type=ValueType.NM,
            units="score",
            reference_range="0.0-1.0",
        )

    logger.info("compute_convergence_node: score=%.4f", score)
    return {"convergence_score": score, "convergence_groups": groups}


async def aggregate_citations_node(state: ValidationGraphState, config: RunnableConfig) -> dict:
    """Combine extraction, validation, and convergence into citations.

    Publishes CITATION_LIST observation with serialized JSON.
    Returns citations pre-serialized as list[dict].
    """
    ctx = _get_ctx(config)
    if ctx is not None:
        ctx.heartbeat(AGENT_NAME)

    extracted_urls = state.get("extracted_urls", [])
    validations: dict = state.get("validations", {})
    convergence_groups: dict = state.get("convergence_groups", {})

    convergence_analyzer = ConvergenceAnalyzer()
    aggregator = CitationAggregator(convergence_analyzer)
    citations = aggregator.aggregate(extracted_urls, validations, convergence_groups)
    json_str = CitationAggregator.to_citation_list_json(citations)

    if ctx is not None:
        await ctx.publish_observation(
            agent=AGENT_NAME,
            code=ObservationCode.CITATION_LIST,
            value=json_str,
            value_type=ValueType.TX,
        )

    logger.info("aggregate_citations_node: %d citations", len(citations))
    return {"citations": [c.to_dict() for c in citations]}


async def analyze_blindspots_node(state: ValidationGraphState, config: RunnableConfig) -> dict:
    """Detect coverage gaps and cross-spectrum corroboration.

    Publishes BLINDSPOT_SCORE, BLINDSPOT_DIRECTION, and
    CROSS_SPECTRUM_CORROBORATION observations.
    """
    ctx = _get_ctx(config)
    if ctx is not None:
        ctx.heartbeat(AGENT_NAME)

    convergence_score = state.get("convergence_score")

    coverage = _build_coverage_snapshot(state, convergence_score)

    score = compute_blindspot_score(coverage)
    direction = compute_blindspot_direction(coverage)
    corroboration, corroboration_note = compute_corroboration(coverage)

    if ctx is not None:
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

    logger.info("analyze_blindspots_node: score=%.4f, direction=%s", score, direction)
    return {"blindspot_score": score, "blindspot_direction": direction}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_ctx(config: RunnableConfig) -> PipelineContext | None:
    """Extract PipelineContext from config, returning None if absent."""
    try:
        return get_pipeline_context(config)
    except (KeyError, TypeError):
        return None


def _build_coverage_snapshot(
    state: ValidationGraphState, convergence_score: float | None
) -> CoverageSnapshot:
    """Build CoverageSnapshot from graph state coverage fields."""

    def _segment(articles: list[dict]) -> SegmentCoverage:
        if not articles:
            return SegmentCoverage(article_count=0, framing="ABSENT")
        framings = [a.get("framing", "") for a in articles if a.get("framing")]
        framing = framings[0] if framings else "PRESENT"
        return SegmentCoverage(article_count=len(articles), framing=framing)

    return CoverageSnapshot(
        left=_segment(state.get("coverage_left", [])),
        center=_segment(state.get("coverage_center", [])),
        right=_segment(state.get("coverage_right", [])),
        source_convergence_score=convergence_score,
    )


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_validation_graph() -> StateGraph:
    """Build the validation StateGraph: 5-node fixed sequence.

    extract_urls → validate_urls → compute_convergence →
    aggregate_citations → analyze_blindspots → END

    Returns a compiled graph that accepts ``ValidationGraphState`` input
    (minimally ``{"cross_agent_urls": [...], "coverage_*": [...]}``).
    """
    builder = StateGraph(ValidationGraphState)

    builder.add_node("extract_urls", extract_urls_node)
    builder.add_node("validate_urls", validate_urls_node)
    builder.add_node("compute_convergence", compute_convergence_node)
    builder.add_node("aggregate_citations", aggregate_citations_node)
    builder.add_node("analyze_blindspots", analyze_blindspots_node)

    builder.set_entry_point("extract_urls")
    builder.add_edge("extract_urls", "validate_urls")
    builder.add_edge("validate_urls", "compute_convergence")
    builder.add_edge("compute_convergence", "aggregate_citations")
    builder.add_edge("aggregate_citations", "analyze_blindspots")
    builder.add_edge("analyze_blindspots", END)

    return builder.compile()


# Module-level compiled graph
validation_graph = build_validation_graph()


# ---------------------------------------------------------------------------
# Backward-compatible entry point
# ---------------------------------------------------------------------------


async def run_validation_agent(input: ValidationInput, ctx: PipelineContext) -> ValidationOutput:
    """Run the validation agent via its StateGraph.

    Backward-compatible wrapper: accepts ValidationInput + PipelineContext,
    invokes the compiled graph, and returns ValidationOutput.

    Args:
        input: Pre-extracted upstream data (URLs and coverage segments).
        ctx: PipelineContext for observation publishing and heartbeats.

    Returns:
        ValidationOutput with validated_urls, convergence_score, citations,
        blindspot_score, and blindspot_direction.
    """
    ctx.heartbeat(AGENT_NAME)
    config: RunnableConfig = {"configurable": {"pipeline_context": ctx}}
    result = await validation_graph.ainvoke(dict(input), config=config)

    return ValidationOutput(
        validated_urls=result.get("validated_urls", []),
        convergence_score=result.get("convergence_score", 0.0),
        citations=result.get("citations", []),
        blindspot_score=result.get("blindspot_score", 0.0),
        blindspot_direction=result.get("blindspot_direction", "NONE"),
    )
