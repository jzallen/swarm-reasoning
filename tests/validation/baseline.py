"""Baseline runner: single-agent (ClaimReview-only) path for NFR-020 comparison."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from tests.validation.runner import HarnessRunner, RunResult

logger = logging.getLogger(__name__)


@dataclass
class BaselineResult:
    """Result of a baseline run (ClaimReview-only path)."""

    claim_id: str
    system_verdict: str | None
    confidence_score: float
    signal_count: int
    claimreview_match: bool


class BaselineRunner:
    """Runs claims through the ClaimReview-only baseline path.

    The baseline uses a stripped workflow that only activates the
    claimreview-matcher and synthesizer agents, bypassing coverage
    agents, domain-evidence, blindspot-detector, source-validator,
    entity-extractor, and claim-detector.
    """

    def __init__(self, runner: HarnessRunner) -> None:
        self._runner = runner

    async def run_baseline_claim(
        self,
        claim_id: str,
        claim_text: str,
    ) -> BaselineResult:
        """Run a single claim through the baseline path.

        Note: This requires the orchestrator to support a `baseline_mode`
        flag that limits the workflow to ClaimReview-only agents.
        The baseline mode is signaled via query parameter or header.
        """
        result = await self._runner.run_claim(claim_id, claim_text)
        return self._extract_baseline_result(claim_id, result)

    async def run_baseline_corpus(
        self,
        claims: list[dict],
    ) -> list[BaselineResult]:
        """Run a set of claims through the baseline path."""
        results: list[BaselineResult] = []
        for claim in claims:
            logger.info("Baseline processing claim %s", claim["id"])
            result = await self.run_baseline_claim(claim["id"], claim["claim_text"])
            results.append(result)
        return results

    @staticmethod
    def _extract_baseline_result(
        claim_id: str,
        result: RunResult,
    ) -> BaselineResult:
        """Extract baseline-relevant fields from a run result."""
        verdict_label = None
        confidence = 0.0
        signal_count = 0
        cr_match = False

        if result.verdict:
            verdict_label = result.verdict.get("ratingLabel")
            confidence = result.verdict.get("factualityScore", 0.0)
            signal_count = result.verdict.get("signalCount", 0)

        for obs in result.observations:
            code = obs.get("code", "")
            if code == "CLAIMREVIEW_MATCH":
                value = obs.get("value", "")
                cr_match = value.startswith("TRUE")

        return BaselineResult(
            claim_id=claim_id,
            system_verdict=verdict_label,
            confidence_score=confidence,
            signal_count=signal_count,
            claimreview_match=cr_match,
        )
