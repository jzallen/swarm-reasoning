"""Pipeline graph skeleton -- StateGraph with placeholder nodes (M0.3).

Defines the claim verification pipeline as a LangGraph StateGraph with 5 nodes:
intake, evidence, coverage, validation, synthesizer.

Graph topology:
    START -> intake -> route_after_intake
        -> [evidence, coverage] (parallel via Send) -> validation -> synthesizer -> END
        -> synthesizer (not-check-worthy shortcut)

Placeholder nodes return empty dicts. M1-M5 replace them with real implementations.
"""

from __future__ import annotations

import logging

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from swarm_reasoning.pipeline.nodes.synthesizer import synthesizer_node
from swarm_reasoning.pipeline.nodes.validation import validation_node
from swarm_reasoning.pipeline.state import PipelineState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Placeholder nodes -- replaced by real implementations in M1-M5
# ---------------------------------------------------------------------------


async def intake_node(state: PipelineState) -> dict:
    """Placeholder: intake (M1) -- claim intake, entity extraction, check-worthiness."""
    logger.info("intake_node: placeholder (no-op)")
    return {}


async def evidence_node(state: PipelineState) -> dict:
    """Placeholder: evidence (M2) -- fact-check lookups and domain evidence."""
    logger.info("evidence_node: placeholder (no-op)")
    return {}


async def coverage_node(state: PipelineState) -> dict:
    """Placeholder: coverage (M3) -- left/center/right news coverage analysis."""
    logger.info("coverage_node: placeholder (no-op)")
    return {}


# validation_node: imported from pipeline.nodes.validation (M4.1)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def route_after_intake(state: PipelineState) -> list[Send]:
    """Route after intake: fan-out to evidence+coverage, or shortcut to synthesizer.

    - Not check-worthy -> skip directly to synthesizer
    - Check-worthy -> parallel dispatch to evidence and coverage via Send API
    """
    if not state.get("is_check_worthy", True):
        logger.info("route_after_intake: not check-worthy, skipping to synthesizer")
        return [Send("synthesizer", state)]

    logger.info("route_after_intake: fan-out to evidence + coverage")
    return [Send("evidence", state), Send("coverage", state)]


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_pipeline_graph() -> StateGraph:
    """Build and compile the claim verification pipeline graph.

    Returns a compiled StateGraph ready for invocation.
    """
    builder = StateGraph(PipelineState)

    # --- Nodes ---
    builder.add_node("intake", intake_node)
    builder.add_node("evidence", evidence_node)
    builder.add_node("coverage", coverage_node)
    builder.add_node("validation", validation_node)
    builder.add_node("synthesizer", synthesizer_node)

    # --- Edges ---
    # Entry: always start with intake
    builder.set_entry_point("intake")

    # After intake: conditional fan-out (or not-check-worthy shortcut)
    builder.add_conditional_edges("intake", route_after_intake)

    # Fan-in: evidence and coverage both converge to validation
    builder.add_edge("evidence", "validation")
    builder.add_edge("coverage", "validation")

    # Sequential tail: validation -> synthesizer -> END
    builder.add_edge("validation", "synthesizer")
    builder.add_edge("synthesizer", END)

    return builder.compile()


# Module-level compiled graph (importable as ``pipeline_graph``)
pipeline_graph = build_pipeline_graph()
