"""Evidence pipeline node -- thin wrapper delegating to agents/evidence.

Translates PipelineState -> EvidenceInput, invokes the evidence ReAct agent,
and translates EvidenceOutput -> PipelineState updates.  Contains no domain
logic; all evidence gathering, scoring, and observation publishing lives in
the agent module.
"""

from __future__ import annotations

from typing import Any

from langgraph.types import RunnableConfig

from swarm_reasoning.agents.evidence import EvidenceInput, EvidenceOutput, run_evidence_agent
from swarm_reasoning.pipeline.context import get_pipeline_context
from swarm_reasoning.pipeline.state import PipelineState

AGENT_NAME = "evidence"


def _extract_input(state: PipelineState) -> EvidenceInput:
    """Extract EvidenceInput from PipelineState."""
    entities: dict[str, list[str]] = state.get("entities") or {}
    return EvidenceInput(
        normalized_claim=state.get("normalized_claim") or state.get("claim_text", ""),
        claim_domain=state.get("claim_domain") or "OTHER",
        persons=entities.get("persons", []),
        organizations=entities.get("organizations", []),
    )


def _apply_output(output: EvidenceOutput) -> dict[str, Any]:
    """Translate EvidenceOutput to PipelineState update dict."""
    return {
        "claimreview_matches": output["claimreview_matches"],
        "domain_sources": output["domain_sources"],
        "evidence_confidence": output["evidence_confidence"],
    }


async def evidence_node(state: PipelineState, config: RunnableConfig) -> dict[str, Any]:
    """Evidence pipeline node: delegates to the evidence ReAct agent.

    1. Extracts EvidenceInput from PipelineState
    2. Invokes run_evidence_agent (LLM-driven ReAct loop)
    3. Returns EvidenceOutput fields as PipelineState updates
    """
    ctx = get_pipeline_context(config)
    ctx.heartbeat(AGENT_NAME)

    evidence_input = _extract_input(state)
    evidence_output = await run_evidence_agent(evidence_input, ctx)

    return _apply_output(evidence_output)
