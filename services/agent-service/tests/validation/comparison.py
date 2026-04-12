"""Comparison logic: swarm vs baseline gap computation (NFR-020)."""

from __future__ import annotations

from dataclasses import dataclass

from tests.validation.scorer import ClaimResult, compute_alignment_rate


@dataclass
class ComparisonResult:
    """Result of comparing swarm vs baseline accuracy."""

    swarm_alignment_rate: float
    baseline_alignment_rate: float
    gap_pp: float  # percentage points
    nfr_020_must: bool  # gap >= 20pp
    nfr_020_plan: bool  # gap >= 30pp
    nfr_020_wish: bool  # gap >= 40pp


def compute_gap(
    swarm_results: list[ClaimResult],
    baseline_results: list[ClaimResult],
) -> ComparisonResult:
    """Compute the accuracy gap between swarm and baseline.

    Both result lists should contain the same claim IDs (the non-indexed
    subset of the corpus).
    """
    swarm_rate = compute_alignment_rate(swarm_results)
    baseline_rate = compute_alignment_rate(baseline_results)
    gap = round((swarm_rate - baseline_rate) * 100, 6)  # percentage points

    return ComparisonResult(
        swarm_alignment_rate=swarm_rate,
        baseline_alignment_rate=baseline_rate,
        gap_pp=gap,
        nfr_020_must=gap >= 20.0,
        nfr_020_plan=gap >= 30.0,
        nfr_020_wish=gap >= 40.0,
    )


@dataclass
class NfrAssessment:
    """Assessment of NFR-019 and NFR-020 thresholds."""

    # NFR-019: overall accuracy
    nfr_019_rate: float
    nfr_019_must: bool  # >= 70%
    nfr_019_plan: bool  # >= 80%
    nfr_019_wish: bool  # >= 90%

    # NFR-020: swarm advantage
    nfr_020_gap_pp: float
    nfr_020_must: bool  # >= 20pp
    nfr_020_plan: bool  # >= 30pp
    nfr_020_wish: bool  # >= 40pp


def assess_nfrs(
    overall_results: list[ClaimResult],
    swarm_non_indexed: list[ClaimResult],
    baseline_non_indexed: list[ClaimResult],
) -> NfrAssessment:
    """Assess NFR-019 and NFR-020 thresholds."""
    overall_rate = compute_alignment_rate(overall_results)
    comparison = compute_gap(swarm_non_indexed, baseline_non_indexed)

    return NfrAssessment(
        nfr_019_rate=overall_rate,
        nfr_019_must=overall_rate >= 0.70,
        nfr_019_plan=overall_rate >= 0.80,
        nfr_019_wish=overall_rate >= 0.90,
        nfr_020_gap_pp=comparison.gap_pp,
        nfr_020_must=comparison.nfr_020_must,
        nfr_020_plan=comparison.nfr_020_plan,
        nfr_020_wish=comparison.nfr_020_wish,
    )


def check_corpus_drift(
    corpus_claims: list[dict],
    run_results: list[dict],
) -> list[str]:
    """Detect corpus drift: non-indexed claims that now return ClaimReview matches.

    Returns list of claim IDs that have drifted.
    """
    non_indexed_ids = set()
    for claim in corpus_claims:
        if "NOT_CLAIMREVIEW_INDEXED" in claim.get("categories", []):
            non_indexed_ids.add(claim["id"])

    drifted: list[str] = []
    for result in run_results:
        claim_id = result.get("claim_id", "")
        if claim_id not in non_indexed_ids:
            continue

        for obs in result.get("observations", []):
            if obs.get("code") == "CLAIMREVIEW_MATCH":
                value = obs.get("value", "")
                if value.startswith("TRUE"):
                    drifted.append(claim_id)
                    break

    return drifted
