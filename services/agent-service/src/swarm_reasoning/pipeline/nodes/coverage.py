"""Coverage pipeline nodes -- thin wrappers delegating to agents/coverage.

Provides three spectrum-specific pipeline node functions that each translate
PipelineState -> CoverageInput, invoke the coverage ReAct agent for a single
spectrum, and translate CoverageOutput -> PipelineState updates.  Contains no
domain logic; all coverage analysis, observation publishing, and sentiment
scoring lives in the agent module.

Pipeline nodes:

- :func:`run_coverage_left`   -- left-spectrum coverage analysis
- :func:`run_coverage_center` -- center-spectrum coverage analysis
- :func:`run_coverage_right`  -- right-spectrum coverage analysis
- :func:`coverage_node`       -- orchestrator that runs all three concurrently

The ``coverage_node`` function preserves backward compatibility with the
existing graph topology (single "coverage" node).  The three individual
functions are graph-registerable for future fan-out topologies.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from langgraph.types import RunnableConfig

from swarm_reasoning.agents.coverage import CoverageInput, CoverageOutput, run_coverage_agent
from swarm_reasoning.pipeline.context import PipelineContext, get_pipeline_context
from swarm_reasoning.pipeline.state import PipelineState

logger = logging.getLogger(__name__)

# Spectrum → agent name mapping
_SPECTRUMS = {
    "left": "coverage-left",
    "center": "coverage-center",
    "right": "coverage-right",
}

# Spectrum → PipelineState key mapping
_STATE_KEYS = {
    "left": "coverage_left",
    "center": "coverage_center",
    "right": "coverage_right",
}

# ---------------------------------------------------------------------------
# Source loading (lazy-cached per spectrum)
# ---------------------------------------------------------------------------

_sources_cache: dict[str, list[dict]] = {}


def _load_sources(spectrum: str) -> list[dict]:
    """Load and cache the source list for a given spectrum."""
    if spectrum not in _sources_cache:
        sources_path = (
            Path(__file__).parents[2] / "agents" / "coverage" / "sources" / f"{spectrum}.json"
        )
        with open(sources_path) as f:
            _sources_cache[spectrum] = json.load(f)
    return _sources_cache[spectrum]


# ---------------------------------------------------------------------------
# Input extraction / output translation
# ---------------------------------------------------------------------------


def _extract_input(state: PipelineState) -> CoverageInput:
    """Extract CoverageInput from PipelineState."""
    return CoverageInput(
        normalized_claim=state.get("normalized_claim") or state.get("claim_text", ""),
    )


def _apply_output(spectrum: str, output: CoverageOutput) -> dict[str, Any]:
    """Translate CoverageOutput for a single spectrum to PipelineState updates."""
    state_key = _STATE_KEYS[spectrum]
    framing_entry = {
        "framing": output["framing"],
        "compound": output["compound_score"],
        "article_count": len(output["articles"]),
    }

    return {
        state_key: output["articles"],
        "framing_analysis": {spectrum: framing_entry},
    }


# ---------------------------------------------------------------------------
# Per-spectrum runner (shared logic)
# ---------------------------------------------------------------------------


async def _run_spectrum_node(
    spectrum: str,
    state: PipelineState,
    ctx: PipelineContext,
) -> dict[str, Any]:
    """Run a single coverage spectrum and return state updates."""
    agent_name = _SPECTRUMS[spectrum]
    ctx.heartbeat(agent_name)

    coverage_input = _extract_input(state)
    sources = _load_sources(spectrum)
    coverage_output = await run_coverage_agent(spectrum, sources, coverage_input, ctx)

    return _apply_output(spectrum, coverage_output)


# ===================================================================
# Pipeline node functions (graph-registerable)
# ===================================================================


async def run_coverage_left(state: PipelineState, config: RunnableConfig) -> dict[str, Any]:
    """Left-spectrum coverage pipeline node: delegates to the coverage ReAct agent.

    1. Extracts CoverageInput from PipelineState
    2. Loads left-spectrum source list
    3. Invokes run_coverage_agent (LLM-driven ReAct loop)
    4. Returns CoverageOutput fields as PipelineState updates
    """
    ctx = get_pipeline_context(config)
    return await _run_spectrum_node("left", state, ctx)


async def run_coverage_center(state: PipelineState, config: RunnableConfig) -> dict[str, Any]:
    """Center-spectrum coverage pipeline node: delegates to the coverage ReAct agent.

    1. Extracts CoverageInput from PipelineState
    2. Loads center-spectrum source list
    3. Invokes run_coverage_agent (LLM-driven ReAct loop)
    4. Returns CoverageOutput fields as PipelineState updates
    """
    ctx = get_pipeline_context(config)
    return await _run_spectrum_node("center", state, ctx)


async def run_coverage_right(state: PipelineState, config: RunnableConfig) -> dict[str, Any]:
    """Right-spectrum coverage pipeline node: delegates to the coverage ReAct agent.

    1. Extracts CoverageInput from PipelineState
    2. Loads right-spectrum source list
    3. Invokes run_coverage_agent (LLM-driven ReAct loop)
    4. Returns CoverageOutput fields as PipelineState updates
    """
    ctx = get_pipeline_context(config)
    return await _run_spectrum_node("right", state, ctx)


# ===================================================================
# Composite node (backward-compatible single-node orchestrator)
# ===================================================================


async def coverage_node(state: PipelineState, config: RunnableConfig) -> dict[str, Any]:
    """Coverage pipeline node: runs all three spectrums concurrently.

    Delegates to run_coverage_left, run_coverage_center, and run_coverage_right
    via asyncio.gather, then merges their state updates.  This preserves
    backward compatibility with the existing graph topology that registers
    a single ``"coverage"`` node.
    """
    ctx = get_pipeline_context(config)
    ctx.heartbeat("coverage")

    await ctx.publish_progress("coverage", "Starting coverage analysis (left/center/right)...")

    results = await asyncio.gather(
        _run_spectrum_node("left", state, ctx),
        _run_spectrum_node("center", state, ctx),
        _run_spectrum_node("right", state, ctx),
    )

    # Merge state updates from all three spectrums
    merged: dict[str, Any] = {}
    framing_analysis: dict[str, dict] = {}

    for result in results:
        for key, value in result.items():
            if key == "framing_analysis":
                framing_analysis.update(value)
            else:
                merged[key] = value

    merged["framing_analysis"] = framing_analysis

    total = sum(fa["article_count"] for fa in framing_analysis.values())
    await ctx.publish_progress(
        "coverage",
        f"Coverage complete: {total} total articles across 3 spectrums",
    )

    return merged
