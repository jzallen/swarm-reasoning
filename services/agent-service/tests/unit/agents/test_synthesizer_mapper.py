"""Unit tests for synthesizer verdict mapping and ClaimReview override."""

from __future__ import annotations

import pytest

from swarm_reasoning.agents.synthesizer.mapper import VerdictMapper
from swarm_reasoning.agents.synthesizer.models import ResolvedObservation, ResolvedObservationSet


def _obs(code: str, value: str, agent: str = "test-agent", seq: int = 1) -> ResolvedObservation:
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


def _resolved_with_claimreview(
    cr_match: str = "TRUE^Match Found^FCK",
    cr_verdict: str = "TRUE^True^POLITIFACT",
    cr_score: str = "0.95",
    cr_source: str = "PolitiFact",
) -> ResolvedObservationSet:
    return ResolvedObservationSet(
        observations=[
            _obs("CLAIMREVIEW_MATCH", cr_match, agent="claimreview-matcher"),
            _obs("CLAIMREVIEW_VERDICT", cr_verdict, agent="claimreview-matcher"),
            _nm_obs("CLAIMREVIEW_MATCH_SCORE", cr_score, agent="claimreview-matcher"),
            ResolvedObservation(
                agent="claimreview-matcher",
                code="CLAIMREVIEW_SOURCE",
                value=cr_source,
                value_type="ST",
                seq=4,
                status="F",
                resolution_method="LATEST_F",
                timestamp="2026-01-01T00:00:00Z",
            ),
        ],
        synthesis_signal_count=4,
    )


@pytest.fixture
def mapper():
    return VerdictMapper()


class TestThresholdMapping:
    """Score maps to correct verdict per verdict.md thresholds."""

    @pytest.mark.parametrize(
        "score, expected_code",
        [
            (0.95, "TRUE"),
            (0.75, "MOSTLY_TRUE"),
            (0.55, "HALF_TRUE"),
            (0.35, "MOSTLY_FALSE"),
            (0.18, "FALSE"),
            (0.04, "PANTS_FIRE"),
        ],
    )
    def test_typical_scores(self, mapper, score, expected_code):
        resolved = ResolvedObservationSet(observations=[], synthesis_signal_count=10)
        code, cwe, reason = mapper.map_verdict(score, resolved)
        assert code == expected_code
        assert reason == ""

    @pytest.mark.parametrize(
        "score, expected_code",
        [
            (1.00, "TRUE"),
            (0.90, "TRUE"),
            (0.8999, "MOSTLY_TRUE"),
            (0.70, "MOSTLY_TRUE"),
            (0.6999, "HALF_TRUE"),
            (0.45, "HALF_TRUE"),
            (0.4499, "MOSTLY_FALSE"),
            (0.25, "MOSTLY_FALSE"),
            (0.2499, "FALSE"),
            (0.10, "FALSE"),
            (0.0999, "PANTS_FIRE"),
            (0.00, "PANTS_FIRE"),
        ],
    )
    def test_boundary_values(self, mapper, score, expected_code):
        resolved = ResolvedObservationSet(observations=[], synthesis_signal_count=10)
        code, cwe, reason = mapper.map_verdict(score, resolved)
        assert code == expected_code


class TestUnverifiable:
    """None score maps to UNVERIFIABLE."""

    def test_none_score(self, mapper):
        resolved = ResolvedObservationSet(observations=[], synthesis_signal_count=3)
        code, cwe, reason = mapper.map_verdict(None, resolved)
        assert code == "UNVERIFIABLE"
        assert cwe == "UNVERIFIABLE^Unverifiable^FCK"
        assert reason == ""


class TestCWEFormat:
    """Verify CWE value format for all verdict tiers."""

    @pytest.mark.parametrize(
        "score, expected_cwe",
        [
            (0.95, "TRUE^True^POLITIFACT"),
            (0.75, "MOSTLY_TRUE^Mostly True^POLITIFACT"),
            (0.55, "HALF_TRUE^Half True^POLITIFACT"),
            (0.35, "MOSTLY_FALSE^Mostly False^POLITIFACT"),
            (0.18, "FALSE^False^POLITIFACT"),
            (0.04, "PANTS_FIRE^Pants on Fire^POLITIFACT"),
        ],
    )
    def test_cwe_values(self, mapper, score, expected_cwe):
        resolved = ResolvedObservationSet(observations=[], synthesis_signal_count=10)
        _, cwe, _ = mapper.map_verdict(score, resolved)
        assert cwe == expected_cwe


class TestClaimReviewOverride:
    """ClaimReview override logic."""

    def test_override_fires(self, mapper):
        """Override fires when match TRUE, score >= 0.90, verdicts differ."""
        resolved = _resolved_with_claimreview(
            cr_verdict="TRUE^True^POLITIFACT",
            cr_score="0.95",
        )
        # Swarm score maps to MOSTLY_FALSE (0.35)
        code, cwe, reason = mapper.map_verdict(0.35, resolved)
        assert code == "TRUE"
        assert cwe == "TRUE^True^POLITIFACT"
        assert "ClaimReview override" in reason
        assert "match_score=0.95" in reason
        assert "MOSTLY_FALSE" in reason

    def test_override_not_fired_same_verdict(self, mapper):
        """Override does not fire when verdicts agree."""
        resolved = _resolved_with_claimreview(
            cr_verdict="TRUE^True^POLITIFACT",
            cr_score="0.95",
        )
        code, cwe, reason = mapper.map_verdict(0.95, resolved)
        assert code == "TRUE"
        assert reason == ""

    def test_override_not_fired_low_score(self, mapper):
        """Override does not fire when match_score < 0.90."""
        resolved = _resolved_with_claimreview(
            cr_verdict="TRUE^True^POLITIFACT",
            cr_score="0.85",
        )
        code, cwe, reason = mapper.map_verdict(0.35, resolved)
        assert code == "MOSTLY_FALSE"
        assert reason == ""

    def test_override_not_fired_no_match(self, mapper):
        """Override does not fire when CLAIMREVIEW_MATCH is FALSE."""
        resolved = _resolved_with_claimreview(
            cr_match="FALSE^No Match^FCK",
            cr_verdict="TRUE^True^POLITIFACT",
            cr_score="0.95",
        )
        code, cwe, reason = mapper.map_verdict(0.35, resolved)
        assert code == "MOSTLY_FALSE"
        assert reason == ""

    def test_override_not_fired_unverifiable(self, mapper):
        """Override does not fire when confidence_score is None."""
        resolved = _resolved_with_claimreview(
            cr_verdict="TRUE^True^POLITIFACT",
            cr_score="0.95",
        )
        code, cwe, reason = mapper.map_verdict(None, resolved)
        assert code == "UNVERIFIABLE"
        assert reason == ""

    def test_override_reason_contains_source(self, mapper):
        """Override reason includes ClaimReview source name."""
        resolved = _resolved_with_claimreview(
            cr_verdict="FALSE^False^POLITIFACT",
            cr_score="0.92",
            cr_source="Snopes",
        )
        code, cwe, reason = mapper.map_verdict(0.95, resolved)
        assert code == "FALSE"
        assert "Snopes" in reason
        assert "match_score=0.92" in reason

    def test_override_reason_empty_when_no_override(self, mapper):
        """Override reason is empty string when no override occurs."""
        resolved = ResolvedObservationSet(observations=[], synthesis_signal_count=10)
        _, _, reason = mapper.map_verdict(0.55, resolved)
        assert reason == ""
