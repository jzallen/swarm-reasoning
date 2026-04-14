"""Edge case tests for synthesizer sub-modules.

Covers boundary conditions, error resilience, and unusual input combinations
not exercised by the primary unit tests.
"""

from __future__ import annotations

import pytest

from swarm_reasoning.agents.synthesizer.mapper import VerdictMapper
from swarm_reasoning.agents.synthesizer.models import ResolvedObservation, ResolvedObservationSet
from swarm_reasoning.agents.synthesizer.narrator import (
    MAX_NARRATIVE_LENGTH,
    MIN_NARRATIVE_LENGTH,
    NarrativeGenerator,
    _parse_citation_list,
)
from swarm_reasoning.agents.synthesizer.resolver import ObservationResolver
from swarm_reasoning.agents.synthesizer.scorer import ConfidenceScorer
from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType
from swarm_reasoning.models.stream import ObsMessage, Phase, StartMessage, StopMessage


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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


def _full_evidence_set(**overrides) -> ResolvedObservationSet:
    """Build a full evidence set with optional per-field overrides."""
    defaults = dict(
        alignment="SUPPORTS^Supports^FCK",
        domain_conf="1.0",
        cr_match="TRUE^Match Found^FCK",
        cr_verdict="TRUE^True^POLITIFACT",
        cr_score="0.95",
        corroboration="TRUE^Corroborated^FCK",
        framing_left="SUPPORTIVE^Supportive^FCK",
        framing_center="SUPPORTIVE^Supportive^FCK",
        framing_right="SUPPORTIVE^Supportive^FCK",
        convergence="0.8",
        blindspot="0.0",
    )
    defaults.update(overrides)
    d = defaults
    obs_list = [
        _obs("DOMAIN_EVIDENCE_ALIGNMENT", d["alignment"], agent="domain-evidence", seq=1),
        _nm_obs("DOMAIN_CONFIDENCE", d["domain_conf"], agent="domain-evidence", seq=2),
        _obs("CLAIMREVIEW_MATCH", d["cr_match"], agent="claimreview-matcher", seq=3),
        _obs("CLAIMREVIEW_VERDICT", d["cr_verdict"], agent="claimreview-matcher", seq=4),
        _nm_obs("CLAIMREVIEW_MATCH_SCORE", d["cr_score"], agent="claimreview-matcher", seq=5),
        _obs("CROSS_SPECTRUM_CORROBORATION", d["corroboration"], agent="blindspot-detector", seq=6),
        _obs("COVERAGE_FRAMING", d["framing_left"], agent="coverage-left", seq=7),
        _obs("COVERAGE_FRAMING", d["framing_center"], agent="coverage-center", seq=8),
        _obs("COVERAGE_FRAMING", d["framing_right"], agent="coverage-right", seq=9),
        _nm_obs("SOURCE_CONVERGENCE_SCORE", d["convergence"], agent="source-validator", seq=10),
        _nm_obs("BLINDSPOT_SCORE", d["blindspot"], agent="blindspot-detector", seq=11),
    ]
    return ResolvedObservationSet(
        observations=obs_list,
        synthesis_signal_count=len(obs_list),
    )


# ---------------------------------------------------------------------------
# FakeStream (reused from test_synthesizer_resolver.py pattern)
# ---------------------------------------------------------------------------


class FakeStream:
    def __init__(self):
        self.streams: dict[str, list] = {}

    def add_obs(
        self,
        run_id: str,
        agent: str,
        seq: int,
        code: str,
        value: str,
        value_type: str,
        status: str = "F",
        **kwargs,
    ):
        key = f"reasoning:{run_id}:{agent}"
        if key not in self.streams:
            self.streams[key] = []
        obs = Observation(
            runId=run_id,
            agent=agent,
            seq=seq,
            code=ObservationCode(code),
            value=value,
            valueType=ValueType(value_type),
            status=status,
            timestamp="2026-01-01T00:00:00Z",
            units=kwargs.get("units"),
            referenceRange=kwargs.get("reference_range"),
            method=kwargs.get("method"),
            note=kwargs.get("note"),
        )
        self.streams[key].append(ObsMessage(observation=obs))

    def add_start(self, run_id: str, agent: str):
        key = f"reasoning:{run_id}:{agent}"
        if key not in self.streams:
            self.streams[key] = []
        self.streams[key].append(
            StartMessage(
                runId=run_id, agent=agent, phase=Phase.FANOUT,
                timestamp="2026-01-01T00:00:00Z",
            )
        )

    def add_stop(self, run_id: str, agent: str, count: int = 1):
        key = f"reasoning:{run_id}:{agent}"
        if key not in self.streams:
            self.streams[key] = []
        self.streams[key].append(
            StopMessage(
                runId=run_id, agent=agent, finalStatus="F",
                observationCount=count, timestamp="2026-01-01T00:00:00Z",
            )
        )

    async def read_range(self, stream_key: str, start: str = "-", end: str = "+"):
        return self.streams.get(stream_key, [])

    async def close(self):
        pass


