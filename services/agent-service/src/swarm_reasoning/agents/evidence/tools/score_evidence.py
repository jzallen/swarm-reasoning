"""Claim alignment scoring and evidence confidence computation (ADR-004).

Scores how well source content aligns with a claim using keyword overlap
and negation detection, then computes an overall confidence value
penalized by source quality factors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from swarm_reasoning.agents._utils import STOP_WORDS

_NEGATION_PATTERNS = re.compile(
    r"\b(not|no evidence|false|debunked|misleading|incorrect|disproven|unfounded)\b",
    re.IGNORECASE,
)


class Alignment(str, Enum):
    """Evidence alignment categories."""

    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    PARTIAL = "PARTIAL"
    ABSENT = "ABSENT"


@dataclass
class AlignmentResult:
    """Result from scoring claim-content alignment."""

    alignment: Alignment
    description: str


def score_claim_alignment(content: str, normalized_claim: str) -> AlignmentResult:
    """Score how well source content aligns with the claim.

    Uses keyword overlap and negation detection to produce an alignment
    assessment.

    Args:
        content: The fetched source content.
        normalized_claim: The normalized claim text.

    Returns:
        AlignmentResult with alignment category and description.
    """
    if not content:
        return AlignmentResult(alignment=Alignment.ABSENT, description="No Evidence Found")

    claim_words = set(normalized_claim.lower().split())
    claim_keywords = claim_words - STOP_WORDS
    if not claim_keywords:
        return AlignmentResult(alignment=Alignment.ABSENT, description="No Evidence Found")

    content_lower = content[:500].lower()
    matching = sum(1 for kw in claim_keywords if kw in content_lower)
    overlap_ratio = matching / len(claim_keywords)

    has_negation = bool(_NEGATION_PATTERNS.search(content_lower))

    if overlap_ratio >= 0.6 and not has_negation:
        return AlignmentResult(alignment=Alignment.SUPPORTS, description="Supports Claim")
    elif overlap_ratio >= 0.6 and has_negation:
        return AlignmentResult(alignment=Alignment.CONTRADICTS, description="Contradicts Claim")
    elif overlap_ratio >= 0.3:
        return AlignmentResult(alignment=Alignment.PARTIAL, description="Partially Supports")
    else:
        return AlignmentResult(alignment=Alignment.ABSENT, description="No Evidence Found")


def compute_evidence_confidence(
    alignment: Alignment,
    fallback_depth: int = 0,
    source_is_old: bool = False,
    is_indirect: bool = False,
) -> float:
    """Compute a confidence score for the domain evidence.

    Base confidence is 1.0, penalized by source quality factors.

    Args:
        alignment: The alignment category from ``score_claim_alignment``.
        fallback_depth: How many fallback sources were tried before
            finding content (0 = primary, 1 = first fallback, etc.).
            Each step costs -0.10.
        source_is_old: True if the source is >2 years old (-0.15 penalty).
        is_indirect: True if the source is indirect/secondary (-0.20 penalty).

    Returns:
        Confidence score in [0.0, 1.0].  Returns 0.0 when alignment is ABSENT.
    """
    if alignment == Alignment.ABSENT:
        return 0.0

    confidence = 1.0
    confidence -= 0.10 * fallback_depth

    if source_is_old:
        confidence -= 0.15

    if is_indirect:
        confidence -= 0.20

    if alignment == Alignment.PARTIAL:
        confidence -= 0.10

    return max(0.10, min(1.0, confidence))
