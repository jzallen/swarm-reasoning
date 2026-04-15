"""Evidence agent tools -- reusable functions for evidence gathering.

Each module exposes the core logic for one aspect of evidence collection:

- ``search_factchecks`` -- Google Fact Check Tools API search and scoring
- ``lookup_domain_sources`` -- domain routing, query derivation, URL formatting
- ``fetch_source_content`` -- HTTP content fetching and relevance checking
- ``score_evidence`` -- claim alignment scoring and confidence computation
"""

from swarm_reasoning.agents.evidence.tools.fetch_source_content import (
    FetchResult,
    check_content_relevance,
    fetch_source_content,
)
from swarm_reasoning.agents.evidence.tools.lookup_domain_sources import (
    DomainSource,
    derive_search_query,
    format_source_url,
    lookup_domain_sources,
)
from swarm_reasoning.agents.evidence.tools.score_evidence import (
    Alignment,
    AlignmentResult,
    compute_evidence_confidence,
    score_claim_alignment,
)
from swarm_reasoning.agents.evidence.tools.search_factchecks import (
    MATCH_THRESHOLD,
    FactCheckResult,
    search_factchecks,
)

__all__ = [
    "Alignment",
    "AlignmentResult",
    "DomainSource",
    "FactCheckResult",
    "FetchResult",
    "MATCH_THRESHOLD",
    "check_content_relevance",
    "compute_evidence_confidence",
    "derive_search_query",
    "fetch_source_content",
    "format_source_url",
    "lookup_domain_sources",
    "score_claim_alignment",
    "search_factchecks",
]