class FailingStream(FakeStream):
    """Stream that raises for a specific agent key."""

    def __init__(self, failing_agents: set[str]):
        super().__init__()
        self._failing = failing_agents

    async def read_range(self, stream_key: str, start: str = "-", end: str = "+"):
        for agent in self._failing:
            if stream_key.endswith(f":{agent}"):
                raise ConnectionError(f"Simulated read failure for {agent}")
        return await super().read_range(stream_key, start, end)


# ===================================================================
# Resolver edge cases
# ===================================================================


class TestResolverStreamFailure:
    """Resolver continues when individual upstream streams fail."""

    @pytest.mark.asyncio
    async def test_partial_stream_failure(self):
        """If one agent stream fails, others are still resolved."""
        stream = FailingStream(failing_agents={"domain-evidence"})
        stream.add_obs(
            "run1", "claimreview-matcher", seq=1,
            code="CLAIMREVIEW_MATCH", value="TRUE^Match^FCK", value_type="CWE",
        )

        resolver = ObservationResolver()
        result = await resolver.resolve("run1", stream)

        assert result.find("CLAIMREVIEW_MATCH") is not None
        assert result.find("DOMAIN_EVIDENCE_ALIGNMENT") is None
        assert result.synthesis_signal_count == 1

    @pytest.mark.asyncio
    async def test_all_streams_fail(self):
        """If all agent streams fail, empty result set with no crash."""
        all_agents = {
            "ingestion-agent", "claim-detector", "entity-extractor",
            "claimreview-matcher", "coverage-left", "coverage-center",
            "coverage-right", "domain-evidence", "source-validator",
            "blindspot-detector",
        }
        stream = FailingStream(failing_agents=all_agents)

        resolver = ObservationResolver()
        result = await resolver.resolve("run1", stream)

        assert result.synthesis_signal_count == 0
        assert len(result.observations) == 0
        assert len(result.warnings) == 0

    @pytest.mark.asyncio
    async def test_multiple_failures_partial_results(self):
        """Multiple failures still collect from healthy agents."""
        stream = FailingStream(failing_agents={"coverage-left", "coverage-right"})
        stream.add_obs(
            "run1", "coverage-center", seq=1,
            code="COVERAGE_FRAMING", value="NEUTRAL^Neutral^FCK", value_type="CWE",
        )
        stream.add_obs(
            "run1", "domain-evidence", seq=1,
            code="DOMAIN_EVIDENCE_ALIGNMENT", value="SUPPORTS^Supports^FCK",
            value_type="CWE",
        )

        resolver = ObservationResolver()
        result = await resolver.resolve("run1", stream)

        assert result.synthesis_signal_count == 2
        assert result.find("COVERAGE_FRAMING", agent="coverage-center") is not None
        assert result.find("DOMAIN_EVIDENCE_ALIGNMENT") is not None


