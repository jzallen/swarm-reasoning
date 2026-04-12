"""Unit tests for synthesizer confidence scoring."""

from __future__ import annotations

import pytest

from swarm_reasoning.agents.synthesizer.models import ResolvedObservation, ResolvedObservationSet
from swarm_reasoning.agents.synthesizer.scorer import ConfidenceScorer


def _obs(code: str, value: str, agent: str = "test-agent", seq: int = 1) -> ResolvedObservation:
    """Helper to create a resolved observation."""
    return ResolvedObservation(
        agent=agent,
        code=code,
        value=value,
        value_type="CWE",
        seq=seq,
        status="F",
        resolution_method="LATEST_F",
        timestamp="2026-01-01T00:00:00Z",
    )


def _nm_obs(code: str, value: str, agent: str = "test-agent", seq: int = 1) -> ResolvedObservation:
    """Helper for NM-type resolved observation."""
    return ResolvedObservation(
        agent=agent,
        code=code,
        value=value,
        value_type="NM",
        seq=seq,
        status="F",
        resolution_method="LATEST_F",
        timestamp="2026-01-01T00:00:00Z",
    )


def _full_evidence_set(
    alignment: str = "SUPPORTS^Supports^FCK",
    domain_conf: str = "1.0",
    cr_match: str = "TRUE^Match Found^FCK",
    cr_verdict: str = "TRUE^True^POLITIFACT",
    cr_score: str = "0.95",
    corroboration: str = "TRUE^Corroborated^FCK",
    framing_left: str = "SUPPORTIVE^Supportive^FCK",
    framing_center: str = "SUPPORTIVE^Supportive^FCK",
    framing_right: str = "SUPPORTIVE^Supportive^FCK",
    convergence: str = "0.8",
    blindspot: str = "0.0",
) -> ResolvedObservationSet:
    """Create a full evidence set with configurable values."""
    obs_list = [
        _obs("DOMAIN_EVIDENCE_ALIGNMENT", alignment, agent="domain-evidence", seq=1),
        _nm_obs("DOMAIN_CONFIDENCE", domain_conf, agent="domain-evidence", seq=2),
        _obs("CLAIMREVIEW_MATCH", cr_match, agent="claimreview-matcher", seq=3),
        _obs("CLAIMREVIEW_VERDICT", cr_verdict, agent="claimreview-matcher", seq=4),
        _nm_obs("CLAIMREVIEW_MATCH_SCORE", cr_score, agent="claimreview-matcher", seq=5),
        _obs("CROSS_SPECTRUM_CORROBORATION", corroboration, agent="blindspot-detector", seq=6),
        _obs("COVERAGE_FRAMING", framing_left, agent="coverage-left", seq=7),
        _obs("COVERAGE_FRAMING", framing_center, agent="coverage-center", seq=8),
        _obs("COVERAGE_FRAMING", framing_right, agent="coverage-right", seq=9),
        _nm_obs("SOURCE_CONVERGENCE_SCORE", convergence, agent="source-validator", seq=10),
        _nm_obs("BLINDSPOT_SCORE", blindspot, agent="blindspot-detector", seq=11),
    ]
    return ResolvedObservationSet(
        observations=obs_list,
        synthesis_signal_count=len(obs_list),
    )


@pytest.fixture
def scorer():
    return ConfidenceScorer()


class TestInsufficientSignals:
    """Return None when synthesis_signal_count < 5."""

    def test_below_threshold_returns_none(self, scorer):
        resolved = ResolvedObservationSet(
            observations=[_obs("DOMAIN_EVIDENCE_ALIGNMENT", "SUPPORTS^Supports^FCK")],
            synthesis_signal_count=4,
        )
        assert scorer.compute(resolved) is None

    def test_exactly_five_returns_score(self, scorer):
        resolved = _full_evidence_set()
        resolved.synthesis_signal_count = 5
        assert scorer.compute(resolved) is not None

    def test_zero_signals(self, scorer):
        resolved = ResolvedObservationSet(observations=[], synthesis_signal_count=0)
        assert scorer.compute(resolved) is None


