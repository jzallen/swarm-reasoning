"""Pipeline graph -- StateGraph with 5 nodes for claim verification.

Defines the claim verification pipeline as a LangGraph StateGraph with 5 nodes:
intake, evidence, coverage, validation, synthesizer.

Graph topology:
    START -> intake -> route_after_intake
        -> [evidence, coverage] (parallel via Send) -> validation -> synthesizer -> END
        -> synthesizer (not-check-worthy shortcut)

Wired nodes: intake (M1.2), evidence (M2.2), coverage (M3.2),
validation (M4.1), synthesizer (M5.1).
"""

from __future__ import annotations

import logging
import os

from langgraph.graph import END, StateGraph
from langgraph.types import RunnableConfig, Send

from swarm_reasoning.pipeline.nodes.coverage import coverage_node
from swarm_reasoning.pipeline.nodes.evidence import evidence_node
from swarm_reasoning.pipeline.nodes.intake import intake_node
from swarm_reasoning.pipeline.nodes.synthesizer import synthesizer_node
from swarm_reasoning.pipeline.nodes.validation import validation_node
from swarm_reasoning.pipeline.state import PipelineState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# All nodes wired -- no placeholders remaining
# ---------------------------------------------------------------------------

# intake_node: imported from pipeline.nodes.intake (M1.2)

# evidence_node: imported from pipeline.nodes.evidence (M2.2)

# coverage_node: imported from pipeline.nodes.coverage (M3.2)

# validation_node: imported from pipeline.nodes.validation (M4.1)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def has_newsapi_key() -> bool:
    """Check whether a NewsAPI key is configured in the environment."""
    return bool(os.environ.get("NEWSAPI_KEY", ""))


def route_after_intake(state: PipelineState) -> list[Send]:
    """Route after intake: fan-out to evidence+coverage, or shortcut to synthesizer.

    - Not check-worthy -> skip directly to synthesizer
    - Check-worthy + NewsAPI key -> parallel dispatch to evidence and coverage
    - Check-worthy + no NewsAPI key -> evidence only (skip coverage)
    """
    if not state.get("is_check_worthy", True):
        logger.info("route_after_intake: not check-worthy, skipping to synthesizer")
        return [Send("synthesizer", state)]

    sends = [Send("evidence", state)]
    if has_newsapi_key():
        sends.append(Send("coverage", state))
        logger.info("route_after_intake: fan-out to evidence + coverage")
    else:
        logger.info("route_after_intake: fan-out to evidence only (no NewsAPI key)")
    return sends


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