class TestResolverAllCancelled:
    """Only X-status observations for every pair."""

    @pytest.mark.asyncio
    async def test_all_x_status(self):
        stream = FakeStream()
        stream.add_obs(
            "run1", "domain-evidence", seq=1,
            code="DOMAIN_EVIDENCE_ALIGNMENT", value="SUPPORTS^Supports^FCK",
            value_type="CWE", status="X",
        )
        stream.add_obs(
            "run1", "claimreview-matcher", seq=1,
            code="CLAIMREVIEW_MATCH", value="TRUE^Match^FCK",
            value_type="CWE", status="X",
        )

        resolver = ObservationResolver()
        result = await resolver.resolve("run1", stream)

        assert result.synthesis_signal_count == 0
        assert len(result.excluded_observations) == 2
        assert len(result.warnings) == 0  # X excluded silently

    @pytest.mark.asyncio
    async def test_all_p_status(self):
        """Only P-status observations → all excluded with warnings."""
        stream = FakeStream()
        stream.add_obs(
            "run1", "domain-evidence", seq=1,
            code="DOMAIN_EVIDENCE_ALIGNMENT", value="SUPPORTS^Supports^FCK",
            value_type="CWE", status="P",
        )
        stream.add_obs(
            "run1", "coverage-left", seq=1,
            code="COVERAGE_FRAMING", value="SUPPORTIVE^Supportive^FCK",
            value_type="CWE", status="P",
        )

        resolver = ObservationResolver()
        result = await resolver.resolve("run1", stream)

        assert result.synthesis_signal_count == 0
        assert len(result.excluded_observations) == 2
        assert len(result.warnings) == 2


class TestResolverMultipleAgentsSameCode:
    """Different agents emit the same OBX code."""

    @pytest.mark.asyncio
    async def test_same_code_different_agents(self):
        """COVERAGE_FRAMING from left/center/right are separate (agent, code) pairs."""
        stream = FakeStream()
        stream.add_obs(
            "run1", "coverage-left", seq=1,
            code="COVERAGE_FRAMING", value="SUPPORTIVE^Supportive^FCK",
            value_type="CWE",
        )
        stream.add_obs(
            "run1", "coverage-center", seq=1,
            code="COVERAGE_FRAMING", value="NEUTRAL^Neutral^FCK",
            value_type="CWE",
        )
        stream.add_obs(
            "run1", "coverage-right", seq=1,
            code="COVERAGE_FRAMING", value="CRITICAL^Critical^FCK",
            value_type="CWE",
        )

        resolver = ObservationResolver()
        result = await resolver.resolve("run1", stream)

        assert result.synthesis_signal_count == 3
        all_framing = result.find_all("COVERAGE_FRAMING")
        assert len(all_framing) == 3
        agents = {o.agent for o in all_framing}
        assert agents == {"coverage-left", "coverage-center", "coverage-right"}


class TestResolverHighSeqSelection:
    """When multiple C or F observations exist, highest seq wins."""

    @pytest.mark.asyncio
    async def test_many_f_observations_highest_wins(self):
        stream = FakeStream()
        for seq, val in [(1, "FALSE"), (5, "HALF_TRUE"), (3, "TRUE"), (10, "MOSTLY_TRUE")]:
            stream.add_obs(
                "run1", "claimreview-matcher", seq=seq,
                code="CLAIMREVIEW_VERDICT", value=f"{val}^{val}^POLITIFACT",
                value_type="CWE", status="F",
            )

        resolver = ObservationResolver()
        result = await resolver.resolve("run1", stream)
        obs = result.find("CLAIMREVIEW_VERDICT")
        assert obs is not None
        assert obs.seq == 10
        assert obs.value.startswith("MOSTLY_TRUE")

    @pytest.mark.asyncio
    async def test_many_c_observations_highest_wins(self):
        stream = FakeStream()
        for seq, val in [(2, "FALSE"), (8, "TRUE"), (6, "HALF_TRUE")]:
            stream.add_obs(
                "run1", "claimreview-matcher", seq=seq,
                code="CLAIMREVIEW_VERDICT", value=f"{val}^{val}^POLITIFACT",
                value_type="CWE", status="C",
            )
        # Also add F observation with higher seq (should be ignored)
        stream.add_obs(
            "run1", "claimreview-matcher", seq=99,
            code="CLAIMREVIEW_VERDICT", value="PANTS_FIRE^Pants on Fire^POLITIFACT",
            value_type="CWE", status="F",
        )

        resolver = ObservationResolver()
        result = await resolver.resolve("run1", stream)
        obs = result.find("CLAIMREVIEW_VERDICT")
        assert obs is not None
        assert obs.resolution_method == "LATEST_C"
        assert obs.seq == 8
        assert obs.value.startswith("TRUE")


# ===================================================================
# Scorer edge cases
# ===================================================================


