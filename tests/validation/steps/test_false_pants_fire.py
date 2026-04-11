"""Scenario: System correctly identifies false claims (FALSE_PANTS_FIRE category)."""

from __future__ import annotations

import pytest

from tests.validation.runner import HarnessRunner, RunResult
from tests.validation.scorer import VerdictTier, label_to_tier


@pytest.mark.integration
class TestFalsePantsFire:
    """Validates the system correctly identifies false/pants-fire claims.

    Given the validation corpus category "FALSE_PANTS_FIRE" containing 10 claims
    When the system processes all 10 claims to completed state
    Then at least 7 of 10 verdicts map to FALSE or PANTS_FIRE
    And no verdict maps to TRUE or MOSTLY_TRUE
    And the mean CONFIDENCE_SCORE for the category is below 0.25
    """

    @pytest.fixture(scope="class")
    async def run_results(
        self, corpus_claims: list[dict], category_map: dict[str, list[str]]
    ) -> list[RunResult]:
        claim_ids = set(category_map["FALSE_PANTS_FIRE"])
        claims = [c for c in corpus_claims if c["id"] in claim_ids]
        assert len(claims) == 10

        runner = HarnessRunner()
        try:
            return await runner.run_corpus(claims)
        finally:
            await runner.close()

    def test_at_least_7_map_to_false_or_pants_fire(
        self, run_results: list[RunResult]
    ) -> None:
        false_count = 0
        for r in run_results:
            if r.verdict and r.verdict.get("ratingLabel") in (
                "false",
                "pants-on-fire",
            ):
                false_count += 1
        assert false_count >= 7, f"Only {false_count}/10 mapped to FALSE/PANTS_FIRE"

    def test_no_verdict_maps_to_true_or_mostly_true(
        self, run_results: list[RunResult]
    ) -> None:
        for r in run_results:
            if r.verdict:
                label = r.verdict.get("ratingLabel", "")
                tier = label_to_tier(label)
                assert tier not in (
                    VerdictTier.TRUE,
                    VerdictTier.MOSTLY_TRUE,
                ), f"Claim {r.claim_id} incorrectly mapped to {label}"

    def test_mean_confidence_below_025(self, run_results: list[RunResult]) -> None:
        scores = [
            r.verdict["factualityScore"]
            for r in run_results
            if r.verdict and "factualityScore" in r.verdict
        ]
        assert scores, "No confidence scores found"
        mean = sum(scores) / len(scores)
        assert mean < 0.25, f"Mean confidence {mean:.3f} not below 0.25"
