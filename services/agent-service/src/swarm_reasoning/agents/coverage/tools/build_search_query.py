"""Coverage tool: build optimized NewsAPI search query from a normalized claim.

Removes stop words and truncates to 100 characters at a word boundary.
"""

from __future__ import annotations

from swarm_reasoning.agents._utils import STOP_WORDS


def build_search_query(normalized_claim: str) -> str:
    """Build an optimized NewsAPI search query from a normalized claim.

    Removes stop words and truncates to 100 characters at a word boundary.
    """
    words = normalized_claim.lower().split()
    filtered = [w for w in words if w not in STOP_WORDS]
    query = " ".join(filtered)

    if len(query) <= 100:
        return query

    truncated = query[:100]
    last_space = truncated.rfind(" ")
    return truncated[:last_space] if last_space > 0 else truncated