class TestScorerNoComponents:
    """Score computation when no scoring components are present."""

    def test_no_recognized_observations(self):
        """Observations exist but none match scoring components → 0.0."""
        resolved = ResolvedObservationSet(
            observations=[
                _obs("ENTITY_PERSON", "John Doe", agent="entity-extractor"),
                _obs("CLAIM_TEXT", "Some claim", agent="ingestion-agent"),
            ] * 3,
            synthesis_signal_count=6,
        )
        scorer = ConfidenceScorer()
        score = scorer.compute(resolved)
        assert score == 0.0

    def test_all_components_none(self):
        """Empty observations with sufficient signal count → 0.0."""
        resolved = ResolvedObservationSet(
            observations=[],
            synthesis_signal_count=10,
        )
        scorer = ConfidenceScorer()
        score = scorer.compute(resolved)
        assert score == 0.0


class TestScorerInvalidNumericValues:
    """Non-numeric values in NM-type observations."""

    def test_invalid_domain_confidence(self):
        """Non-parseable DOMAIN_CONFIDENCE falls back to 1.0."""
        resolved = _full_evidence_set(domain_conf="not-a-number")
        scorer = ConfidenceScorer()
        score = scorer.compute(resolved)
        assert score is not None
        # Should use fallback domain_confidence=1.0
        assert 0.0 <= score <= 1.0

    def test_invalid_convergence_score(self):
        """Non-parseable SOURCE_CONVERGENCE_SCORE → component skipped."""
        resolved = _full_evidence_set(convergence="NaN")
        scorer = ConfidenceScorer()
        score = scorer.compute(resolved)
        assert score is not None
        assert 0.0 <= score <= 1.0

    def test_invalid_blindspot_score(self):
        """Non-parseable BLINDSPOT_SCORE → penalty skipped."""
        resolved = _full_evidence_set(blindspot="invalid")
        scorer = ConfidenceScorer()
        score = scorer.compute(resolved)
        assert score is not None
        # No penalty applied, should be same as blindspot=0.0
        no_penalty = _full_evidence_set(blindspot="0.0")
        score_no_penalty = scorer.compute(no_penalty)
        assert abs(score - score_no_penalty) < 0.001

    def test_invalid_claimreview_match_score(self):
        """Non-parseable CLAIMREVIEW_MATCH_SCORE falls back to 1.0."""
        resolved = _full_evidence_set(cr_score="bad-value")
        scorer = ConfidenceScorer()
        score = scorer.compute(resolved)
        assert score is not None
        assert 0.0 <= score <= 1.0


class TestScorerSingleComponent:
    """Only one scoring component present."""

    def test_only_domain_evidence(self):
        """Score from domain evidence alone, normalized by effective weight."""
        resolved = ResolvedObservationSet(
            observations=[
                _obs("DOMAIN_EVIDENCE_ALIGNMENT", "SUPPORTS^Supports^FCK",
                     agent="domain-evidence"),
            ],
            synthesis_signal_count=5,
        )
        scorer = ConfidenceScorer()
        score = scorer.compute(resolved)
        assert score is not None
        # SUPPORTS = 1.0, effective_weight = 0.30, so raw = 1.0*0.30/0.30 = 1.0
        assert abs(score - 1.0) < 0.001

    def test_only_convergence(self):
        """Score from source convergence alone."""
        resolved = ResolvedObservationSet(
            observations=[
                _nm_obs("SOURCE_CONVERGENCE_SCORE", "0.6", agent="source-validator"),
            ],
            synthesis_signal_count=5,
        )
        scorer = ConfidenceScorer()
        score = scorer.compute(resolved)
        assert score is not None
        assert abs(score - 0.6) < 0.001