class TestFullEvidenceSet:
    """Score computation with all signals present."""

    def test_all_positive_signals(self, scorer):
        """All SUPPORTS/TRUE/SUPPORTIVE with no blindspot should yield high score."""
        resolved = _full_evidence_set()
        score = scorer.compute(resolved)
        assert score is not None
        assert score > 0.85

    def test_all_negative_signals(self, scorer):
        """All CONTRADICTS/FALSE/CRITICAL should yield low score."""
        resolved = _full_evidence_set(
            alignment="CONTRADICTS^Contradicts^FCK",
            cr_verdict="FALSE^False^POLITIFACT",
            corroboration="FALSE^Not Corroborated^FCK",
            framing_left="CRITICAL^Critical^FCK",
            framing_center="CRITICAL^Critical^FCK",
            framing_right="CRITICAL^Critical^FCK",
            convergence="0.0",
            blindspot="0.5",
        )
        score = scorer.compute(resolved)
        assert score is not None
        assert score < 0.25


class TestMissingClaimReview:
    """ClaimReview absent: weight deducted, other signals normalized."""

    def test_no_claimreview_match(self, scorer):
        resolved = _full_evidence_set(cr_match="FALSE^No Match^FCK")
        score_no_cr = scorer.compute(resolved)

        resolved_with = _full_evidence_set()
        score_with_cr = scorer.compute(resolved_with)

        assert score_no_cr is not None
        assert score_with_cr is not None
        # Without positive ClaimReview, should still produce valid score
        assert 0.0 <= score_no_cr <= 1.0


class TestBlindspotPenalty:
    """BLINDSPOT_SCORE reduces confidence."""

    def test_blindspot_penalty_applied(self, scorer):
        no_penalty = _full_evidence_set(blindspot="0.0")
        with_penalty = _full_evidence_set(blindspot="0.90")

        score_no = scorer.compute(no_penalty)
        score_with = scorer.compute(with_penalty)

        assert score_no is not None and score_with is not None
        # Penalty is BLINDSPOT_SCORE * 0.10 = 0.90 * 0.10 = 0.09
        assert abs((score_no - score_with) - 0.09) < 0.001

    def test_blindspot_penalty_clamped(self, scorer):
        """Score cannot go below 0.0 after penalty."""
        resolved = _full_evidence_set(
            alignment="CONTRADICTS^Contradicts^FCK",
            cr_match="FALSE^No Match^FCK",
            corroboration="FALSE^Not Corroborated^FCK",
            framing_left="CRITICAL^Critical^FCK",
            framing_center="CRITICAL^Critical^FCK",
            framing_right="CRITICAL^Critical^FCK",
            convergence="0.0",
            blindspot="1.0",
        )
        score = scorer.compute(resolved)
        assert score is not None
        assert score >= 0.0


class TestEffectiveWeightNormalization:
    """Missing signals reduce effective weight total; remaining signals are normalized."""

    def test_missing_convergence(self, scorer):
        """Without SOURCE_CONVERGENCE_SCORE, effective weight drops by 0.10."""
        with_conv = _full_evidence_set(convergence="1.0")
        # Remove SOURCE_CONVERGENCE_SCORE
        without_conv = _full_evidence_set()
        without_conv.observations = [
            o for o in without_conv.observations if o.code != "SOURCE_CONVERGENCE_SCORE"
        ]

        score_with = scorer.compute(with_conv)
        score_without = scorer.compute(without_conv)

        assert score_with is not None
        assert score_without is not None
        # Both should be valid scores
        assert 0.0 <= score_with <= 1.0
        assert 0.0 <= score_without <= 1.0


class TestConvergenceScoreImpact:
    """SOURCE_CONVERGENCE_SCORE influences final score per ADR-0021."""

    def test_high_convergence_raises_score(self, scorer):
        low_conv = _full_evidence_set(convergence="0.0")
        high_conv = _full_evidence_set(convergence="1.0")

        score_low = scorer.compute(low_conv)
        score_high = scorer.compute(high_conv)

        assert score_low is not None and score_high is not None
        assert score_high > score_low


class TestDomainConfidenceMultiplier:
    """DOMAIN_CONFIDENCE multiplies domain evidence alignment score."""

    def test_low_confidence_reduces_domain_component(self, scorer):
        full_conf = _full_evidence_set(domain_conf="1.0")
        half_conf = _full_evidence_set(domain_conf="0.5")

        score_full = scorer.compute(full_conf)
        score_half = scorer.compute(half_conf)

        assert score_full is not None and score_half is not None
        assert score_full > score_half


class TestClaimReviewMatchScore:
    """CLAIMREVIEW_MATCH_SCORE acts as trust weight for the ClaimReview signal."""

    def test_lower_match_score_reduces_component(self, scorer):
        high_match = _full_evidence_set(cr_score="0.95")
        low_match = _full_evidence_set(cr_score="0.50")

        score_high = scorer.compute(high_match)
        score_low = scorer.compute(low_match)

        assert score_high is not None and score_low is not None
        assert score_high > score_low
