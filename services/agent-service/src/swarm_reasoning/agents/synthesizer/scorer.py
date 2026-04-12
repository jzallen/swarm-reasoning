"""Confidence scoring: deterministic weighted signal model (ADR-004)."""

from __future__ import annotations

from swarm_reasoning.agents.synthesizer.models import ResolvedObservationSet

# Signal weights (normalized)
WEIGHT_DOMAIN_EVIDENCE = 0.30
WEIGHT_CLAIMREVIEW = 0.25
WEIGHT_CROSS_SPECTRUM = 0.15
WEIGHT_COVERAGE_FRAMING = 0.15
WEIGHT_SOURCE_CONVERGENCE = 0.10

# Blindspot penalty multiplier
BLINDSPOT_PENALTY_FACTOR = 0.10

# Minimum signals for scoring
MIN_SIGNAL_COUNT = 5

# DOMAIN_EVIDENCE_ALIGNMENT -> raw score
_ALIGNMENT_SCORES: dict[str, float] = {
    "SUPPORTS": 1.0,
    "PARTIAL": 0.5,
    "ABSENT": 0.25,
    "CONTRADICTS": 0.0,
}

# CLAIMREVIEW_VERDICT -> truthfulness midpoint
_CLAIMREVIEW_TRUTHFULNESS: dict[str, float] = {
    "TRUE": 0.950,
    "MOSTLY_TRUE": 0.795,
    "HALF_TRUE": 0.570,
    "MOSTLY_FALSE": 0.345,
    "FALSE": 0.170,
    "PANTS_FIRE": 0.045,
}

# COVERAGE_FRAMING -> framing score
_FRAMING_SCORES: dict[str, float] = {
    "SUPPORTIVE": 1.0,
    "NEUTRAL": 0.5,
    "ABSENT": 0.25,
    "CRITICAL": 0.0,
}

# Coverage agents
_COVERAGE_AGENTS = ["coverage-left", "coverage-center", "coverage-right"]


def _extract_cwe_code(cwe_value: str) -> str:
    """Extract the code portion from a CWE value (CODE^Display^System)."""
    return cwe_value.split("^")[0] if "^" in cwe_value else cwe_value