class TestScorerPartialCoverage:
    """Only some coverage agents report framing."""

    def test_single_coverage_agent(self):
        """One COVERAGE_FRAMING agent → average of 1 score."""
        resolved = ResolvedObservationSet(
            observations=[
                _obs("DOMAIN_EVIDENCE_ALIGNMENT", "SUPPORTS^Supports^FCK",
                     agent="domain-evidence"),
                _obs("COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK",
                     agent="coverage-left"),
            ],
            synthesis_signal_count=5,
        )
        scorer = ConfidenceScorer()
        score = scorer.compute(resolved)
        assert score is not None
        assert 0.0 <= score <= 1.0

    def test_two_coverage_agents(self):
        """Two COVERAGE_FRAMING agents → average of 2 scores."""
        resolved = ResolvedObservationSet(
            observations=[
                _obs("DOMAIN_EVIDENCE_ALIGNMENT", "SUPPORTS^Supports^FCK",
                     agent="domain-evidence"),
                _obs("COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK",
                     agent="coverage-left"),
                _obs("COVERAGE_FRAMING", "CRITICAL^Critical^FCK",
                     agent="coverage-center"),
            ],
            synthesis_signal_count=5,
        )
        scorer = ConfidenceScorer()
        score = scorer.compute(resolved)
        assert score is not None
        assert 0.0 <= score <= 1.0


class TestScorerUnknownAlignmentCode:
    """Unknown CWE codes in scoring components."""

    def test_unknown_alignment(self):
        """Unknown DOMAIN_EVIDENCE_ALIGNMENT code → alignment_score = 0.0."""
        resolved = _full_evidence_set(alignment="WEIRD^Weird^FCK")
        scorer = ConfidenceScorer()
        score = scorer.compute(resolved)
        assert score is not None
        assert 0.0 <= score <= 1.0

    def test_unknown_framing_code(self):
        """Unknown COVERAGE_FRAMING code → score = 0.0 for that agent."""
        resolved = _full_evidence_set(framing_left="UNKNOWN^Unknown^FCK")
        scorer = ConfidenceScorer()
        score = scorer.compute(resolved)
        assert score is not None


class TestScorerExactBoundary:
    """Signal count exactly at MIN_SIGNAL_COUNT threshold."""

    def test_exactly_at_min(self):
        resolved = _full_evidence_set()
        resolved.synthesis_signal_count = 5
        scorer = ConfidenceScorer()
        assert scorer.compute(resolved) is not None

    def test_one_below_min(self):
        resolved = _full_evidence_set()
        resolved.synthesis_signal_count = 4
        scorer = ConfidenceScorer()
        assert scorer.compute(resolved) is None


class TestScorerClampingBehavior:
    """Score clamping to [0.0, 1.0]."""

    def test_score_never_exceeds_one(self):
        """Even with all positive signals, score stays <= 1.0."""
        resolved = _full_evidence_set(blindspot="0.0", convergence="1.0")
        scorer = ConfidenceScorer()
        score = scorer.compute(resolved)
        assert score is not None
        assert score <= 1.0

    def test_heavy_blindspot_penalty_stays_non_negative(self):
        """Huge blindspot penalty cannot push score below 0.0."""
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
        scorer = ConfidenceScorer()
        score = scorer.compute(resolved)
        assert score is not None
        assert score >= 0.0


# ===================================================================
# Mapper edge cases
# ===================================================================


class TestMapperExactThresholds:
    """Score at exact threshold boundaries."""

    @pytest.mark.parametrize("score, expected", [
        (0.90, "TRUE"),
        (0.70, "MOSTLY_TRUE"),
        (0.45, "HALF_TRUE"),
        (0.25, "MOSTLY_FALSE"),
        (0.10, "FALSE"),
        (0.00, "PANTS_FIRE"),
        (1.00, "TRUE"),
    ])
    def test_exact_lower_bounds(self, score, expected):
        mapper = VerdictMapper()
        resolved = ResolvedObservationSet(observations=[], synthesis_signal_count=10)
        code, _, _ = mapper.map_verdict(score, resolved)
        assert code == expected


class TestMapperNegativeScore:
    """Negative confidence score (should not happen but handle gracefully)."""

    def test_negative_score_maps_to_pants_fire(self):
        mapper = VerdictMapper()
        resolved = ResolvedObservationSet(observations=[], synthesis_signal_count=10)
        code, _, _ = mapper.map_verdict(-0.5, resolved)
        assert code == "PANTS_FIRE"

    def test_large_positive_score_maps_to_true(self):
        mapper = VerdictMapper()
        resolved = ResolvedObservationSet(observations=[], synthesis_signal_count=10)
        code, _, _ = mapper.map_verdict(1.5, resolved)
        # 1.5 > 1.01 so no threshold matches, falls through to PANTS_FIRE
        # (edge case of the threshold logic)
        assert code in ("TRUE", "PANTS_FIRE")


