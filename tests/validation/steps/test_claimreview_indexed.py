"""Scenario: System matches ClaimReview verdicts for indexed claims."""

from __future__ import annotations

import pytest

from tests.validation.runner import HarnessRunner, RunResult
from tests.validation.scorer import within_one_tier


@pytest.mark.integration
class TestClaimReviewIndexed:
    """Validates the system matches ClaimReview verdicts for indexed claims.

    Given the validation corpus category "CLAIMREVIEW_INDEXED" containing 10 claims
    When the system processes all 10 claims to completed state
    Then CLAIMREVIEW_MATCH is TRUE for all 10 runs
    And CLAIMREVIEW_MATCH_SCORE is above 0.75 for all 10 runs
    And the system verdict matches the ClaimReview verdict for at least 8 of 10 claims
    And SYNTHESIS_OVERRIDE_REASON is non-empty for any claim where verdicts diverge
    """

    @pytest.fixture(scope="class")
    async def run_results(
        self, corpus_claims: list[dict], category_map: dict[str, list[str]]
    ) -> list[RunResult]:
        claim_ids = set(category_map["CLAIMREVIEW_INDEXED"])
        claims = [c for c in corpus_claims if c["id"] in claim_ids]
        assert len(claims) == 10

        runner = HarnessRunner()
        try:
            return await runner.run_corpus(claims)
        finally:
            await runner.close()

    def test_claimreview_match_true_for_all(
        self, run_results: list[RunResult]
    ) -> None:
        for r in run_results:
            cr_match = False
            for obs in r.observations:
                if obs.get("code") == "CLAIMREVIEW_MATCH":
                    cr_match = obs.get("value", "").startswith("TRUE")
            assert cr_match, f"Claim {r.claim_id}: CLAIMREVIEW_MATCH not TRUE"

    def test_match_score_above_075(self, run_results: list[RunResult]) -> None:
        for r in run_results:
            for obs in r.observations:
                if obs.get("code") == "CLAIMREVIEW_MATCH_SCORE":
                    score = float(obs.get("value", "0"))
                    assert score > 0.75, (
                        f"Claim {r.claim_id}: match score {score} not above 0.75"
                    )

    def test_verdict_matches_for_at_least_8(
        self, run_results: list[RunResult], corpus_claims: list[dict]
    ) -> None:
        ground_truth = {c["id"]: c["ground_truth"] for c in corpus_claims}
        match_count = 0

        for r in run_results:
            if r.verdict:
                system_label = r.verdict.get("ratingLabel", "")
                gt_label = ground_truth.get(r.claim_id, "")
                if within_one_tier(system_label, gt_label):
                    match_count += 1

        assert match_count >= 8, f"Only {match_count}/10 verdicts match ClaimReview"

    def test_override_reason_when_divergent(
        self, run_results: list[RunResult], corpus_claims: list[dict]
    ) -> None:
        ground_truth = {c["id"]: c["ground_truth"] for c in corpus_claims}

        for r in run_results:
            if not r.verdict:
                continue
            system_label = r.verdict.get("ratingLabel", "")
            gt_label = ground_truth.get(r.claim_id, "")

            if not within_one_tier(system_label, gt_label):
                has_override = any(
                    obs.get("code") == "SYNTHESIS_OVERRIDE_REASON"
                    and obs.get("value", "").strip()
                    for obs in r.observations
                )
                assert has_override, (
                    f"Claim {r.claim_id}: divergent verdict without override reason"
                )