class ConfidenceScorer:
    """Compute a calibrated CONFIDENCE_SCORE from resolved observations."""

    def compute(self, resolved: ResolvedObservationSet) -> float | None:
        """Compute confidence score from resolved observation set.

        Returns None when synthesis_signal_count < MIN_SIGNAL_COUNT (UNVERIFIABLE).
        """
        if resolved.synthesis_signal_count < MIN_SIGNAL_COUNT:
            return None

        effective_weight = 0.0
        weighted_sum = 0.0

        # Component A -- Domain Evidence (weight 0.30)
        comp_a = self._component_domain_evidence(resolved)
        if comp_a is not None:
            weighted_sum += comp_a * WEIGHT_DOMAIN_EVIDENCE
            effective_weight += WEIGHT_DOMAIN_EVIDENCE

        # Component B -- ClaimReview (weight 0.25)
        comp_b = self._component_claimreview(resolved)
        if comp_b is not None:
            weighted_sum += comp_b * WEIGHT_CLAIMREVIEW
            effective_weight += WEIGHT_CLAIMREVIEW

        # Component C -- Cross-Spectrum Corroboration (weight 0.15)
        comp_c = self._component_cross_spectrum(resolved)
        if comp_c is not None:
            weighted_sum += comp_c * WEIGHT_CROSS_SPECTRUM
            effective_weight += WEIGHT_CROSS_SPECTRUM

        # Component D -- Coverage Framing Consensus (weight 0.15)
        comp_d = self._component_coverage_framing(resolved)
        if comp_d is not None:
            weighted_sum += comp_d * WEIGHT_COVERAGE_FRAMING
            effective_weight += WEIGHT_COVERAGE_FRAMING

        # Component E -- Source Convergence (weight 0.10)
        comp_e = self._component_source_convergence(resolved)
        if comp_e is not None:
            weighted_sum += comp_e * WEIGHT_SOURCE_CONVERGENCE
            effective_weight += WEIGHT_SOURCE_CONVERGENCE

        # Normalize by effective weight
        if effective_weight <= 0:
            return 0.0
        raw_score = weighted_sum / effective_weight

        # Blindspot penalty
        blindspot_obs = resolved.find("BLINDSPOT_SCORE")
        if blindspot_obs is not None:
            try:
                blindspot_score = float(blindspot_obs.value)
                raw_score -= blindspot_score * BLINDSPOT_PENALTY_FACTOR
            except (ValueError, TypeError):
                pass

        # Clamp to [0.0, 1.0]
        return max(0.0, min(1.0, raw_score))

    def _component_domain_evidence(self, resolved: ResolvedObservationSet) -> float | None:
        """Component A: domain evidence alignment * domain confidence."""
        alignment_obs = resolved.find("DOMAIN_EVIDENCE_ALIGNMENT")
        if alignment_obs is None:
            return None

        code = _extract_cwe_code(alignment_obs.value)
        alignment_score = _ALIGNMENT_SCORES.get(code, 0.0)

        # Apply DOMAIN_CONFIDENCE multiplier (default 1.0)
        confidence_obs = resolved.find("DOMAIN_CONFIDENCE")
        domain_confidence = 1.0
        if confidence_obs is not None:
            try:
                domain_confidence = float(confidence_obs.value)
            except (ValueError, TypeError):
                domain_confidence = 1.0

        return alignment_score * domain_confidence

    def _component_claimreview(self, resolved: ResolvedObservationSet) -> float | None:
        """Component B: ClaimReview verdict weighted by match score."""
        match_obs = resolved.find("CLAIMREVIEW_MATCH")
        if match_obs is None:
            return None

        match_code = _extract_cwe_code(match_obs.value)
        if match_code != "TRUE":
            return None

        verdict_obs = resolved.find("CLAIMREVIEW_VERDICT")
        if verdict_obs is None:
            return None

        verdict_code = _extract_cwe_code(verdict_obs.value)
        truthfulness = _CLAIMREVIEW_TRUTHFULNESS.get(verdict_code, 0.0)

        # Weight by match score
        match_score_obs = resolved.find("CLAIMREVIEW_MATCH_SCORE")
        match_score = 1.0
        if match_score_obs is not None:
            try:
                match_score = float(match_score_obs.value)
            except (ValueError, TypeError):
                match_score = 1.0

        return truthfulness * match_score

    def _component_cross_spectrum(self, resolved: ResolvedObservationSet) -> float | None:
        """Component C: cross-spectrum corroboration."""
        obs = resolved.find("CROSS_SPECTRUM_CORROBORATION")
        if obs is None:
            return None
        code = _extract_cwe_code(obs.value)
        if code == "TRUE":
            return 1.0
        return 0.0

    def _component_coverage_framing(self, resolved: ResolvedObservationSet) -> float | None:
        """Component D: average framing score across coverage agents."""
        framing_scores: list[float] = []
        for agent_name in _COVERAGE_AGENTS:
            obs = resolved.find("COVERAGE_FRAMING", agent=agent_name)
            if obs is not None:
                code = _extract_cwe_code(obs.value)
                score = _FRAMING_SCORES.get(code, 0.0)
                framing_scores.append(score)

        if not framing_scores:
            return None

        return sum(framing_scores) / len(framing_scores)

    def _component_source_convergence(self, resolved: ResolvedObservationSet) -> float | None:
        """Component E: source convergence score (ADR-0021)."""
        obs = resolved.find("SOURCE_CONVERGENCE_SCORE")
        if obs is None:
            return None
        try:
            return float(obs.value)
        except (ValueError, TypeError):
            return None
