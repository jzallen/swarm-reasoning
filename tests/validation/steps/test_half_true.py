"""Scenario: System handles ambiguous claims without overclaiming (HALF_TRUE category)."""

from __future__ import annotations

import pytest

from tests.validation.runner import HarnessRunner, RunResult


@pytest.mark.integration
class TestHalfTrue:
    """Validates the system handles ambiguous claims correctly.

    Given the validation corpus category "HALF_TRUE" containing 10 claims
    When the system processes all 10 claims to completed state
    Then at least 5 of 10 verdicts map to HALF_TRUE or MOSTLY_TRUE or MOSTLY_FALSE
    And SYNTHESIS_SIGNAL_COUNT is above 10 for all 10 runs
    And no claim in this category reaches UNVERIFIABLE verdict
    """

    @pytest.fixture(scope="class")
    async def run_results(
        self, corpus_claims: list[dict], category_map: dict[str, list[str]]
    ) -> list[RunResult]:
        claim_ids = set(category_map["HALF_TRUE"])
        claims = [c for c in corpus_claims if c["id"] in claim_ids]
        assert len(claims) == 10

        runner = HarnessRunner()
        try:
            return await runner.run_corpus(claims)
        finally:
            await runner.close()

    def test_at_least_5_map_to_middle_tiers(
        self, run_results: list[RunResult]
    ) -> None:
        middle_labels = {"half-true", "mostly-true", "mostly-false"}
        count = sum(
            1
            for r in run_results
            if r.verdict and r.verdict.get("ratingLabel") in middle_labels
        )
        assert count >= 5, f"Only {count}/10 mapped to middle tiers"

    def test_signal_count_above_10(self, run_results: list[RunResult]) -> None:
        for r in run_results:
            if r.verdict:
                signal_count = r.verdict.get("signalCount", 0)
                assert signal_count > 10, (
                    f"Claim {r.claim_id} has only {signal_count} synthesis signals"
                )

    def test_no_unverifiable_verdict(self, run_results: list[RunResult]) -> None:
        for r in run_results:
            if r.verdict:
                label = r.verdict.get("ratingLabel", "")
                assert label.lower() != "unverifiable", (
                    f"Claim {r.claim_id} reached UNVERIFIABLE verdict"
                )
