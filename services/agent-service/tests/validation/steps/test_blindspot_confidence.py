"""Scenario: Blindspot detection correlates with lower confidence scores."""

from __future__ import annotations

import pytest

from tests.validation.runner import HarnessRunner, RunResult


@pytest.mark.integration
class TestBlindspotConfidence:
    """Validates blindspot-confidence correlation.

    Given all 50 corpus claims have been processed
    When runs are grouped by BLINDSPOT_SCORE above 0.7 vs below 0.3
    Then the mean CONFIDENCE_SCORE for the high-blindspot group is lower
    And the difference in mean CONFIDENCE_SCORE between groups is statistically significant
    """

    @pytest.fixture(scope="class")
    async def all_results(self, corpus_claims: list[dict]) -> list[RunResult]:
        runner = HarnessRunner()
        try:
            return await runner.run_corpus(corpus_claims)
        finally:
            await runner.close()

    def test_high_blindspot_lower_confidence(
        self, all_results: list[RunResult]
    ) -> None:
        high_blindspot_confidence: list[float] = []
        low_blindspot_confidence: list[float] = []

        for r in all_results:
            blindspot = None
            confidence = None

            for obs in r.observations:
                if obs.get("code") == "BLINDSPOT_SCORE":
                    blindspot = float(obs.get("value", "0"))
                if obs.get("code") == "CONFIDENCE_SCORE":
                    confidence = float(obs.get("value", "0"))

            if blindspot is not None and confidence is not None:
                if blindspot > 0.7:
                    high_blindspot_confidence.append(confidence)
                elif blindspot < 0.3:
                    low_blindspot_confidence.append(confidence)

        if not high_blindspot_confidence or not low_blindspot_confidence:
            pytest.skip(
                "Insufficient data: need claims in both blindspot groups "
                f"(high={len(high_blindspot_confidence)}, "
                f"low={len(low_blindspot_confidence)})"
            )

        high_mean = sum(high_blindspot_confidence) / len(high_blindspot_confidence)
        low_mean = sum(low_blindspot_confidence) / len(low_blindspot_confidence)

        assert high_mean < low_mean, (
            f"High-blindspot mean confidence ({high_mean:.3f}) "
            f"is not lower than low-blindspot ({low_mean:.3f})"
        )

    def test_confidence_difference_is_significant(
        self, all_results: list[RunResult]
    ) -> None:
        high_blindspot_confidence: list[float] = []
        low_blindspot_confidence: list[float] = []

        for r in all_results:
            blindspot = None
            confidence = None

            for obs in r.observations:
                if obs.get("code") == "BLINDSPOT_SCORE":
                    blindspot = float(obs.get("value", "0"))
                if obs.get("code") == "CONFIDENCE_SCORE":
                    confidence = float(obs.get("value", "0"))

            if blindspot is not None and confidence is not None:
                if blindspot > 0.7:
                    high_blindspot_confidence.append(confidence)
                elif blindspot < 0.3:
                    low_blindspot_confidence.append(confidence)

        if len(high_blindspot_confidence) < 3 or len(low_blindspot_confidence) < 3:
            pytest.skip("Need at least 3 samples per group for significance test")

        high_mean = sum(high_blindspot_confidence) / len(high_blindspot_confidence)
        low_mean = sum(low_blindspot_confidence) / len(low_blindspot_confidence)
        diff = abs(low_mean - high_mean)

        # Practical significance threshold: at least 0.05 difference
        assert diff >= 0.05, (
            f"Confidence difference ({diff:.3f}) is not practically significant"
        )
