"""Scenario: System correctly identifies true claims (TRUE_MOSTLY_TRUE category)."""

from __future__ import annotations

import pytest

from tests.validation.runner import HarnessRunner, RunResult
from tests.validation.scorer import VerdictTier, label_to_tier


@pytest.mark.integration
class TestTrueMostlyTrue:
    """Validates the system correctly identifies true/mostly-true claims.

    Given the validation corpus category "TRUE_MOSTLY_TRUE" containing 10 claims
    When the system processes all 10 claims to completed state
    Then at least 7 of 10 verdicts map to TRUE or MOSTLY_TRUE
    And no verdict maps to FALSE or PANTS_FIRE
    And the mean CONFIDENCE_SCORE for the category is above 0.70
    """

    @pytest.fixture(scope="class")
    async def run_results(
        self, corpus_claims: list[dict], category_map: dict[str, list[str]]
    ) -> list[RunResult]:
        claim_ids = set(category_map["TRUE_MOSTLY_TRUE"])
        claims = [c for c in corpus_claims if c["id"] in claim_ids]
        assert len(claims) == 10

        runner = HarnessRunner()
        try:
            return await runner.run_corpus(claims)
        finally:
            await runner.close()

    def test_at_least_7_map_to_true_or_mostly_true(
        self, run_results: list[RunResult]
    ) -> None:
        true_count = 0
        for r in run_results:
            if r.verdict and r.verdict.get("ratingLabel") in ("true", "mostly-true"):
                true_count += 1
        assert true_count >= 7, f"Only {true_count}/10 mapped to TRUE/MOSTLY_TRUE"

    def test_no_verdict_maps_to_false_or_pants_fire(
        self, run_results: list[RunResult]
    ) -> None:
        for r in run_results:
            if r.verdict:
                label = r.verdict.get("ratingLabel", "")
                tier = label_to_tier(label)
                assert tier not in (
                    VerdictTier.FALSE,
                    VerdictTier.PANTS_FIRE,
                ), f"Claim {r.claim_id} incorrectly mapped to {label}"

    def test_mean_confidence_above_070(self, run_results: list[RunResult]) -> None:
        scores = [
            r.verdict["factualityScore"]
            for r in run_results
            if r.verdict and "factualityScore" in r.verdict
        ]
        assert scores, "No confidence scores found"
        mean = sum(scores) / len(scores)
        assert mean > 0.70, f"Mean confidence {mean:.3f} not above 0.70"
