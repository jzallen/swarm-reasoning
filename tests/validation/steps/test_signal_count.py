"""Scenario: No run reaches completed state with fewer than 5 synthesis signals."""

from __future__ import annotations

import pytest

from tests.validation.runner import HarnessRunner, RunResult


@pytest.mark.integration
class TestSignalCount:
    """Validates minimum synthesis signal count.

    Given all 50 corpus claims have been processed
    Then no completed run has SYNTHESIS_SIGNAL_COUNT below 5
    And any run with SYNTHESIS_SIGNAL_COUNT below 5 has VERDICT = "UNVERIFIABLE"
    """

    @pytest.fixture(scope="class")
    async def all_results(self, corpus_claims: list[dict]) -> list[RunResult]:
        runner = HarnessRunner()
        try:
            return await runner.run_corpus(corpus_claims)
        finally:
            await runner.close()

    def test_no_run_below_5_signals(self, all_results: list[RunResult]) -> None:
        for r in all_results:
            if r.verdict:
                signal_count = r.verdict.get("signalCount", 0)
                label = r.verdict.get("ratingLabel", "")

                if signal_count < 5:
                    assert label.lower() == "unverifiable", (
                        f"Claim {r.claim_id}: {signal_count} signals but "
                        f"verdict is {label}, expected UNVERIFIABLE"
                    )
