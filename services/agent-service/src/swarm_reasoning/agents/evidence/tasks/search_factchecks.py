"""Deterministic ClaimReview search task (no LLM, no state).

Thin adapter over :mod:`tools.search_factchecks` that returns a plain
``list[dict]`` suitable for the evidence entrypoint's
``claimreview_matches`` output field. Each entry carries the real URL
returned by the Google Fact Check Tools API -- not a constructed search
query.
"""

from __future__ import annotations

import logging

from swarm_reasoning.agents.evidence.tools import search_factchecks as search_module

logger = logging.getLogger(__name__)


async def search_factcheck_matches(
    claim_text: str,
    persons: list[str] | None = None,
    organizations: list[str] | None = None,
) -> list[dict]:
    """Return structured ClaimReview matches for *claim_text*, or ``[]``.

    The API response's ``url`` field is preserved verbatim: it is the
    fact-checker's real review page (e.g. politifact.com/factchecks/...),
    never a synthesized search-results URL.
    """
    try:
        result = await search_module.search_factchecks(
            claim=claim_text,
            persons=persons,
            organizations=organizations,
        )
    except Exception as exc:  # pragma: no cover -- defensive
        logger.warning("search_factchecks raised: %s", exc)
        return []

    if result.error or not result.matched:
        return []

    return [
        {
            "source": result.source,
            "rating": result.rating,
            "url": result.url,
            "score": round(result.score, 2),
        }
    ]
