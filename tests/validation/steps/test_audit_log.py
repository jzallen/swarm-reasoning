"""Scenario: Every published run has a queryable audit log."""

from __future__ import annotations

import pytest

from tests.validation.runner import HarnessRunner, RunResult


@pytest.mark.integration
class TestAuditLog:
    """Validates audit log coverage for all runs.

    Given all 50 corpus claims have been processed to completed state
    When a user fetches any verdict via GET "/sessions/{sessionId}/verdict"
    Then the observation streams for that run exist in Redis
    And the streams contain observations from at least 8 distinct agents
    """

    @pytest.fixture(scope="class")
    async def all_results(self, corpus_claims: list[dict]) -> list[RunResult]:
        runner = HarnessRunner()
        try:
            return await runner.run_corpus(corpus_claims)
        finally:
            await runner.close()

    def test_observation_streams_exist(self, all_results: list[RunResult]) -> None:
        for r in all_results:
            assert r.observations, (
                f"Claim {r.claim_id}: no observation streams found"
            )

    def test_at_least_8_distinct_agents(self, all_results: list[RunResult]) -> None:
        for r in all_results:
            agents = {obs.get("agent") for obs in r.observations if obs.get("agent")}
            assert len(agents) >= 8, (
                f"Claim {r.claim_id}: only {len(agents)} distinct agents "
                f"(expected >=8): {sorted(agents)}"
            )
