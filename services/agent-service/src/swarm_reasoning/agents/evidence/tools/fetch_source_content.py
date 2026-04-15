"""Authoritative source content fetching and relevance checking (ADR-004).

Fetches text from domain-authoritative URLs via resilient HTTP GET,
and checks whether fetched content is relevant to a claim using entity
presence and keyword overlap.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from swarm_reasoning.agents._utils import STOP_WORDS, resilient_get

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 2000


@dataclass
class FetchResult:
    """Result from fetching a source URL."""

    content: str
    error: str | None = None


async def fetch_source_content(url: str) -> FetchResult:
    """Fetch text content from an authoritative source URL.

    Args:
        url: The full URL to fetch (use ``format_source_url`` to build
             from a template).

    Returns:
        FetchResult with the first 2000 characters of the response body,
        or an error message on failure.
    """
    try:
        resp = await resilient_get(url, follow_redirects=True, max_redirects=5)
        if resp.status_code >= 400:
            return FetchResult(content="", error=f"HTTP {resp.status_code} from {url}")
        return FetchResult(content=resp.text[:MAX_CONTENT_LENGTH])
    except Exception as exc:
        logger.warning("fetch_source_content failed for %s: %s", url, exc)
        return FetchResult(content="", error=f"Failed to fetch {url}: {exc}")


def check_content_relevance(
    content: str,
    normalized_claim: str,
    persons: list[str] | None = None,
    organizations: list[str] | None = None,
) -> bool:
    """Check whether fetched content is relevant to the claim.

    Uses entity presence and keyword overlap to determine relevance.

    Args:
        content: The fetched source content (first 1000 chars are checked).
        normalized_claim: The normalized claim text.
        persons: Person entity names.
        organizations: Organization entity names.

    Returns:
        True if content is relevant to the claim, False otherwise.
    """
    if not content:
        return False

    persons = persons or []
    organizations = organizations or []
    content_lower = content[:1000].lower()

    # Check for entity presence
    for name in persons + organizations:
        if name.lower() in content_lower:
            return True

    # Check for claim keyword presence
    claim_words = set(normalized_claim.lower().split()) - STOP_WORDS
    matches = sum(1 for w in claim_words if w in content_lower)
    return matches >= 2
