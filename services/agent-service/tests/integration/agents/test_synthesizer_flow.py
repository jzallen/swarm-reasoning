"""Integration tests for the synthesizer agent full pipeline.

Tests the end-to-end flow: resolve → score → map → narrate,
using mocked stream/Redis to verify the complete tool chain
produces correct observations and output.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.synthesizer.handler import SynthesizerHandler
from swarm_reasoning.agents.synthesizer.models import ResolvedObservation, ResolvedObservationSet
from swarm_reasoning.agents.synthesizer.tools.map_verdict import map_verdict
from swarm_reasoning.agents.synthesizer.tools.narrate import generate_narrative
from swarm_reasoning.agents.synthesizer.tools.resolve import (
    _serialize_resolved,
    resolve_observations,
)
from swarm_reasoning.agents.synthesizer.tools.score import (
    _deserialize_resolved,
    compute_confidence,
)
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType
from swarm_reasoning.models.stream import ObsMessage, Phase, StartMessage, StopMessage


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _obs(code: str, value: str, agent: str = "test-agent", seq: int = 1,
         value_type: str = "CWE") -> ResolvedObservation:
    return ResolvedObservation(
        agent=agent, code=code, value=value, value_type=value_type,
        seq=seq, status="F", resolution_method="LATEST_F",
        timestamp="2026-01-01T00:00:00Z",
    )


def _make_context() -> AgentContext:
    stream = MagicMock()
    stream.publish = AsyncMock()
    redis_client = MagicMock()
    return AgentContext(
        stream=stream, redis_client=redis_client,
        run_id="test-run-int", sk="reasoning:test-run-int:synthesizer",
        agent_name="synthesizer",
    )


def _full_resolved_set() -> ResolvedObservationSet:
    """Full 11-observation evidence set for integration testing."""
    return ResolvedObservationSet(
        observations=[
            _obs("DOMAIN_EVIDENCE_ALIGNMENT", "SUPPORTS^Supports^FCK",
                 agent="domain-evidence", seq=1),
            _obs("DOMAIN_CONFIDENCE", "0.9", agent="domain-evidence", seq=2,
                 value_type="NM"),
            _obs("CLAIMREVIEW_MATCH", "TRUE^Match Found^FCK",
                 agent="claimreview-matcher", seq=3),
            _obs("CLAIMREVIEW_VERDICT", "TRUE^True^POLITIFACT",
                 agent="claimreview-matcher", seq=4),
            _obs("CLAIMREVIEW_MATCH_SCORE", "0.95", agent="claimreview-matcher",
                 seq=5, value_type="NM"),
            _obs("CROSS_SPECTRUM_CORROBORATION", "TRUE^Corroborated^FCK",
                 agent="blindspot-detector", seq=6),
            _obs("COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK",
                 agent="coverage-left", seq=7),
            _obs("COVERAGE_FRAMING", "NEUTRAL^Neutral^FCK",
                 agent="coverage-center", seq=8),
            _obs("COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK",
                 agent="coverage-right", seq=9),
            _obs("SOURCE_CONVERGENCE_SCORE", "0.85", agent="source-validator",
                 seq=10, value_type="NM"),
            _obs("BLINDSPOT_SCORE", "0.1", agent="blindspot-detector",
                 seq=11, value_type="NM"),
        ],
        synthesis_signal_count=11,
    )


def _low_confidence_resolved_set() -> ResolvedObservationSet:
    """Evidence set that produces a low confidence (FALSE/PANTS_FIRE) verdict."""
    return ResolvedObservationSet(
        observations=[
            _obs("DOMAIN_EVIDENCE_ALIGNMENT", "CONTRADICTS^Contradicts^FCK",
                 agent="domain-evidence", seq=1),
            _obs("DOMAIN_CONFIDENCE", "0.9", agent="domain-evidence", seq=2,
                 value_type="NM"),
            _obs("CLAIMREVIEW_MATCH", "TRUE^Match Found^FCK",
                 agent="claimreview-matcher", seq=3),
            _obs("CLAIMREVIEW_VERDICT", "FALSE^False^POLITIFACT",
                 agent="claimreview-matcher", seq=4),
            _obs("CLAIMREVIEW_MATCH_SCORE", "0.92", agent="claimreview-matcher",
                 seq=5, value_type="NM"),
            _obs("CROSS_SPECTRUM_CORROBORATION", "FALSE^Not Corroborated^FCK",
                 agent="blindspot-detector", seq=6),
            _obs("COVERAGE_FRAMING", "CRITICAL^Critical^FCK",
                 agent="coverage-left", seq=7),
            _obs("COVERAGE_FRAMING", "CRITICAL^Critical^FCK",
                 agent="coverage-center", seq=8),
            _obs("COVERAGE_FRAMING", "CRITICAL^Critical^FCK",
                 agent="coverage-right", seq=9),
            _obs("SOURCE_CONVERGENCE_SCORE", "0.1", agent="source-validator",
                 seq=10, value_type="NM"),
            _obs("BLINDSPOT_SCORE", "0.8", agent="blindspot-detector",
                 seq=11, value_type="NM"),
        ],
        synthesis_signal_count=11,
    )


def _unverifiable_resolved_set() -> ResolvedObservationSet:
    """Evidence set with insufficient signals for scoring."""
    return ResolvedObservationSet(
        observations=[
            _obs("CLAIM_TEXT", "Some claim", agent="ingestion-agent", seq=1),
            _obs("ENTITY_PERSON", "John Doe", agent="entity-extractor", seq=2),
        ],
        synthesis_signal_count=2,
    )


def _collect_obs(ctx: AgentContext) -> list[ObsMessage]:
    """Extract all ObsMessage instances from stream publish calls."""
    return [
        call[0][1]
        for call in ctx.stream.publish.call_args_list
        if isinstance(call[0][1], ObsMessage)
    ]


def _obs_by_code(observations: list[ObsMessage], code: ObservationCode) -> list[ObsMessage]:
    return [o for o in observations if o.observation.code == code]


# ---------------------------------------------------------------------------
# FakeStream for resolver
# ---------------------------------------------------------------------------


class FakeStream:
    def __init__(self):
        self.streams: dict[str, list] = {}

    def add_obs(
        self, run_id: str, agent: str, seq: int,
        code: str, value: str, value_type: str, status: str = "F", **kwargs,
    ):
        key = f"reasoning:{run_id}:{agent}"
        if key not in self.streams:
            self.streams[key] = []
        obs = Observation(
            runId=run_id, agent=agent, seq=seq,
            code=ObservationCode(code), value=value,
            valueType=ValueType(value_type), status=status,
            timestamp="2026-01-01T00:00:00Z",
            units=kwargs.get("units"), referenceRange=kwargs.get("reference_range"),
            method=kwargs.get("method"), note=kwargs.get("note"),
        )
        self.streams[key].append(ObsMessage(observation=obs))

    async def read_range(self, stream_key: str, start: str = "-", end: str = "+"):
        return self.streams.get(stream_key, [])

    async def publish(self, key: str, msg):
        pass

    async def close(self):
        pass


# ===================================================================
# Tool pipeline integration tests
# ===================================================================


class TestToolPipelineHighConfidence:
    """End-to-end: resolve → score → map → narrate with high-confidence data."""

    @pytest.mark.asyncio
    async def test_full_pipeline_high_confidence(self, monkeypatch):
        """Full tool chain produces TRUE verdict for all-positive evidence."""
        # Mock the LLM to force fallback narrative
        async def mock_llm(*args, **kwargs):
            raise RuntimeError("no API key")
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.narrator.NarrativeGenerator._llm_generate",
            mock_llm,
        )

        ctx = _make_context()
        resolved = _full_resolved_set()

        # Mock resolver to return our data
        async def mock_resolve(self, run_id, stream):
            return resolved
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.tools.resolve.ObservationResolver.resolve",
            mock_resolve,
        )

        # Step 1: resolve
        resolved_json = await resolve_observations.ainvoke(
            {"run_id": "test-run-int", "context": ctx}
        )
        data = json.loads(resolved_json)
        assert data["synthesis_signal_count"] == 11

        # Step 2: score
        score_json = await compute_confidence.ainvoke(
            {"resolved_json": resolved_json, "context": ctx}
        )
        score_data = json.loads(score_json)
        assert score_data["score"] is not None
        assert score_data["score"] > 0.7  # Should be high

        # Step 3: map verdict
        verdict_json = await map_verdict.ainvoke({
            "confidence_score": score_data["score"],
            "resolved_json": resolved_json,
            "context": ctx,
        })
        verdict_data = json.loads(verdict_json)
        assert verdict_data["verdict_code"] in ("TRUE", "MOSTLY_TRUE")
        assert "POLITIFACT" in verdict_data["verdict_cwe"]

        # Step 4: narrate
        narrative = await generate_narrative.ainvoke({
            "resolved_json": resolved_json,
            "verdict_code": verdict_data["verdict_code"],
            "confidence_score": score_data["score"],
            "override_reason": verdict_data["override_reason"],
            "signal_count": data["synthesis_signal_count"],
            "warnings_json": json.dumps(data["warnings"]),
            "context": ctx,
        })

        assert isinstance(narrative, str)
        assert 200 <= len(narrative) <= 1000
        assert verdict_data["verdict_code"] in narrative

        # Verify observation publishing
        obs = _collect_obs(ctx)
        codes = [o.observation.code for o in obs]
        assert ObservationCode.SYNTHESIS_SIGNAL_COUNT in codes
        assert ObservationCode.CONFIDENCE_SCORE in codes
        assert ObservationCode.VERDICT in codes
        assert ObservationCode.SYNTHESIS_OVERRIDE_REASON in codes
        assert ObservationCode.VERDICT_NARRATIVE in codes

    @pytest.mark.asyncio
    async def test_seq_counter_increments_through_pipeline(self, monkeypatch):
        """AgentContext.seq_counter advances correctly across all tools."""
        async def mock_llm(*args, **kwargs):
            raise RuntimeError("no API key")
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.narrator.NarrativeGenerator._llm_generate",
            mock_llm,
        )

        ctx = _make_context()
        resolved = _full_resolved_set()

        async def mock_resolve(self, run_id, stream):
            return resolved
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.tools.resolve.ObservationResolver.resolve",
            mock_resolve,
        )

        resolved_json = await resolve_observations.ainvoke(
            {"run_id": "test-run-int", "context": ctx}
        )
        assert ctx.seq_counter == 1  # SYNTHESIS_SIGNAL_COUNT

        score_json = await compute_confidence.ainvoke(
            {"resolved_json": resolved_json, "context": ctx}
        )
        assert ctx.seq_counter == 2  # + CONFIDENCE_SCORE

        await map_verdict.ainvoke({
            "confidence_score": json.loads(score_json)["score"],
            "resolved_json": resolved_json,
            "context": ctx,
        })
        assert ctx.seq_counter == 4  # + VERDICT + OVERRIDE_REASON

        await generate_narrative.ainvoke({
            "resolved_json": resolved_json,
            "verdict_code": "TRUE",
            "confidence_score": 0.95,
            "override_reason": "",
            "signal_count": 11,
            "warnings_json": "[]",
            "context": ctx,
        })
        assert ctx.seq_counter == 5  # + VERDICT_NARRATIVE


class TestToolPipelineLowConfidence:
    """End-to-end with all-negative evidence → FALSE/PANTS_FIRE."""

    @pytest.mark.asyncio
    async def test_full_pipeline_low_confidence(self, monkeypatch):
        async def mock_llm(*args, **kwargs):
            raise RuntimeError("no API key")
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.narrator.NarrativeGenerator._llm_generate",
            mock_llm,
        )

        ctx = _make_context()
        resolved = _low_confidence_resolved_set()

        async def mock_resolve(self, run_id, stream):
            return resolved
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.tools.resolve.ObservationResolver.resolve",
            mock_resolve,
        )

        resolved_json = await resolve_observations.ainvoke(
            {"run_id": "test-run-int", "context": ctx}
        )

        score_json = await compute_confidence.ainvoke(
            {"resolved_json": resolved_json, "context": ctx}
        )
        score = json.loads(score_json)["score"]
        assert score is not None
        assert score < 0.3

        verdict_json = await map_verdict.ainvoke({
            "confidence_score": score,
            "resolved_json": resolved_json,
            "context": ctx,
        })
        verdict_data = json.loads(verdict_json)
        # ClaimReview says FALSE with high match score, and swarm score is low
        # so either the swarm verdict or the override should be FALSE
        assert verdict_data["verdict_code"] in ("FALSE", "PANTS_FIRE", "MOSTLY_FALSE")

        narrative = await generate_narrative.ainvoke({
            "resolved_json": resolved_json,
            "verdict_code": verdict_data["verdict_code"],
            "confidence_score": score,
            "override_reason": verdict_data["override_reason"],
            "signal_count": 11,
            "warnings_json": "[]",
            "context": ctx,
        })
        assert 200 <= len(narrative) <= 1000


class TestToolPipelineUnverifiable:
    """End-to-end with insufficient signals → UNVERIFIABLE."""

    @pytest.mark.asyncio
    async def test_full_pipeline_unverifiable(self, monkeypatch):
        async def mock_llm(*args, **kwargs):
            raise RuntimeError("no API key")
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.narrator.NarrativeGenerator._llm_generate",
            mock_llm,
        )

        ctx = _make_context()
        resolved = _unverifiable_resolved_set()

        async def mock_resolve(self, run_id, stream):
            return resolved
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.tools.resolve.ObservationResolver.resolve",
            mock_resolve,
        )

        resolved_json = await resolve_observations.ainvoke(
            {"run_id": "test-run-int", "context": ctx}
        )

        score_json = await compute_confidence.ainvoke(
            {"resolved_json": resolved_json, "context": ctx}
        )
        score = json.loads(score_json)["score"]
        assert score is None

        verdict_json = await map_verdict.ainvoke({
            "confidence_score": score,
            "resolved_json": resolved_json,
            "context": ctx,
        })
        verdict_data = json.loads(verdict_json)
        assert verdict_data["verdict_code"] == "UNVERIFIABLE"
        assert "Unverifiable" in verdict_data["verdict_cwe"]

        narrative = await generate_narrative.ainvoke({
            "resolved_json": resolved_json,
            "verdict_code": "UNVERIFIABLE",
            "confidence_score": None,
            "override_reason": "",
            "signal_count": 2,
            "warnings_json": "[]",
            "context": ctx,
        })
        assert "UNVERIFIABLE" in narrative
        assert 200 <= len(narrative) <= 1000

    @pytest.mark.asyncio
    async def test_no_confidence_observation_when_unverifiable(self, monkeypatch):
        """CONFIDENCE_SCORE observation is NOT published when score is None."""
        ctx = _make_context()
        resolved = _unverifiable_resolved_set()

        async def mock_resolve(self, run_id, stream):
            return resolved
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.tools.resolve.ObservationResolver.resolve",
            mock_resolve,
        )

        resolved_json = await resolve_observations.ainvoke(
            {"run_id": "test-run-int", "context": ctx}
        )
        # seq_counter = 1 (SYNTHESIS_SIGNAL_COUNT only)

        await compute_confidence.ainvoke(
            {"resolved_json": resolved_json, "context": ctx}
        )
        # No CONFIDENCE_SCORE published
        assert ctx.seq_counter == 1

        obs = _collect_obs(ctx)
        conf_obs = _obs_by_code(obs, ObservationCode.CONFIDENCE_SCORE)
        assert len(conf_obs) == 0


class TestToolPipelineOverride:
    """End-to-end with ClaimReview override triggering."""

    @pytest.mark.asyncio
    async def test_pipeline_with_override(self, monkeypatch):
        """High swarm score overridden by ClaimReview FALSE verdict."""
        async def mock_llm(*args, **kwargs):
            raise RuntimeError("no API key")
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.narrator.NarrativeGenerator._llm_generate",
            mock_llm,
        )

        ctx = _make_context()
        # Build evidence with high domain support but ClaimReview says FALSE
        resolved = ResolvedObservationSet(
            observations=[
                _obs("DOMAIN_EVIDENCE_ALIGNMENT", "SUPPORTS^Supports^FCK",
                     agent="domain-evidence", seq=1),
                _obs("DOMAIN_CONFIDENCE", "1.0", agent="domain-evidence",
                     seq=2, value_type="NM"),
                _obs("CLAIMREVIEW_MATCH", "TRUE^Match Found^FCK",
                     agent="claimreview-matcher", seq=3),
                _obs("CLAIMREVIEW_VERDICT", "FALSE^False^POLITIFACT",
                     agent="claimreview-matcher", seq=4),
                _obs("CLAIMREVIEW_MATCH_SCORE", "0.98", agent="claimreview-matcher",
                     seq=5, value_type="NM"),
                ResolvedObservation(
                    agent="claimreview-matcher", code="CLAIMREVIEW_SOURCE",
                    value="PolitiFact", value_type="ST", seq=6, status="F",
                    resolution_method="LATEST_F", timestamp="2026-01-01T00:00:00Z",
                ),
                _obs("CROSS_SPECTRUM_CORROBORATION", "TRUE^Corroborated^FCK",
                     agent="blindspot-detector", seq=7),
                _obs("COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK",
                     agent="coverage-left", seq=8),
                _obs("COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK",
                     agent="coverage-center", seq=9),
                _obs("COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK",
                     agent="coverage-right", seq=10),
                _obs("SOURCE_CONVERGENCE_SCORE", "0.9", agent="source-validator",
                     seq=11, value_type="NM"),
                _obs("BLINDSPOT_SCORE", "0.0", agent="blindspot-detector",
                     seq=12, value_type="NM"),
            ],
            synthesis_signal_count=12,
        )

        async def mock_resolve(self, run_id, stream):
            return resolved
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.tools.resolve.ObservationResolver.resolve",
            mock_resolve,
        )

        resolved_json = await resolve_observations.ainvoke(
            {"run_id": "test-run-int", "context": ctx}
        )

        score_json = await compute_confidence.ainvoke(
            {"resolved_json": resolved_json, "context": ctx}
        )
        score = json.loads(score_json)["score"]
        # High swarm score because domain + coverage + convergence are all positive
        assert score is not None
        assert score > 0.6

        verdict_json = await map_verdict.ainvoke({
            "confidence_score": score,
            "resolved_json": resolved_json,
            "context": ctx,
        })
        verdict_data = json.loads(verdict_json)
        # ClaimReview override should fire: match=TRUE, score=0.98, cr_verdict=FALSE
        assert verdict_data["verdict_code"] == "FALSE"
        assert "ClaimReview override" in verdict_data["override_reason"]
        assert "PolitiFact" in verdict_data["override_reason"]

        # Check SYNTHESIS_OVERRIDE_REASON observation has content
        obs = _collect_obs(ctx)
        override_obs = _obs_by_code(obs, ObservationCode.SYNTHESIS_OVERRIDE_REASON)
        assert len(override_obs) == 1
        assert override_obs[0].observation.value != ""


class TestToolPipelineWithWarnings:
    """Pipeline with P-status warnings flowing through all tools."""

    @pytest.mark.asyncio
    async def test_warnings_preserved_through_pipeline(self, monkeypatch):
        async def mock_llm(*args, **kwargs):
            raise RuntimeError("no API key")
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.narrator.NarrativeGenerator._llm_generate",
            mock_llm,
        )

        ctx = _make_context()
        resolved = _full_resolved_set()
        resolved.warnings = [
            "WARNING: coverage-right:COVERAGE_FRAMING has only P-status observations"
        ]

        async def mock_resolve(self, run_id, stream):
            return resolved
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.tools.resolve.ObservationResolver.resolve",
            mock_resolve,
        )

        resolved_json = await resolve_observations.ainvoke(
            {"run_id": "test-run-int", "context": ctx}
        )
        data = json.loads(resolved_json)
        assert len(data["warnings"]) == 1

        score_json = await compute_confidence.ainvoke(
            {"resolved_json": resolved_json, "context": ctx}
        )

        verdict_json = await map_verdict.ainvoke({
            "confidence_score": json.loads(score_json)["score"],
            "resolved_json": resolved_json,
            "context": ctx,
        })
        verdict_data = json.loads(verdict_json)

        narrative = await generate_narrative.ainvoke({
            "resolved_json": resolved_json,
            "verdict_code": verdict_data["verdict_code"],
            "confidence_score": json.loads(score_json)["score"],
            "override_reason": verdict_data["override_reason"],
            "signal_count": data["synthesis_signal_count"],
            "warnings_json": json.dumps(data["warnings"]),
            "context": ctx,
        })

        # Fallback narrative should mention incomplete signals
        assert "incomplete" in narrative.lower()


# ===================================================================
# Serialization round-trip integration
# ===================================================================


class TestSerializationIntegrity:
    """Verify data survives the resolve → score → map JSON boundary."""

    def test_optional_fields_preserved(self):
        """method, note, units, reference_range survive serialization."""
        resolved = ResolvedObservationSet(
            observations=[
                ResolvedObservation(
                    agent="domain-evidence", code="DOMAIN_EVIDENCE_ALIGNMENT",
                    value="SUPPORTS^Supports^FCK", value_type="CWE", seq=1,
                    status="F", resolution_method="LATEST_F",
                    timestamp="2026-01-01T00:00:00Z",
                    method="api_lookup", note="Strong evidence found",
                    units=None, reference_range=None,
                ),
            ],
            synthesis_signal_count=1,
            warnings=["some warning"],
        )

        serialized = _serialize_resolved(resolved)
        deserialized = _deserialize_resolved(serialized)

        assert deserialized.observations[0].method == "api_lookup"
        assert deserialized.observations[0].note == "Strong evidence found"
        assert deserialized.observations[0].units is None
        assert deserialized.warnings == ["some warning"]

    def test_large_observation_set_round_trips(self):
        """Many observations survive serialization intact."""
        observations = [
            ResolvedObservation(
                agent=f"agent-{i}", code=f"CODE_{i}", value=f"val_{i}",
                value_type="ST", seq=i, status="F",
                resolution_method="LATEST_F",
                timestamp="2026-01-01T00:00:00Z",
            )
            for i in range(100)
        ]
        resolved = ResolvedObservationSet(
            observations=observations,
            synthesis_signal_count=100,
        )

        serialized = _serialize_resolved(resolved)
        deserialized = _deserialize_resolved(serialized)

        assert len(deserialized.observations) == 100
        assert deserialized.synthesis_signal_count == 100

    def test_empty_set_round_trips(self):
        resolved = ResolvedObservationSet()
        serialized = _serialize_resolved(resolved)
        deserialized = _deserialize_resolved(serialized)

        assert len(deserialized.observations) == 0
        assert deserialized.synthesis_signal_count == 0
        assert deserialized.warnings == []


# ===================================================================
# Resolver → Scorer integration with FakeStream
# ===================================================================


class TestResolverScorerIntegration:
    """Resolver output feeds directly into scorer."""

    @pytest.mark.asyncio
    async def test_resolved_stream_feeds_scorer(self):
        """Data resolved from FakeStream produces a valid score."""
        from swarm_reasoning.agents.synthesizer.resolver import ObservationResolver
        from swarm_reasoning.agents.synthesizer.scorer import ConfidenceScorer

        stream = FakeStream()
        # Add all the observations a full run would produce
        stream.add_obs("run1", "domain-evidence", seq=1,
                       code="DOMAIN_EVIDENCE_ALIGNMENT",
                       value="SUPPORTS^Supports^FCK", value_type="CWE")
        stream.add_obs("run1", "domain-evidence", seq=2,
                       code="DOMAIN_CONFIDENCE",
                       value="0.85", value_type="NM")
        stream.add_obs("run1", "claimreview-matcher", seq=1,
                       code="CLAIMREVIEW_MATCH",
                       value="TRUE^Match Found^FCK", value_type="CWE")
        stream.add_obs("run1", "claimreview-matcher", seq=2,
                       code="CLAIMREVIEW_VERDICT",
                       value="MOSTLY_TRUE^Mostly True^POLITIFACT", value_type="CWE")
        stream.add_obs("run1", "claimreview-matcher", seq=3,
                       code="CLAIMREVIEW_MATCH_SCORE",
                       value="0.88", value_type="NM")
        stream.add_obs("run1", "blindspot-detector", seq=1,
                       code="CROSS_SPECTRUM_CORROBORATION",
                       value="TRUE^Corroborated^FCK", value_type="CWE")
        stream.add_obs("run1", "coverage-left", seq=1,
                       code="COVERAGE_FRAMING",
                       value="SUPPORTIVE^Supportive^FCK", value_type="CWE")
        stream.add_obs("run1", "coverage-center", seq=1,
                       code="COVERAGE_FRAMING",
                       value="NEUTRAL^Neutral^FCK", value_type="CWE")
        stream.add_obs("run1", "coverage-right", seq=1,
                       code="COVERAGE_FRAMING",
                       value="CRITICAL^Critical^FCK", value_type="CWE")
        stream.add_obs("run1", "source-validator", seq=1,
                       code="SOURCE_CONVERGENCE_SCORE",
                       value="0.65", value_type="NM")
        stream.add_obs("run1", "blindspot-detector", seq=2,
                       code="BLINDSPOT_SCORE",
                       value="0.15", value_type="NM")

        resolver = ObservationResolver()
        resolved = await resolver.resolve("run1", stream)

        assert resolved.synthesis_signal_count == 11

        scorer = ConfidenceScorer()
        score = scorer.compute(resolved)
        assert score is not None
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_sparse_stream_below_threshold(self):
        """Stream with only 3 observations → signal_count < 5 → None score."""
        from swarm_reasoning.agents.synthesizer.resolver import ObservationResolver
        from swarm_reasoning.agents.synthesizer.scorer import ConfidenceScorer

        stream = FakeStream()
        stream.add_obs("run1", "domain-evidence", seq=1,
                       code="DOMAIN_EVIDENCE_ALIGNMENT",
                       value="SUPPORTS^Supports^FCK", value_type="CWE")
        stream.add_obs("run1", "claimreview-matcher", seq=1,
                       code="CLAIMREVIEW_MATCH",
                       value="FALSE^No Match^FCK", value_type="CWE")
        stream.add_obs("run1", "blindspot-detector", seq=1,
                       code="BLINDSPOT_SCORE",
                       value="0.5", value_type="NM")

        resolver = ObservationResolver()
        resolved = await resolver.resolve("run1", stream)
        assert resolved.synthesis_signal_count == 3

        scorer = ConfidenceScorer()
        assert scorer.compute(resolved) is None


# ===================================================================
# Handler integration (mock Redis + stream)
# ===================================================================


class TestSynthesizerHandlerIntegration:
    """Full handler.run() with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_handler_produces_output(self, monkeypatch):
        """SynthesizerHandler.run() produces an AgentActivityOutput."""
        resolved = _full_resolved_set()

        async def mock_resolve(self, run_id, stream):
            return resolved
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.tools.resolve.ObservationResolver.resolve",
            mock_resolve,
        )

        async def mock_llm(*args, **kwargs):
            raise RuntimeError("no API key")
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.narrator.NarrativeGenerator._llm_generate",
            mock_llm,
        )

        stream_mock = MagicMock()
        stream_mock.publish = AsyncMock()
        stream_mock.read_range = AsyncMock(return_value=[])
        stream_mock.close = AsyncMock()

        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        with (
            patch(
                "swarm_reasoning.agents.synthesizer.handler.RedisReasoningStream",
                return_value=stream_mock,
            ),
            patch(
                "swarm_reasoning.agents.synthesizer.handler.aioredis.Redis",
                return_value=redis_mock,
            ),
            patch("swarm_reasoning.agents.synthesizer.handler.activity"),
        ):
            handler = SynthesizerHandler()
            inp = MagicMock()
            inp.run_id = "run-synth-001"
            inp.agent_name = "synthesizer"

            result = await handler.run(inp)

        assert result.agent_name == "synthesizer"
        assert result.terminal_status == "F"
        assert result.observation_count == 5  # signal_count + score + verdict + override + narrative
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_handler_publishes_start_and_stop(self, monkeypatch):
        """Handler publishes START and STOP messages bracketing observations."""
        resolved = _full_resolved_set()

        async def mock_resolve(self, run_id, stream):
            return resolved
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.tools.resolve.ObservationResolver.resolve",
            mock_resolve,
        )

        async def mock_llm(*args, **kwargs):
            raise RuntimeError("no API key")
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.narrator.NarrativeGenerator._llm_generate",
            mock_llm,
        )

        stream_mock = MagicMock()
        stream_mock.publish = AsyncMock()
        stream_mock.read_range = AsyncMock(return_value=[])
        stream_mock.close = AsyncMock()

        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        with (
            patch(
                "swarm_reasoning.agents.synthesizer.handler.RedisReasoningStream",
                return_value=stream_mock,
            ),
            patch(
                "swarm_reasoning.agents.synthesizer.handler.aioredis.Redis",
                return_value=redis_mock,
            ),
            patch("swarm_reasoning.agents.synthesizer.handler.activity"),
        ):
            handler = SynthesizerHandler()
            inp = MagicMock()
            inp.run_id = "run-synth-002"
            inp.agent_name = "synthesizer"

            await handler.run(inp)

        all_msgs = [call[0][1] for call in stream_mock.publish.call_args_list]

        # First message should be START
        assert isinstance(all_msgs[0], StartMessage)
        assert all_msgs[0].agent == "synthesizer"
        assert all_msgs[0].phase == Phase.SYNTHESIS

        # Last message should be STOP
        assert isinstance(all_msgs[-1], StopMessage)
        assert all_msgs[-1].agent == "synthesizer"
        assert all_msgs[-1].final_status == "F"
        assert all_msgs[-1].observation_count == 5

    @pytest.mark.asyncio
    async def test_handler_publishes_progress_events(self, monkeypatch):
        """Handler publishes progress events to progress:{runId}."""
        resolved = _full_resolved_set()

        async def mock_resolve(self, run_id, stream):
            return resolved
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.tools.resolve.ObservationResolver.resolve",
            mock_resolve,
        )

        async def mock_llm(*args, **kwargs):
            raise RuntimeError("no API key")
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.narrator.NarrativeGenerator._llm_generate",
            mock_llm,
        )

        stream_mock = MagicMock()
        stream_mock.publish = AsyncMock()
        stream_mock.read_range = AsyncMock(return_value=[])
        stream_mock.close = AsyncMock()

        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        with (
            patch(
                "swarm_reasoning.agents.synthesizer.handler.RedisReasoningStream",
                return_value=stream_mock,
            ),
            patch(
                "swarm_reasoning.agents.synthesizer.handler.aioredis.Redis",
                return_value=redis_mock,
            ),
            patch("swarm_reasoning.agents.synthesizer.handler.activity"),
        ):
            handler = SynthesizerHandler()
            inp = MagicMock()
            inp.run_id = "run-synth-003"
            inp.agent_name = "synthesizer"

            await handler.run(inp)

        # Check progress events via redis xadd
        xadd_calls = redis_mock.xadd.call_args_list
        progress_keys = [call[0][0] for call in xadd_calls]
        assert all(k == "progress:run-synth-003" for k in progress_keys)

        progress_messages = [call[0][1]["message"] for call in xadd_calls]
        assert "Resolving observations..." in progress_messages
        assert "Computing confidence..." in progress_messages
        assert "Mapping verdict..." in progress_messages
        assert "Generating narrative..." in progress_messages
        # Final progress: "Verdict: TRUE" or similar
        assert any(msg.startswith("Verdict:") for msg in progress_messages)

    @pytest.mark.asyncio
    async def test_handler_cleans_up_connections(self, monkeypatch):
        """Handler closes stream and Redis connections even on success."""
        resolved = _full_resolved_set()

        async def mock_resolve(self, run_id, stream):
            return resolved
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.tools.resolve.ObservationResolver.resolve",
            mock_resolve,
        )

        async def mock_llm(*args, **kwargs):
            raise RuntimeError("no API key")
        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.narrator.NarrativeGenerator._llm_generate",
            mock_llm,
        )

        stream_mock = MagicMock()
        stream_mock.publish = AsyncMock()
        stream_mock.read_range = AsyncMock(return_value=[])
        stream_mock.close = AsyncMock()

        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        with (
            patch(
                "swarm_reasoning.agents.synthesizer.handler.RedisReasoningStream",
                return_value=stream_mock,
            ),
            patch(
                "swarm_reasoning.agents.synthesizer.handler.aioredis.Redis",
                return_value=redis_mock,
            ),
            patch("swarm_reasoning.agents.synthesizer.handler.activity"),
        ):
            handler = SynthesizerHandler()
            inp = MagicMock()
            inp.run_id = "run-synth-004"
            inp.agent_name = "synthesizer"

            await handler.run(inp)

        stream_mock.close.assert_awaited_once()
        redis_mock.aclose.assert_awaited_once()
