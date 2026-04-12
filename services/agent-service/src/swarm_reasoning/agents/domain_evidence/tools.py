"""Domain-evidence @tool definitions for LangChain agents (ADR-004).

Exposes domain-specific research operations as @tool-decorated functions:
source routing, content fetching, relevance checking, alignment scoring,
and confidence computation. A LangChain agent invokes these alongside
the shared publish_observation / publish_progress tools.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import quote_plus

from langchain_core.tools import tool

from swarm_reasoning.agents._utils import STOP_WORDS, resilient_get

logger = logging.getLogger(__name__)

# Negation patterns for alignment detection
_NEGATION_PATTERNS = re.compile(
    r"\b(not|no evidence|false|debunked|misleading|incorrect|disproven|unfounded)\b",
    re.IGNORECASE,
)

# Lazy-loaded routes cache
_routes_cache: dict[str, list[dict]] | None = None


def _load_routes() -> dict[str, list[dict]]:
    """Load and cache the domain routing table."""
    global _routes_cache
    if _routes_cache is None:
        routes_path = Path(__file__).parent / "routes.json"
        with open(routes_path) as f:
            _routes_cache = json.load(f)
    return _routes_cache


@tool
def lookup_domain_sources(domain: str) -> str:
    """Look up authoritative sources for a claim domain.

    Args:
        domain: The domain category (e.g. HEALTHCARE, ECONOMICS, POLICY,
                SCIENCE, ELECTION, CRIME, OTHER). Case-insensitive.

    Returns:
        JSON array of available sources with name and URL template.
        The URL template contains a {query} placeholder for search terms.
        Sources are listed in priority order — prefer earlier entries.
    """
    routes = _load_routes()
    key = domain.upper()
    sources = routes.get(key, routes.get("OTHER", []))
    return json.dumps(sources, indent=2)


@tool
async def fetch_source_content(url: str) -> str:
    """Fetch text content from an authoritative source URL.

    Args:
        url: The full URL to fetch. Use lookup_domain_sources to get URL
             templates, then substitute the {query} placeholder.

    Returns:
        The first 2000 characters of the response body on success,
        or an error message starting with "ERROR:" on failure.
    """
    try:
        resp = await resilient_get(
            url, follow_redirects=True, max_redirects=5
        )
        if resp.status_code >= 400:
            return f"ERROR: HTTP {resp.status_code} from {url}"
        # Return first 2000 chars to stay within LLM context limits
        return resp.text[:2000]
    except Exception as exc:
        logger.warning("fetch_source_content failed for %s: %s", url, exc)
        return f"ERROR: Failed to fetch {url}: {exc}"


@tool
def derive_search_query(
    normalized_claim: str,
    persons: str = "",
    organizations: str = "",
    statistics: str = "",
    dates: str = "",
) -> str:
    """Derive an optimized search query from claim context.

    Combines entity names, claim keywords (minus stop words), statistics,
    and dates into a search string truncated to 80 characters.

    Args:
        normalized_claim: The normalized claim text.
        persons: Comma-separated person names (e.g. "Joe Biden, Dr. Fauci").
        organizations: Comma-separated org names (e.g. "CDC, FDA").
        statistics: Comma-separated statistics (e.g. "3.4%, 90 percent").
        dates: Comma-separated dates (e.g. "January 2023").

    Returns:
        An optimized search query string (max 80 characters).
    """
    parts: list[str] = []

    # Parse comma-separated inputs
    person_list = [p.strip() for p in persons.split(",") if p.strip()] if persons else []
    org_list = [o.strip() for o in organizations.split(",") if o.strip()] if organizations else []
    stat_list = [s.strip() for s in statistics.split(",") if s.strip()] if statistics else []
    date_list = [d.strip() for d in dates.split(",") if d.strip()] if dates else []

    # Prepend prominent entity names
    for name in (person_list + org_list)[:3]:
        parts.append(name)

    # Add claim text minus stop words
    words = normalized_claim.lower().split()
    filtered = [w for w in words if w not in STOP_WORDS]
    parts.extend(filtered)

    # Append statistics verbatim
    for stat in stat_list[:2]:
        parts.append(stat)

    # Append dates
    for date in date_list[:1]:
        parts.append(date)

    query = " ".join(parts)

    if len(query) <= 80:
        return query

    truncated = query[:80]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space]
    return truncated


@tool
def format_source_url(url_template: str, query: str) -> str:
    """Format a source URL template with a search query.

    Args:
        url_template: URL template from lookup_domain_sources containing
                      a {query} placeholder.
        query: The search query to insert (will be URL-encoded).

    Returns:
        The formatted URL ready for fetch_source_content.
    """
    return url_template.format(query=quote_plus(query))


@tool
def check_content_relevance(
    content: str,
    normalized_claim: str,
    persons: str = "",
    organizations: str = "",
) -> str:
    """Check whether fetched content is relevant to the claim.

    Uses entity presence and keyword overlap to determine relevance.
    Call this before scoring alignment to avoid wasting effort on
    irrelevant content.

    Args:
        content: The fetched source content (or first 1000 chars).
        normalized_claim: The normalized claim text.
        persons: Comma-separated person names.
        organizations: Comma-separated organization names.

    Returns:
        "RELEVANT" if content matches the claim, "NOT_RELEVANT" otherwise.
    """
    if not content:
        return "NOT_RELEVANT"

    content_lower = content[:1000].lower()

    # Parse entities
    person_list = [p.strip() for p in persons.split(",") if p.strip()] if persons else []
    org_list = [o.strip() for o in organizations.split(",") if o.strip()] if organizations else []

    # Check for entity presence
    for name in person_list + org_list:
        if name.lower() in content_lower:
            return "RELEVANT"

    # Check for claim keyword presence
    claim_words = set(normalized_claim.lower().split()) - STOP_WORDS
    matches = sum(1 for w in claim_words if w in content_lower)
    if matches >= 2:
        return "RELEVANT"

    return "NOT_RELEVANT"


@tool
def score_claim_alignment(content: str, normalized_claim: str) -> str:
    """Score how well source content aligns with the claim.

    Uses keyword overlap and negation detection to produce a coded
    alignment value.

    Args:
        content: The fetched source content.
        normalized_claim: The normalized claim text.

    Returns:
        CWE-formatted alignment: one of
        - SUPPORTS^Supports Claim^FCK
        - CONTRADICTS^Contradicts Claim^FCK
        - PARTIAL^Partially Supports^FCK
        - ABSENT^No Evidence Found^FCK
    """
    if not content:
        return "ABSENT^No Evidence Found^FCK"

    claim_words = set(normalized_claim.lower().split())
    claim_keywords = claim_words - STOP_WORDS
    if not claim_keywords:
        return "ABSENT^No Evidence Found^FCK"

    content_lower = content[:500].lower()
    matching = sum(1 for kw in claim_keywords if kw in content_lower)
    overlap_ratio = matching / len(claim_keywords)

    has_negation = bool(_NEGATION_PATTERNS.search(content_lower))

    if overlap_ratio >= 0.6 and not has_negation:
        return "SUPPORTS^Supports Claim^FCK"
    elif overlap_ratio >= 0.6 and has_negation:
        return "CONTRADICTS^Contradicts Claim^FCK"
    elif overlap_ratio >= 0.3:
        return "PARTIAL^Partially Supports^FCK"
    else:
        return "ABSENT^No Evidence Found^FCK"


@tool
def compute_evidence_confidence(
    alignment: str,
    fallback_depth: int = 0,
    source_is_old: bool = False,
    is_indirect: bool = False,
) -> str:
    """Compute a confidence score for the domain evidence.

    Base confidence is 1.0, penalized by source quality factors.

    Args:
        alignment: The CWE alignment string from score_claim_alignment.
        fallback_depth: How many fallback sources were tried before
                        finding content (0 = primary source, 1 = first
                        fallback, etc.). Each step costs -0.10.
        source_is_old: True if the source is >2 years old (-0.15 penalty).
        is_indirect: True if the source is indirect/secondary (-0.20 penalty).

    Returns:
        Confidence score as a decimal string (e.g. "0.85"), range 0.00-1.00.
    """
    if "ABSENT" in alignment:
        return "0.00"

    confidence = 1.0
    confidence -= 0.10 * fallback_depth

    if source_is_old:
        confidence -= 0.15

    if is_indirect:
        confidence -= 0.20

    if "PARTIAL" in alignment:
        confidence -= 0.10

    return f"{max(0.10, confidence):.2f}"


# All domain-evidence tools for binding to a LangChain agent
DOMAIN_EVIDENCE_TOOLS = [
    lookup_domain_sources,
    fetch_source_content,
    derive_search_query,
    format_source_url,
    check_content_relevance,
    score_claim_alignment,
    compute_evidence_confidence,
]
