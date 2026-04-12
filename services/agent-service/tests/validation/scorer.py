"""Accuracy scorer: within-one-tier alignment metric (ADR-008, NFR-019)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class VerdictTier(IntEnum):
    """Six-tier encoding of PolitiFact ratings."""

    PANTS_FIRE = 0
    FALSE = 1
    MOSTLY_FALSE = 2
    HALF_TRUE = 3
    MOSTLY_TRUE = 4
    TRUE = 5


# Map string labels to tiers (handles both corpus ground_truth and system output)
_LABEL_TO_TIER: dict[str, VerdictTier] = {
    "TRUE": VerdictTier.TRUE,
    "true": VerdictTier.TRUE,
    "MOSTLY_TRUE": VerdictTier.MOSTLY_TRUE,
    "mostly-true": VerdictTier.MOSTLY_TRUE,
    "HALF_TRUE": VerdictTier.HALF_TRUE,
    "half-true": VerdictTier.HALF_TRUE,
    "MOSTLY_FALSE": VerdictTier.MOSTLY_FALSE,
    "mostly-false": VerdictTier.MOSTLY_FALSE,
    "FALSE": VerdictTier.FALSE,
    "false": VerdictTier.FALSE,
    "PANTS_FIRE": VerdictTier.PANTS_FIRE,
    "pants-on-fire": VerdictTier.PANTS_FIRE,
}


def label_to_tier(label: str) -> VerdictTier:
    """Convert a verdict label string to its numeric tier.

    Accepts both corpus-style (e.g. 'MOSTLY_TRUE') and system-style
    (e.g. 'mostly-true') labels.
    """
    tier = _LABEL_TO_TIER.get(label)
    if tier is None:
        raise ValueError(f"Unknown verdict label: {label!r}")
    return tier


def within_one_tier(system_label: str, ground_truth_label: str) -> bool:
    """Return True if system verdict is within one tier of ground truth."""
    system_tier = label_to_tier(system_label)
    truth_tier = label_to_tier(ground_truth_label)
    return abs(system_tier - truth_tier) <= 1


@dataclass
class ClaimResult:
    """Result of scoring a single claim."""

    claim_id: str
    claim_text: str
    ground_truth: str
    system_verdict: str
    ground_truth_tier: int
    system_tier: int
    aligned: bool
    confidence_score: float
    signal_count: int


def score_claim(
    claim_id: str,
    claim_text: str,
    ground_truth: str,
    system_verdict: str,
    confidence_score: float,
    signal_count: int,
) -> ClaimResult:
    """Score a single claim against ground truth."""
    gt_tier = label_to_tier(ground_truth)
    sys_tier = label_to_tier(system_verdict)
    return ClaimResult(
        claim_id=claim_id,
        claim_text=claim_text,
        ground_truth=ground_truth,
        system_verdict=system_verdict,
        ground_truth_tier=int(gt_tier),
        system_tier=int(sys_tier),
        aligned=abs(sys_tier - gt_tier) <= 1,
        confidence_score=confidence_score,
        signal_count=signal_count,
    )


def compute_alignment_rate(results: list[ClaimResult]) -> float:
    """Compute the fraction of claims that are within-one-tier aligned."""
    if not results:
        return 0.0
    aligned_count = sum(1 for r in results if r.aligned)
    return aligned_count / len(results)


def compute_category_alignment(
    results: list[ClaimResult],
    category_claims: list[str],
) -> float:
    """Compute alignment rate for a specific category of claim IDs."""
    category_results = [r for r in results if r.claim_id in category_claims]
    return compute_alignment_rate(category_results)