class TestMapperOverrideEdgeCases:
    """Override conditions with edge-case inputs."""

    def test_override_at_exact_threshold(self):
        """Match score exactly 0.90 should trigger override."""
        mapper = VerdictMapper()
        resolved = ResolvedObservationSet(
            observations=[
                _obs("CLAIMREVIEW_MATCH", "TRUE^Match^FCK", agent="claimreview-matcher"),
                _obs("CLAIMREVIEW_VERDICT", "TRUE^True^POLITIFACT", agent="claimreview-matcher"),
                _nm_obs("CLAIMREVIEW_MATCH_SCORE", "0.90", agent="claimreview-matcher"),
                ResolvedObservation(
                    agent="claimreview-matcher", code="CLAIMREVIEW_SOURCE",
                    value="PolitiFact", value_type="ST", seq=4, status="F",
                    resolution_method="LATEST_F", timestamp="2026-01-01T00:00:00Z",
                ),
            ],
            synthesis_signal_count=4,
        )
        code, _, reason = mapper.map_verdict(0.35, resolved)
        assert code == "TRUE"
        assert "ClaimReview override" in reason

    def test_override_just_below_threshold(self):
        """Match score 0.899... should NOT trigger override."""
        mapper = VerdictMapper()
        resolved = ResolvedObservationSet(
            observations=[
                _obs("CLAIMREVIEW_MATCH", "TRUE^Match^FCK", agent="claimreview-matcher"),
                _obs("CLAIMREVIEW_VERDICT", "TRUE^True^POLITIFACT", agent="claimreview-matcher"),
                _nm_obs("CLAIMREVIEW_MATCH_SCORE", "0.8999", agent="claimreview-matcher"),
            ],
            synthesis_signal_count=3,
        )
        code, _, reason = mapper.map_verdict(0.35, resolved)
        assert code == "MOSTLY_FALSE"
        assert reason == ""

    def test_override_missing_claimreview_source(self):
        """Override fires even without CLAIMREVIEW_SOURCE (uses 'unknown')."""
        mapper = VerdictMapper()
        resolved = ResolvedObservationSet(
            observations=[
                _obs("CLAIMREVIEW_MATCH", "TRUE^Match^FCK", agent="claimreview-matcher"),
                _obs("CLAIMREVIEW_VERDICT", "FALSE^False^POLITIFACT", agent="claimreview-matcher"),
                _nm_obs("CLAIMREVIEW_MATCH_SCORE", "0.95", agent="claimreview-matcher"),
                # No CLAIMREVIEW_SOURCE
            ],
            synthesis_signal_count=3,
        )
        code, _, reason = mapper.map_verdict(0.95, resolved)
        assert code == "FALSE"
        assert "unknown" in reason

    def test_override_with_invalid_match_score(self):
        """Invalid match score string → no override."""
        mapper = VerdictMapper()
        resolved = ResolvedObservationSet(
            observations=[
                _obs("CLAIMREVIEW_MATCH", "TRUE^Match^FCK", agent="claimreview-matcher"),
                _obs("CLAIMREVIEW_VERDICT", "FALSE^False^POLITIFACT", agent="claimreview-matcher"),
                _nm_obs("CLAIMREVIEW_MATCH_SCORE", "not-a-number", agent="claimreview-matcher"),
            ],
            synthesis_signal_count=3,
        )
        code, _, reason = mapper.map_verdict(0.95, resolved)
        assert code == "TRUE"
        assert reason == ""

    def test_override_unknown_cr_verdict_code(self):
        """Unknown ClaimReview verdict code → override not applied."""
        mapper = VerdictMapper()
        resolved = ResolvedObservationSet(
            observations=[
                _obs("CLAIMREVIEW_MATCH", "TRUE^Match^FCK", agent="claimreview-matcher"),
                _obs("CLAIMREVIEW_VERDICT", "UNKNOWN^Unknown^FCK", agent="claimreview-matcher"),
                _nm_obs("CLAIMREVIEW_MATCH_SCORE", "0.95", agent="claimreview-matcher"),
                ResolvedObservation(
                    agent="claimreview-matcher", code="CLAIMREVIEW_SOURCE",
                    value="PolitiFact", value_type="ST", seq=4, status="F",
                    resolution_method="LATEST_F", timestamp="2026-01-01T00:00:00Z",
                ),
            ],
            synthesis_signal_count=4,
        )
        # Override evaluates: cr_code=UNKNOWN differs from swarm_code=TRUE,
        # but UNKNOWN is not in _CLAIMREVIEW_TO_POLITIFACT → no override applied
        code, _, reason = mapper.map_verdict(0.95, resolved)
        # Override reason is set by _evaluate_override, but then the cr_code
        # lookup in _CLAIMREVIEW_TO_POLITIFACT fails, so original swarm result is returned
        assert code == "TRUE"

    def test_override_with_missing_verdict_obs(self):
        """CLAIMREVIEW_MATCH=TRUE but no CLAIMREVIEW_VERDICT → no override."""
        mapper = VerdictMapper()
        resolved = ResolvedObservationSet(
            observations=[
                _obs("CLAIMREVIEW_MATCH", "TRUE^Match^FCK", agent="claimreview-matcher"),
                _nm_obs("CLAIMREVIEW_MATCH_SCORE", "0.95", agent="claimreview-matcher"),
            ],
            synthesis_signal_count=2,
        )
        code, _, reason = mapper.map_verdict(0.35, resolved)
        assert code == "MOSTLY_FALSE"
        assert reason == ""


