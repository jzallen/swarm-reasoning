"""@task wrapper that invokes the evidence scorer subagent on a source."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.func import task

from swarm_reasoning.agents.evidence.tasks.score_evidence.agent import (
    SCORER_NAME,
    build_scorer_subagent,
)
from swarm_reasoning.agents.messaging import share_heartbeat, share_progress

logger = logging.getLogger(__name__)

_AGENT_NAME = "evidence"

_scorer = None


def _get_scorer() -> Any:
    """Build the scorer subagent on first call; reuse across invocations."""
    global _scorer
    if _scorer is None:
        _scorer = build_scorer_subagent()
    return _scorer


def _format_scorer_prompt(claim_text: str, source: dict[str, Any]) -> str:
    """Build the user message for the scorer subagent."""
    excerpt = (source.get("content") or "")[:2000]
    return (
        f"Claim: {claim_text}\n\n"
        f"Source: {source.get('name', '')}\n"
        f"URL: {source.get('url', '')}\n\n"
        f"Content excerpt (first 2000 chars):\n"
        f"```\n{excerpt}\n```\n\n"
        "Decide alignment and call the record_alignment tool exactly once."
    )


@task
async def score_evidence(claim_text: str, sources: list[dict]) -> list[dict]:
    """Score the first fetched source for alignment with the claim.

    Returns a one-element list (matching the orchestrator's prior shape)
    with ``name``, ``url``, ``alignment``, ``rationale``. Empty input
    returns ``[]``. Scorer exceptions degrade to an ABSENT verdict so the
    pipeline can continue.
    """
    if not sources:
        return []
    source = sources[0]
    share_progress(f"Scoring evidence from {source.get('name', '')}...")
    share_heartbeat(_AGENT_NAME)

    prompt = _format_scorer_prompt(claim_text, source)
    config = {
        "configurable": {
            "thread_id": f"{SCORER_NAME}-{uuid.uuid4()}",
            "checkpoint_ns": "",
        }
    }
    scorer = _get_scorer()
    try:
        result = await scorer.ainvoke(
            {"messages": [HumanMessage(content=prompt)]},
            config=config,
        )
    except Exception as exc:  # pragma: no cover -- defensive
        logger.warning("scorer subagent raised: %s", exc)
        return [
            {
                "name": source.get("name", ""),
                "url": source.get("url", ""),
                "alignment": "ABSENT",
                "rationale": f"scorer error: {exc}",
            }
        ]

    alignment = str(result.get("alignment") or "ABSENT").upper()
    rationale = str(result.get("rationale") or "")
    share_heartbeat(_AGENT_NAME)
    return [
        {
            "name": source.get("name", ""),
            "url": source.get("url", ""),
            "alignment": alignment,
            "rationale": rationale,
        }
    ]
