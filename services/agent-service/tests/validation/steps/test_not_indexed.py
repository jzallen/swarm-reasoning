"""Scenario: Swarm produces verdicts for claims not in ClaimReview."""

from __future__ import annotations

import pytest

from tests.validation.runner import HarnessRunner, RunResult
from tests.validation.scorer import within_one_tier


@pytest.mark.integration
class TestNotClaimReviewIndexed:
    """Validates swarm performance on non-indexed claims.

    Given the validation corpus category "NOT_CLAIMREVIEW_INDEXED" containing 10 claims
    When the system processes all 10 claims to completed state
    Then CLAIMREVIEW_MATCH is FALSE for all 10 runs
    And no claim reaches UNVERIFIABLE verdict
    And SYNTHESIS_SIGNAL_COUNT is above 8 for all 10 runs
    And the system verdict aligns with PolitiFact ground truth for at least 6 of 10
    """

    @pytest.fixture(scope="class")
    async def run_results(
        self, corpus_claims: list[dict], category_map: dict[str, list[str]]
    ) -> list[RunResult]:
        claim_ids = set(category_map["NOT_CLAIMREVIEW_INDEXED"])
        claims = [c for c in corpus_claims if c["id"] in claim_ids]
        assert len(claims) == 10

        runner = HarnessRunner()
        try:
            return await runner.run_corpus(claims)
        finally:
            await runner.close()

    def test_claimreview_match_false_for_all(
        self, run_results: list[RunResult]
    ) -> None:
        for r in run_results:
            for obs in r.observations:
                if obs.get("code") == "CLAIMREVIEW_MATCH":
                    value = obs.get("value", "")
                    assert not value.startswith("TRUE"), (
                        f"Claim {r.claim_id}: expected no ClaimReview match"
                    )

    def test_no_unverifiable_verdict(self, run_results: list[RunResult]) -> None:
        for r in run_results:
            if r.verdict:
                label = r.verdict.get("ratingLabel", "")
                assert label.lower() != "unverifiable", (
                    f"Claim {r.claim_id} reached UNVERIFIABLE verdict"
                )

    def test_signal_count_above_8(self, run_results: list[RunResult]) -> None:
        for r in run_results:
            if r.verdict:
                signal_count = r.verdict.get("signalCount", 0)
                assert signal_count > 8, (
                    f"Claim {r.claim_id} has only {signal_count} synthesis signals"
                )

    def test_alignment_at_least_6_of_10(
        self, run_results: list[RunResult], corpus_claims: list[dict]
    ) -> None:
        ground_truth = {c["id"]: c["ground_truth"] for c in corpus_claims}
        aligned_count = 0

        for r in run_results:
            if r.verdict:
                system_label = r.verdict.get("ratingLabel", "")
                gt_label = ground_truth.get(r.claim_id, "")
                if within_one_tier(system_label, gt_label):
                    aligned_count += 1

        assert aligned_count >= 6, (
            f"Only {aligned_count}/10 aligned with ground truth"
        )