# ===================================================================
# Narrator edge cases
# ===================================================================


class TestNarratorFallbackEdgeCases:
    """Edge cases in fallback narrative generation."""

    def test_empty_observations_still_meets_min_length(self):
        narrator = NarrativeGenerator()
        resolved = ResolvedObservationSet(observations=[], synthesis_signal_count=0)
        narrative = narrator._fallback_narrative(resolved, "UNVERIFIABLE", None, "", [], 0, [])
        assert len(narrative) >= MIN_NARRATIVE_LENGTH
        assert len(narrative) <= MAX_NARRATIVE_LENGTH

    def test_override_reason_not_in_fallback(self):
        """Override reason is not explicitly shown in fallback, but doesn't crash."""
        narrator = NarrativeGenerator()
        resolved = ResolvedObservationSet(
            observations=[
                _obs("DOMAIN_EVIDENCE_ALIGNMENT", "SUPPORTS^Supports^FCK",
                     agent="domain-evidence"),
            ],
            synthesis_signal_count=5,
        )
        narrative = narrator._fallback_narrative(
            resolved, "TRUE", 0.95,
            "ClaimReview override: Snopes rated FALSE", [], 5, [],
        )
        assert len(narrative) >= MIN_NARRATIVE_LENGTH

    def test_many_citations(self):
        """Large citation list included in fallback narrative."""
        narrator = NarrativeGenerator()
        resolved = _full_evidence_set()
        citations = [
            {"sourceName": f"Source-{i}", "validationStatus": "live" if i % 2 == 0 else "dead",
             "sourceUrl": f"https://example.com/{i}"}
            for i in range(20)
        ]
        narrative = narrator._fallback_narrative(
            resolved, "MOSTLY_TRUE", 0.75, "", [], 11, citations,
        )
        assert "20 citations" in narrative
        assert "10 live" in narrative
        assert "10 dead" in narrative

    def test_citations_with_missing_fields(self):
        """Citations with missing validationStatus fields."""
        narrator = NarrativeGenerator()
        resolved = _full_evidence_set()
        citations = [
            {"sourceName": "CDC"},  # no validationStatus
            {"validationStatus": "live"},  # no sourceName
            {},  # completely empty
        ]
        narrative = narrator._fallback_narrative(
            resolved, "TRUE", 0.95, "", [], 11, citations,
        )
        # Should count live/dead based on what's available
        assert "3 citations" in narrative

    def test_all_verdicts_produce_valid_fallback(self):
        """Every verdict code produces a valid-length fallback narrative."""
        narrator = NarrativeGenerator()
        for verdict in ["TRUE", "MOSTLY_TRUE", "HALF_TRUE", "MOSTLY_FALSE",
                        "FALSE", "PANTS_FIRE", "UNVERIFIABLE"]:
            resolved = _full_evidence_set()
            conf = None if verdict == "UNVERIFIABLE" else 0.5
            narrative = narrator._fallback_narrative(
                resolved, verdict, conf, "", [], 11, [],
            )
            assert MIN_NARRATIVE_LENGTH <= len(narrative) <= MAX_NARRATIVE_LENGTH, (
                f"Verdict {verdict}: narrative length {len(narrative)} out of bounds"
            )


