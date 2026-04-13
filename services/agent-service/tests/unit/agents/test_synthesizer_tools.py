"""Unit tests for synthesizer @tool definitions.

Tests that each tool wrapper correctly:
1. Delegates to the underlying logic module
2. Publishes the expected observations via AgentContext
3. Returns the correct JSON output
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

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
from swarm_reasoning.models.stream import ObsMessage


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_resolved_set(
    signal_count: int = 10,
    observations: list[ResolvedObservation] | None = None,
    warnings: list[str] | None = None,
) -> ResolvedObservationSet:
    """Build a ResolvedObservationSet with sane defaults."""
    if observations is None:
        observations = [
            ResolvedObservation(
                agent="domain-evidence",
                code="DOMAIN_EVIDENCE_ALIGNMENT",
                value="SUPPORTS^Supports^FCK",
                value_type="CWE",
                seq=1,
                status="F",
                resolution_method="LATEST_F",
                timestamp="2026-04-13T12:00:00Z",
            ),
            ResolvedObservation(
                agent="claimreview-matcher",
                code="CLAIMREVIEW_MATCH",
                value="TRUE^Matched^FCK",
                value_type="CWE",
                seq=2,
                status="F",
                resolution_method="LATEST_F",
                timestamp="2026-04-13T12:00:01Z",
            ),
            ResolvedObservation(
                agent="claimreview-matcher",
                code="CLAIMREVIEW_VERDICT",
                value="TRUE^True^POLITIFACT",
                value_type="CWE",
                seq=3,
                status="F",
                resolution_method="LATEST_F",
                timestamp="2026-04-13T12:00:02Z",
            ),
            ResolvedObservation(
                agent="claimreview-matcher",
                code="CLAIMREVIEW_MATCH_SCORE",
                value="0.95",
                value_type="NM",
                seq=4,
                status="F",
                resolution_method="LATEST_F",
                timestamp="2026-04-13T12:00:03Z",
            ),
            ResolvedObservation(
                agent="blindspot-detector",
                code="CROSS_SPECTRUM_CORROBORATION",
                value="TRUE^Corroborated^FCK",
                value_type="CWE",
                seq=5,
                status="F",
                resolution_method="LATEST_F",
                timestamp="2026-04-13T12:00:04Z",
            ),
            ResolvedObservation(
                agent="coverage-left",
                code="COVERAGE_FRAMING",
                value="POS^Supportive^FCK",
                value_type="CWE",
                seq=6,
                status="F",
                resolution_method="LATEST_F",
                timestamp="2026-04-13T12:00:05Z",
            ),
            ResolvedObservation(
                agent="coverage-center",
                code="COVERAGE_FRAMING",
                value="NEU^Neutral^FCK",
                value_type="CWE",
                seq=7,
                status="F",
                resolution_method="LATEST_F",
                timestamp="2026-04-13T12:00:06Z",
            ),
            ResolvedObservation(
                agent="coverage-right",
                code="COVERAGE_FRAMING",
                value="POS^Supportive^FCK",
                value_type="CWE",
                seq=8,
                status="F",
                resolution_method="LATEST_F",
                timestamp="2026-04-13T12:00:07Z",
            ),
            ResolvedObservation(
                agent="source-validator",
                code="SOURCE_CONVERGENCE_SCORE",
                value="0.85",
                value_type="NM",
                seq=9,
                status="F",
                resolution_method="LATEST_F",
                timestamp="2026-04-13T12:00:08Z",
            ),
            ResolvedObservation(
                agent="blindspot-detector",
                code="BLINDSPOT_SCORE",
                value="0.2",
                value_type="NM",
                seq=10,
                status="F",
                resolution_method="LATEST_F",
                timestamp="2026-04-13T12:00:09Z",
            ),
        ]
    return ResolvedObservationSet(
        observations=observations,
        synthesis_signal_count=signal_count,
        warnings=warnings or [],
    )


def _make_context() -> AgentContext:
    """Create a mock AgentContext that records published observations."""
    stream = MagicMock()
    stream.publish = AsyncMock()
    redis_client = MagicMock()
    ctx = AgentContext(
        stream=stream,
        redis_client=redis_client,
        run_id="test-run-001",
        sk="reasoning:test-run-001:synthesizer",
        agent_name="synthesizer",
    )
    return ctx


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


class TestSerializationRoundTrip:
    def test_serialize_deserialize(self):
        original = _make_resolved_set()
        serialized = _serialize_resolved(original)
        deserialized = _deserialize_resolved(serialized)

        assert deserialized.synthesis_signal_count == original.synthesis_signal_count
        assert len(deserialized.observations) == len(original.observations)
        for orig, deser in zip(original.observations, deserialized.observations):
            assert deser.agent == orig.agent
            assert deser.code == orig.code
            assert deser.value == orig.value
            assert deser.resolution_method == orig.resolution_method

    def test_serialize_empty_set(self):
        empty = ResolvedObservationSet()
        serialized = _serialize_resolved(empty)
        data = json.loads(serialized)
        assert data["synthesis_signal_count"] == 0
        assert data["observations"] == []
        assert data["warnings"] == []

    def test_deserialize_preserves_warnings(self):
        resolved = _make_resolved_set(warnings=["Missing DOMAIN_EVIDENCE_ALIGNMENT"])
        serialized = _serialize_resolved(resolved)
        deserialized = _deserialize_resolved(serialized)
        assert deserialized.warnings == ["Missing DOMAIN_EVIDENCE_ALIGNMENT"]


# ---------------------------------------------------------------------------
# resolve_observations tool
# ---------------------------------------------------------------------------


class TestResolveObservationsTool:
    @pytest.fixture
    def resolved_set(self):
        return _make_resolved_set()

    async def test_publishes_signal_count(self, resolved_set, monkeypatch):
        ctx = _make_context()

        async def mock_resolve(self, run_id, stream):
            return resolved_set

        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.tools.resolve.ObservationResolver.resolve",
            mock_resolve,
        )

        result = await resolve_observations.ainvoke(
            {"run_id": "test-run-001", "context": ctx}
        )

        # Verify SYNTHESIS_SIGNAL_COUNT was published
        assert ctx.seq_counter == 1
        call_args = ctx.stream.publish.call_args_list[0]
        msg = call_args[0][1]
        assert isinstance(msg, ObsMessage)
        assert msg.observation.code == ObservationCode.SYNTHESIS_SIGNAL_COUNT
        assert msg.observation.value == "10"
        assert msg.observation.value_type == ValueType.NM

    async def test_returns_json_with_observations(self, resolved_set, monkeypatch):
        ctx = _make_context()

        async def mock_resolve(self, run_id, stream):
            return resolved_set

        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.tools.resolve.ObservationResolver.resolve",
            mock_resolve,
        )

        result = await resolve_observations.ainvoke(
            {"run_id": "test-run-001", "context": ctx}
        )

        data = json.loads(result)
        assert data["synthesis_signal_count"] == 10
        assert len(data["observations"]) == 10


# ---------------------------------------------------------------------------
# compute_confidence tool
# ---------------------------------------------------------------------------


class TestComputeConfidenceTool:
    async def test_publishes_confidence_score(self):
        ctx = _make_context()
        resolved = _make_resolved_set()
        resolved_json = _serialize_resolved(resolved)

        result = await compute_confidence.ainvoke(
            {"resolved_json": resolved_json, "context": ctx}
        )

        data = json.loads(result)
        assert data["score"] is not None
        assert 0.0 <= data["score"] <= 1.0

        # Should have published CONFIDENCE_SCORE
        assert ctx.seq_counter == 1
        call_args = ctx.stream.publish.call_args_list[0]
        msg = call_args[0][1]
        assert msg.observation.code == ObservationCode.CONFIDENCE_SCORE

    async def test_returns_null_when_unverifiable(self):
        ctx = _make_context()
        resolved = _make_resolved_set(signal_count=3, observations=[
            ResolvedObservation(
                agent="domain-evidence", code="DOMAIN_EVIDENCE_ALIGNMENT",
                value="SUPPORTS", value_type="CWE", seq=1, status="F",
                resolution_method="LATEST_F", timestamp="2026-04-13T12:00:00Z",
            ),
        ])
        resolved_json = _serialize_resolved(resolved)

        result = await compute_confidence.ainvoke(
            {"resolved_json": resolved_json, "context": ctx}
        )

        data = json.loads(result)
        assert data["score"] is None
        # No observation published when unverifiable
        assert ctx.seq_counter == 0

    async def test_score_format_four_decimals(self):
        ctx = _make_context()
        resolved = _make_resolved_set()
        resolved_json = _serialize_resolved(resolved)

        await compute_confidence.ainvoke(
            {"resolved_json": resolved_json, "context": ctx}
        )

        call_args = ctx.stream.publish.call_args_list[0]
        msg = call_args[0][1]
        # Value should be formatted to 4 decimal places
        parts = msg.observation.value.split(".")
        assert len(parts) == 2
        assert len(parts[1]) == 4


# ---------------------------------------------------------------------------
# map_verdict tool
# ---------------------------------------------------------------------------


class TestMapVerdictTool:
    async def test_publishes_verdict_and_override(self):
        ctx = _make_context()
        resolved = _make_resolved_set()
        resolved_json = _serialize_resolved(resolved)

        result = await map_verdict.ainvoke(
            {
                "confidence_score": 0.95,
                "resolved_json": resolved_json,
                "context": ctx,
            }
        )

        data = json.loads(result)
        assert data["verdict_code"] == "TRUE"
        assert "POLITIFACT" in data["verdict_cwe"]

        # Should have published 2 observations: VERDICT + OVERRIDE_REASON
        assert ctx.seq_counter == 2
        codes = [
            ctx.stream.publish.call_args_list[i][0][1].observation.code
            for i in range(2)
        ]
        assert ObservationCode.VERDICT in codes
        assert ObservationCode.SYNTHESIS_OVERRIDE_REASON in codes

    async def test_unverifiable_when_score_is_none(self):
        ctx = _make_context()
        resolved = _make_resolved_set()
        resolved_json = _serialize_resolved(resolved)

        result = await map_verdict.ainvoke(
            {
                "confidence_score": None,
                "resolved_json": resolved_json,
                "context": ctx,
            }
        )

        data = json.loads(result)
        assert data["verdict_code"] == "UNVERIFIABLE"

    async def test_verdict_cwe_format(self):
        ctx = _make_context()
        resolved = _make_resolved_set()
        resolved_json = _serialize_resolved(resolved)

        result = await map_verdict.ainvoke(
            {
                "confidence_score": 0.55,
                "resolved_json": resolved_json,
                "context": ctx,
            }
        )

        data = json.loads(result)
        # CWE format: CODE^Display^System
        parts = data["verdict_cwe"].split("^")
        assert len(parts) == 3
        assert parts[2] == "POLITIFACT"


# ---------------------------------------------------------------------------
# generate_narrative tool
# ---------------------------------------------------------------------------


class TestGenerateNarrativeTool:
    async def test_publishes_narrative_observation(self, monkeypatch):
        ctx = _make_context()
        resolved = _make_resolved_set()
        resolved_json = _serialize_resolved(resolved)

        # Mock LLM to avoid real API call — force fallback narrative
        async def mock_llm_generate(self, *args, **kwargs):
            raise RuntimeError("no API key")

        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.narrator.NarrativeGenerator._llm_generate",
            mock_llm_generate,
        )

        result = await generate_narrative.ainvoke(
            {
                "resolved_json": resolved_json,
                "verdict_code": "TRUE",
                "confidence_score": 0.95,
                "override_reason": "",
                "signal_count": 10,
                "warnings_json": "[]",
                "context": ctx,
            }
        )

        # Should have published VERDICT_NARRATIVE
        assert ctx.seq_counter == 1
        call_args = ctx.stream.publish.call_args_list[0]
        msg = call_args[0][1]
        assert msg.observation.code == ObservationCode.VERDICT_NARRATIVE
        assert len(msg.observation.value) >= 200

    async def test_returns_narrative_string(self, monkeypatch):
        ctx = _make_context()
        resolved = _make_resolved_set()
        resolved_json = _serialize_resolved(resolved)

        async def mock_llm_generate(self, *args, **kwargs):
            raise RuntimeError("no API key")

        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.narrator.NarrativeGenerator._llm_generate",
            mock_llm_generate,
        )

        result = await generate_narrative.ainvoke(
            {
                "resolved_json": resolved_json,
                "verdict_code": "FALSE",
                "confidence_score": 0.15,
                "override_reason": "",
                "signal_count": 10,
                "warnings_json": "[]",
                "context": ctx,
            }
        )

        assert isinstance(result, str)
        assert "FALSE" in result
        assert len(result) >= 200
        assert len(result) <= 1000

    async def test_passes_warnings_to_generator(self, monkeypatch):
        ctx = _make_context()
        resolved = _make_resolved_set(warnings=["P-status only for ENTITY_PERSON"])
        resolved_json = _serialize_resolved(resolved)

        async def mock_llm_generate(self, *args, **kwargs):
            raise RuntimeError("no API key")

        monkeypatch.setattr(
            "swarm_reasoning.agents.synthesizer.narrator.NarrativeGenerator._llm_generate",
            mock_llm_generate,
        )

        result = await generate_narrative.ainvoke(
            {
                "resolved_json": resolved_json,
                "verdict_code": "HALF_TRUE",
                "confidence_score": 0.55,
                "override_reason": "",
                "signal_count": 10,
                "warnings_json": json.dumps(["P-status only for ENTITY_PERSON"]),
                "context": ctx,
            }
        )

        # Fallback narrative mentions incomplete signals when warnings present
        assert "incomplete" in result.lower() or "signal" in result.lower()
