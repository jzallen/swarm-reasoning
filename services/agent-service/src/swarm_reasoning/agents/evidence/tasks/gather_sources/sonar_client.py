"""Perplexity Sonar HTTP client (pass-2 of the gather_sources two-pass flow).

Issues a chat-completions request scoped by ``search_domain_filter``
(from pass 1) and an optional date/recency filter, then discards the
synthesis (``choices[].message.content``) and returns the raw
``search_results`` array. The orchestrator parses entries via
:class:`...models.SonarResult`.

Sources:
- https://docs.perplexity.ai/api-reference/chat-completions-post
- https://docs.perplexity.ai/guides/search-domain-filters
- https://docs.perplexity.ai/guides/date-range-filter-guide
"""

from __future__ import annotations

import logging
from typing import Any

from swarm_reasoning.agents.evidence.tasks.gather_sources.models import RecencyHint

logger = logging.getLogger(__name__)

SONAR_API_URL = "https://api.perplexity.ai/chat/completions"
SONAR_MODEL = "sonar"
SONAR_MAX_TOKENS = 64  # synthesis is discarded; 64 is a safe floor
SONAR_CONTEXT_SIZE = "low"
_SONAR_TIMEOUT_SECONDS = 15.0
_SONAR_DOMAIN_CAP = 20


def _format_sonar_date(iso: str) -> str:
    """Convert ISO8601 ``YYYY-MM-DD`` into Perplexity's ``%m/%d/%Y`` format."""
    y, m, d = iso.split("-")
    return f"{int(m)}/{int(d)}/{int(y)}"


async def _sonar_search(
    *,
    claim_text: str,
    domains: list[str],
    recency: RecencyHint,
) -> list[dict]:
    """Call Perplexity Sonar with an allow-listed domain filter.

    Returns the raw ``search_results`` array (not the synthesis). Returns
    ``[]`` when ``PERPLEXITY_API_KEY`` is not configured or the upstream
    response is non-2xx.
    """
    import os

    import httpx

    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        logger.warning("PERPLEXITY_API_KEY not configured")
        return []

    body: dict[str, Any] = {
        "model": SONAR_MODEL,
        "messages": [
            {
                "role": "user",
                "content": f"Find authoritative sources for this claim: {claim_text}",
            }
        ],
        "search_domain_filter": domains[:_SONAR_DOMAIN_CAP],
        "web_search_options": {"search_context_size": SONAR_CONTEXT_SIZE},
        "max_tokens": SONAR_MAX_TOKENS,
    }
    if recency.window:
        body["search_recency_filter"] = recency.window
    if recency.after_date:
        body["search_after_date_filter"] = _format_sonar_date(recency.after_date)
    if recency.before_date:
        body["search_before_date_filter"] = _format_sonar_date(recency.before_date)

    async with httpx.AsyncClient(timeout=_SONAR_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            SONAR_API_URL,
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if resp.status_code >= 400:
        logger.warning("Sonar HTTP %s: %s", resp.status_code, resp.text[:200])
        return []
    return resp.json().get("search_results", [])