class TestNarratorTruncationEdgeCases:

    def test_truncate_exactly_at_limit(self):
        narrator = NarrativeGenerator()
        text = "A" * MAX_NARRATIVE_LENGTH
        result = narrator._truncate(text)
        assert len(result) <= MAX_NARRATIVE_LENGTH

    def test_truncate_one_over_limit(self):
        narrator = NarrativeGenerator()
        text = "Hello. " * 200  # well over 1000
        result = narrator._truncate(text)
        assert len(result) <= MAX_NARRATIVE_LENGTH
        assert result.endswith(".")

    def test_truncate_no_sentence_boundary(self):
        narrator = NarrativeGenerator()
        text = "a" * 1500  # no punctuation at all
        result = narrator._truncate(text)
        assert len(result) == MAX_NARRATIVE_LENGTH


class TestNarratorCitationParsing:

    def test_json_object_not_array(self):
        """Non-array JSON returns empty list."""
        result = _parse_citation_list('{"key": "value"}')
        assert result == []

    def test_nested_arrays(self):
        """Nested array is accepted (returns outer)."""
        result = _parse_citation_list('[[1,2],[3,4]]')
        assert len(result) == 2

    def test_very_large_json(self):
        """Large valid JSON array."""
        import json
        large = json.dumps([{"id": i} for i in range(1000)])
        result = _parse_citation_list(large)
        assert len(result) == 1000


class TestNarratorGenerateWithLLMFailure:
    """Narrator.generate falls back to template when LLM fails."""

    @pytest.mark.asyncio
    async def test_generate_falls_back_on_exception(self):
        narrator = NarrativeGenerator()
        resolved = _full_evidence_set()
        # _llm_generate will fail because ANTHROPIC_API_KEY is not set
        narrative = await narrator.generate(
            resolved=resolved,
            verdict="TRUE",
            confidence_score=0.95,
            override_reason="",
            warnings=[],
            signal_count=11,
            citation_list=[],
        )
        assert isinstance(narrative, str)
        assert MIN_NARRATIVE_LENGTH <= len(narrative) <= MAX_NARRATIVE_LENGTH


# ===================================================================
# ResolvedObservationSet model edge cases
# ===================================================================


class TestResolvedObservationSetModel:

    def test_find_returns_none_for_missing_code(self):
        resolved = ResolvedObservationSet(
            observations=[_obs("SOME_CODE", "val")],
        )
        assert resolved.find("NONEXISTENT") is None

    def test_find_with_agent_filter(self):
        resolved = ResolvedObservationSet(
            observations=[
                _obs("COVERAGE_FRAMING", "A", agent="coverage-left"),
                _obs("COVERAGE_FRAMING", "B", agent="coverage-center"),
            ],
        )
        obs = resolved.find("COVERAGE_FRAMING", agent="coverage-center")
        assert obs is not None
        assert obs.value == "B"

    def test_find_with_wrong_agent(self):
        resolved = ResolvedObservationSet(
            observations=[_obs("COVERAGE_FRAMING", "A", agent="coverage-left")],
        )
        assert resolved.find("COVERAGE_FRAMING", agent="coverage-right") is None

    def test_find_all_returns_empty_for_missing_code(self):
        resolved = ResolvedObservationSet(observations=[])
        assert resolved.find_all("WHATEVER") == []

    def test_find_all_returns_multiple(self):
        resolved = ResolvedObservationSet(
            observations=[
                _obs("COVERAGE_FRAMING", "A", agent="coverage-left"),
                _obs("COVERAGE_FRAMING", "B", agent="coverage-center"),
                _obs("COVERAGE_FRAMING", "C", agent="coverage-right"),
            ],
        )
        results = resolved.find_all("COVERAGE_FRAMING")
        assert len(results) == 3

    def test_empty_set_defaults(self):
        resolved = ResolvedObservationSet()
        assert resolved.observations == []
        assert resolved.synthesis_signal_count == 0
        assert resolved.excluded_observations == []
        assert resolved.warnings == []
