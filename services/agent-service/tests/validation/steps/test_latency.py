"""Scenario: Total run time for a single claim does not exceed 120 seconds."""

from __future__ import annotations

import pytest

from tests.validation.runner import HarnessRunner, RunResult


@pytest.mark.integration
class TestLatency:
    """Validates single-claim run time.

    Given a claim from the validation corpus
    When the claim is submitted and the run completes to completed state
    Then the elapsed time is under 120 seconds
    And the parallel fan-out phase (agents 4-9) completes in under 45 seconds
    """

    @pytest.fixture(scope="class")
    async def run_result(self, corpus_claims: list[dict]) -> RunResult:
        claim = corpus_claims[0]
        runner = HarnessRunner()
        try:
            return await runner.run_claim(claim["id"], claim["claim_text"])
        finally:
            await runner.close()

    def test_total_time_under_120_seconds(self, run_result: RunResult) -> None:
        assert run_result.elapsed_seconds < 120, (
            f"Total elapsed time {run_result.elapsed_seconds:.1f}s exceeds 120s"
        )

    def test_fanout_phase_under_45_seconds(self, run_result: RunResult) -> None:
        # Estimate fan-out duration from observation timestamps
        fanout_agents = {
            "coverage-left", "coverage-center", "coverage-right",
            "domain-evidence", "source-validator", "blindspot-detector",
        }

        fanout_timestamps: list[str] = []
        for obs in run_result.observations:
            agent = obs.get("agent", "")
            if agent in fanout_agents and obs.get("timestamp"):
                fanout_timestamps.append(obs["timestamp"])

        if len(fanout_timestamps) < 2:
            pytest.skip("Insufficient fan-out observations to measure duration")

        from datetime import datetime

        times = sorted(datetime.fromisoformat(t) for t in fanout_timestamps)
        fanout_duration = (times[-1] - times[0]).total_seconds()

        assert fanout_duration < 45, (
            f"Fan-out phase took {fanout_duration:.1f}s, exceeds 45s limit"
        )
