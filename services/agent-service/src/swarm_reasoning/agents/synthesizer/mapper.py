"""Verdict mapping: fixed thresholds from verdict.md + ClaimReview override."""

from __future__ import annotations

from swarm_reasoning.agents.synthesizer.models import ResolvedObservationSet

# Verdict threshold table: (lower_bound_inclusive, upper_bound_exclusive, code, cwe_value)
# TRUE is inclusive on both bounds (0.90-1.00)
_THRESHOLDS: list[tuple[float, float, str, str]] = [
    (0.90, 1.01, "TRUE", "TRUE^True^POLITIFACT"),
    (0.70, 0.90, "MOSTLY_TRUE", "MOSTLY_TRUE^Mostly True^POLITIFACT"),
    (0.45, 0.70, "HALF_TRUE", "HALF_TRUE^Half True^POLITIFACT"),
    (0.25, 0.45, "MOSTLY_FALSE", "MOSTLY_FALSE^Mostly False^POLITIFACT"),
    (0.10, 0.25, "FALSE", "FALSE^False^POLITIFACT"),
    (0.00, 0.10, "PANTS_FIRE", "PANTS_FIRE^Pants on Fire^POLITIFACT"),
]

_UNVERIFIABLE_CWE = "UNVERIFIABLE^Unverifiable^FCK"

# Map ClaimReview verdict codes to POLITIFACT CWE values
_CLAIMREVIEW_TO_POLITIFACT: dict[str, tuple[str, str]] = {
    "TRUE": ("TRUE", "TRUE^True^POLITIFACT"),
    "MOSTLY_TRUE": ("MOSTLY_TRUE", "MOSTLY_TRUE^Mostly True^POLITIFACT"),
    "HALF_TRUE": ("HALF_TRUE", "HALF_TRUE^Half True^POLITIFACT"),
    "MOSTLY_FALSE": ("MOSTLY_FALSE", "MOSTLY_FALSE^Mostly False^POLITIFACT"),
    "FALSE": ("FALSE", "FALSE^False^POLITIFACT"),
    "PANTS_FIRE": ("PANTS_FIRE", "PANTS_FIRE^Pants on Fire^POLITIFACT"),
}

# Override threshold for ClaimReview match score
_OVERRIDE_MATCH_THRESHOLD = 0.90


def _extract_cwe_code(cwe_value: str) -> str:
    """Extract the code portion from a CWE value (CODE^Display^System)."""
    return cwe_value.split("^")[0] if "^" in cwe_value else cwe_value


class VerdictMapper:
    """Map confidence score to verdict with ClaimReview override."""

    def map_verdict(
        self,
        confidence_score: float | None,
        resolved: ResolvedObservationSet,
    ) -> tuple[str, str, str]:
        """Map confidence score to verdict.

        Returns (verdict_code, verdict_cwe, override_reason).
        """
        if confidence_score is None:
            return "UNVERIFIABLE", _UNVERIFIABLE_CWE, ""

        # Threshold mapping
        swarm_code, swarm_cwe = self._threshold_map(confidence_score)

        # ClaimReview override evaluation
        override_reason = self._evaluate_override(swarm_code, confidence_score, resolved)

        if override_reason:
            # Extract the override verdict from resolved observations
            verdict_obs = resolved.find("CLAIMREVIEW_VERDICT")
            if verdict_obs is not None:
                cr_code = _extract_cwe_code(verdict_obs.value)
                if cr_code in _CLAIMREVIEW_TO_POLITIFACT:
                    final_code, final_cwe = _CLAIMREVIEW_TO_POLITIFACT[cr_code]
                    return final_code, final_cwe, override_reason

        return swarm_code, swarm_cwe, ""

    def _threshold_map(self, score: float) -> tuple[str, str]:
        """Map a confidence score to verdict code and CWE value."""
        for lower, upper, code, cwe in _THRESHOLDS:
            if lower <= score < upper:
                return code, cwe
        # Edge case: score exactly 1.0 handled by TRUE's upper bound of 1.01
        # Score below 0.0 maps to PANTS_FIRE
        return "PANTS_FIRE", "PANTS_FIRE^Pants on Fire^POLITIFACT"

    def _evaluate_override(
        self,
        swarm_code: str,
        confidence_score: float,
        resolved: ResolvedObservationSet,
    ) -> str:
        """Evaluate ClaimReview override conditions.

        Returns override_reason string, or empty string if no override.
        """
        # Condition 1: CLAIMREVIEW_MATCH == TRUE
        match_obs = resolved.find("CLAIMREVIEW_MATCH")
        if match_obs is None:
            return ""
        match_code = _extract_cwe_code(match_obs.value)
        if match_code != "TRUE":
            return ""

        # Condition 2: CLAIMREVIEW_MATCH_SCORE >= 0.90
        score_obs = resolved.find("CLAIMREVIEW_MATCH_SCORE")
        if score_obs is None:
            return ""
        try:
            match_score = float(score_obs.value)
        except (ValueError, TypeError):
            return ""
        if match_score < _OVERRIDE_MATCH_THRESHOLD:
            return ""

        # Condition 3: CLAIMREVIEW_VERDICT differs from swarm verdict
        verdict_obs = resolved.find("CLAIMREVIEW_VERDICT")
        if verdict_obs is None:
            return ""
        cr_code = _extract_cwe_code(verdict_obs.value)
        if cr_code == swarm_code:
            return ""

        # All conditions met: build override reason
        source_obs = resolved.find("CLAIMREVIEW_SOURCE")
        source_name = source_obs.value if source_obs else "unknown"

        return (
            f"ClaimReview override: {source_name} rated this claim {cr_code} "
            f"(match_score={match_score:.2f}); "
            f"swarm computed {swarm_code} at confidence {confidence_score:.2f}"
        )
