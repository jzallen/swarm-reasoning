"""Build the final entrypoint return value from scored inputs.

Consumes ClaimReview matches (from :mod:`search_factchecks`) and scored
domain sources (from the LLM scorer subagent) and produces the state dict
the pipeline node reads: ``claimreview_matches``, ``domain_sources``, and
``best_confidence`` (the max confidence across any scored domain source).

Confidence mapping: SUPPORTS/CONTRADICTS = 1.0, PARTIAL = 0.6, ABSENT = 0.0.
Deliberately simpler than the old ``compute_evidence_confidence`` heuristic
because the LLM scorer already accounts for content quality -- fallback
depth and staleness are no longer signal-bearing once an honest LLM reads
the page.
"""

from __future__ import annotations

from typing import Any

_CONFIDENCE_BY_ALIGNMENT = {
    "SUPPORTS": 1.0,
    "CONTRADICTS": 1.0,
    "PARTIAL": 0.6,
    "ABSENT": 0.0,
}


def _confidence(alignment: str) -> float:
    return _CONFIDENCE_BY_ALIGNMENT.get(alignment.upper(), 0.0)


def format_response(
    *,
    claimreview_matches: list[dict],
    scored_sources: list[dict],
) -> dict[str, Any]:
    """Build the evidence entrypoint's final return dict.

    Args:
        claimreview_matches: Raw ClaimReview matches (may be empty).
        scored_sources: Scored source dicts with keys ``name``, ``url``,
            ``alignment``, and optional ``rationale``. Empty list means
            no domain source was fetched or scorable.

    Returns:
        A dict with keys ``claimreview_matches``, ``domain_sources``,
        and ``best_confidence``. ``domain_sources`` entries carry a
        ``confidence`` field derived from alignment.
    """
    domain_sources: list[dict] = []
    best_confidence = 0.0

    for scored in scored_sources:
        alignment = str(scored.get("alignment") or "ABSENT").upper()
        confidence = _confidence(alignment)
        entry = {
            "name": scored.get("name", ""),
            "url": scored.get("url", ""),
            "alignment": alignment,
            "confidence": confidence,
        }
        if "rationale" in scored:
            entry["rationale"] = scored["rationale"]
        domain_sources.append(entry)
        if confidence > best_confidence:
            best_confidence = confidence

    return {
        "claimreview_matches": claimreview_matches,
        "domain_sources": domain_sources,
        "best_confidence": best_confidence,
    }
