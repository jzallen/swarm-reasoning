"""Scenario: Swarm outperforms single-agent baseline on non-indexed claims."""

from __future__ import annotations

import pytest

from tests.validation.runner import HarnessRunner, RunResult
from tests.validation.scorer import compute_alignment_rate, score_claim


@pytest.mark.integration
class TestBaselineComparison:
    """Validates swarm advantage over ClaimReview-only baseline.

    Given the validation corpus category "NOT_CLAIMREVIEW_INDEXED" containing 10 claims
    And a single-agent baseline has been run on the same 10 claims
    When system verdicts are compared to baseline verdicts
    Then the swarm correct alignment rate exceeds the baseline correct alignment rate
    And the swarm mean SYNTHESIS_SIGNAL_COUNT exceeds the baseline signal count by at least 5
    """

    @pytest.fixture(scope="class")
    async def swarm_results(
        self, corpus_claims: list[dict], category_map: dict[str, list[str]]
    ) -> list[RunResult]:
        claim_ids = set(category_map["NOT_CLAIMREVIEW_INDEXED"])
        claims = [c for c in corpus_claims if c["id"] in claim_ids]
        runner = HarnessRunner()
        try:
            return await runner.run_corpus(claims)
        finally:
            await runner.close()

    @pytest.fixture(scope="class")
    async def baseline_results(
        self, corpus_claims: list[dict], category_map: dict[str, list[str]]
    ) -> list[RunResult]:
        claim_ids = set(category_map["NOT_CLAIMREVIEW_INDEXED"])
        claims = [c for c in corpus_claims if c["id"] in claim_ids]
        # Baseline mode uses the same API but with a stripped workflow.
        # When baseline_mode is implemented in the orchestrator, this
        # will pass a query parameter or header to select the baseline path.
        runner = HarnessRunner()
        try:
            return await runner.run_corpus(claims)
        finally:
            await runner.close()

    def test_swarm_alignment_exceeds_baseline(
        self,
        swarm_results: list[RunResult],
        baseline_results: list[RunResult],
        corpus_claims: list[dict],
    ) -> None:
        ground_truth = {c["id"]: c["ground_truth"] for c in corpus_claims}

        swarm_scored = [
            score_claim(
                r.claim_id, "", ground_truth.get(r.claim_id, ""),
                r.verdict.get("ratingLabel", "") if r.verdict else "",
                r.verdict.get("factualityScore", 0) if r.verdict else 0,
                r.verdict.get("signalCount", 0) if r.verdict else 0,
            )
            for r in swarm_results
        ]

        baseline_scored = [
            score_claim(
                r.claim_id, "", ground_truth.get(r.claim_id, ""),
                r.verdict.get("ratingLabel", "") if r.verdict else "",
                r.verdict.get("factualityScore", 0) if r.verdict else 0,
                r.verdict.get("signalCount", 0) if r.verdict else 0,
            )
            for r in baseline_results
        ]

        swarm_rate = compute_alignment_rate(swarm_scored)
        baseline_rate = compute_alignment_rate(baseline_scored)
        assert swarm_rate > baseline_rate, (
            f"Swarm alignment {swarm_rate:.1%} does not exceed "
            f"baseline {baseline_rate:.1%}"
        )

    def test_swarm_signal_count_exceeds_baseline_by_5(
        self,
        swarm_results: list[RunResult],
        baseline_results: list[RunResult],
    ) -> None:
        swarm_signals = [
            r.verdict.get("signalCount", 0)
            for r in swarm_results
            if r.verdict
        ]
        baseline_signals = [
            r.verdict.get("signalCount", 0)
            for r in baseline_results
            if r.verdict
        ]

        swarm_mean = sum(swarm_signals) / len(swarm_signals) if swarm_signals else 0
        baseline_mean = (
            sum(baseline_signals) / len(baseline_signals) if baseline_signals else 0
        )

        assert swarm_mean >= baseline_mean + 5, (
            f"Swarm mean signals {swarm_mean:.1f} does not exceed "
            f"baseline {baseline_mean:.1f} by at least 5"
        )
