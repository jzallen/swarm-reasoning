"""Tests for synthesizer pipeline node (M5.1).

Verifies:
- Observation resolution from PipelineState (epistemic status precedence)
- Not-check-worthy bypass path
- Full synthesis path (resolve → score → map → narrate)
- Observation publishing via PipelineContext
- Verdict observation output structure
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.synthesizer.models import ResolvedObservation, ResolvedObservationSet
from swarm_reasoning.agents.synthesizer.narrator import NarrativeGenerator
from swarm_reasoning.agents.synthesizer.resolver import resolve_from_state
from swarm_reasoning.pipeline.nodes.synthesizer import (
    AGENT_NAME,
    synthesizer_node,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class FakePipelineContext:
    """Minimal PipelineContext double for unit tests."""

    run_id: str = "run-test"
    session_id: str = "sess-test"
    published_observations: list = field(default_factory=list)
    published_progress: list = field(default_factory=list)

    async def publish_observation(self, *, agent, code, value, value_type, **kwargs):
        self.published_observations.append({
            "agent": agent,
            "code": code,
            "value": value,
            "value_type": value_type,
            **kwargs,
        })

    async def publish_progress(self, agent, message):
        self.published_progress.append({"agent": agent, "message": message})

    def heartbeat(self, node_name):
        pass


def _make_config(ctx=None):
    if ctx is None:
        ctx = FakePipelineContext()
    return {"configurable": {"pipeline_context": ctx}}


def _make_obs(agent, code, value, value_type="ST", seq=1, status="F", **kwargs):
    """Helper to build an observation dict matching PipelineState format."""
    return {
        "agent": agent,
        "code": code,
        "value": value,
        "value_type": value_type,
        "seq": seq,
        "status": status,
        "timestamp": "2026-01-01T00:00:00Z",
        **kwargs,
    }


# ---------------------------------------------------------------------------
# resolve_from_state tests
# ---------------------------------------------------------------------------


class TestResolveFromState:
    """Test the observation resolution algorithm on PipelineState data."""

    def test_empty_observations(self):
        resolved = resolve_from_state([])
        assert resolved.synthesis_signal_count == 0
        assert resolved.observations == []
        assert resolved.warnings == []

    def test_single_final_observation(self):
        obs = [_make_obs("evidence", "DOMAIN_EVIDENCE_ALIGNMENT", "SUPPORTS^Supports^FCK", "CWE")]
        resolved = resolve_from_state(obs)
        assert resolved.synthesis_signal_count == 1
        assert resolved.observations[0].agent == "evidence"
        assert resolved.observations[0].code == "DOMAIN_EVIDENCE_ALIGNMENT"
        assert resolved.observations[0].resolution_method == "LATEST_F"

    def test_corrected_takes_precedence_over_final(self):
        obs = [
            _make_obs("evidence", "DOMAIN_CONFIDENCE", "0.7", "NM", seq=1, status="F"),
            _make_obs("evidence", "DOMAIN_CONFIDENCE", "0.9", "NM", seq=2, status="C"),
        ]
        resolved = resolve_from_state(obs)
        assert resolved.synthesis_signal_count == 1
        winner = resolved.observations[0]
        assert winner.value == "0.9"
        assert winner.resolution_method == "LATEST_C"

    def test_highest_seq_corrected_wins(self):
        obs = [
            _make_obs("evidence", "DOMAIN_CONFIDENCE", "0.5", "NM", seq=1, status="C"),
            _make_obs("evidence", "DOMAIN_CONFIDENCE", "0.8", "NM", seq=3, status="C"),
            _make_obs("evidence", "DOMAIN_CONFIDENCE", "0.6", "NM", seq=2, status="C"),
        ]
        resolved = resolve_from_state(obs)
        assert resolved.observations[0].value == "0.8"
        assert resolved.observations[0].seq == 3

    def test_cancelled_excluded_silently(self):
        obs = [
            _make_obs("evidence", "DOMAIN_CONFIDENCE", "0.5", "NM", seq=1, status="X"),
        ]
        resolved = resolve_from_state(obs)
        assert resolved.synthesis_signal_count == 0
        assert len(resolved.excluded_observations) == 1
        assert resolved.warnings == []

    def test_preliminary_excluded_with_warning(self):
        obs = [
            _make_obs("evidence", "DOMAIN_CONFIDENCE", "0.5", "NM", seq=1, status="P"),
        ]
        resolved = resolve_from_state(obs)
        assert resolved.synthesis_signal_count == 0
        assert len(resolved.excluded_observations) == 1
        assert len(resolved.warnings) == 1
        assert "P-status" in resolved.warnings[0]

    def test_multiple_agents_resolved_independently(self):
        obs = [
            _make_obs("evidence", "DOMAIN_CONFIDENCE", "0.8", "NM", seq=1, status="F"),
            _make_obs("coverage-left", "COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK", "CWE", seq=1, status="F"),
            _make_obs("coverage-center", "COVERAGE_FRAMING", "NEUTRAL^Neutral^FCK", "CWE", seq=1, status="F"),
        ]
        resolved = resolve_from_state(obs)
        assert resolved.synthesis_signal_count == 3
        agents = {o.agent for o in resolved.observations}
        assert agents == {"evidence", "coverage-left", "coverage-center"}

    def test_observations_without_agent_or_code_skipped(self):
        obs = [
            {"value": "orphan", "status": "F"},
            _make_obs("evidence", "DOMAIN_CONFIDENCE", "0.5", "NM"),
        ]
        resolved = resolve_from_state(obs)
        assert resolved.synthesis_signal_count == 1

    def test_enum_code_values_handled(self):
        """Observation codes may arrive as enum instances."""
        from swarm_reasoning.models.observation import ObservationCode, ValueType

        obs = [{
            "agent": "evidence",
            "code": ObservationCode.DOMAIN_CONFIDENCE,
            "value": "0.8",
            "value_type": ValueType.NM,
            "seq": 1,
            "status": "F",
            "timestamp": "2026-01-01T00:00:00Z",
        }]
        resolved = resolve_from_state(obs)
        assert resolved.synthesis_signal_count == 1
        assert resolved.observations[0].code == "DOMAIN_CONFIDENCE"


# ---------------------------------------------------------------------------
# Not-check-worthy bypass tests
# ---------------------------------------------------------------------------


class TestNotCheckWorthyBypass:
    """Test the not-check-worthy bypass path."""

    @pytest.mark.asyncio
    async def test_bypass_produces_not_check_worthy_verdict(self):
        ctx = FakePipelineContext()
        state = {
            "claim_text": "What time is it?",
            "run_id": "run-1",
            "session_id": "sess-1",
            "is_check_worthy": False,
            "check_worthy_score": 0.15,
            "observations": [],
            "errors": [],
        }
        result = await synthesizer_node(state, _make_config(ctx))
        assert result["verdict"] == "NOT_CHECK_WORTHY"
        assert result["confidence"] == 1.0
        assert result["verdict_observations"] == []
        assert "not check-worthy" in result["narrative"].lower()

    @pytest.mark.asyncio
    async def test_bypass_publishes_observations(self):
        ctx = FakePipelineContext()
        state = {
            "claim_text": "What time is it?",
            "run_id": "run-1",
            "session_id": "sess-1",
            "is_check_worthy": False,
            "observations": [],
            "errors": [],
        }
        await synthesizer_node(state, _make_config(ctx))

        codes = [o["code"].value if hasattr(o["code"], "value") else str(o["code"])
                 for o in ctx.published_observations]
        assert "ObservationCode.VERDICT" in codes or "VERDICT" in codes
        assert "ObservationCode.CONFIDENCE_SCORE" in codes or "CONFIDENCE_SCORE" in codes
        assert "ObservationCode.VERDICT_NARRATIVE" in codes or "VERDICT_NARRATIVE" in codes

    @pytest.mark.asyncio
    async def test_bypass_narrative_exceeds_200_chars(self):
        """TX value type requires >200 characters."""
        ctx = FakePipelineContext()
        state = {
            "claim_text": "opinion",
            "run_id": "run-1",
            "session_id": "sess-1",
            "is_check_worthy": False,
            "observations": [],
            "errors": [],
        }
        result = await synthesizer_node(state, _make_config(ctx))
        assert len(result["narrative"]) > 200


# ---------------------------------------------------------------------------
# Full synthesis path tests
# ---------------------------------------------------------------------------


def _build_full_state(observations=None) -> dict:
    """Build a PipelineState dict with check-worthy claim and upstream data."""
    return {
        "claim_text": "The Earth is flat",
        "run_id": "run-synth",
        "session_id": "sess-synth",
        "is_check_worthy": True,
        "check_worthy_score": 0.95,
        "normalized_claim": "The Earth is flat",
        "claim_domain": "science",
        "entities": {"persons": [], "orgs": []},
        "observations": observations or [],
        "errors": [],
    }


def _build_rich_observations() -> list[dict]:
    """Build a realistic set of upstream observations for synthesis testing."""
    return [
        _make_obs("evidence", "DOMAIN_EVIDENCE_ALIGNMENT", "CONTRADICTS^Contradicts^FCK", "CWE", seq=1),
        _make_obs("evidence", "DOMAIN_CONFIDENCE", "0.95", "NM", seq=2),
        _make_obs("evidence", "CLAIMREVIEW_MATCH", "TRUE^True^FCK", "CWE", seq=3),
        _make_obs("evidence", "CLAIMREVIEW_VERDICT", "FALSE^False^POLITIFACT", "CWE", seq=4),
        _make_obs("evidence", "CLAIMREVIEW_SOURCE", "PolitiFact", "ST", seq=5),
        _make_obs("evidence", "CLAIMREVIEW_MATCH_SCORE", "0.95", "NM", seq=6),
        _make_obs("coverage-left", "COVERAGE_FRAMING", "CRITICAL^Critical^FCK", "CWE", seq=1),
        _make_obs("coverage-center", "COVERAGE_FRAMING", "CRITICAL^Critical^FCK", "CWE", seq=1),
        _make_obs("coverage-right", "COVERAGE_FRAMING", "CRITICAL^Critical^FCK", "CWE", seq=1),
        _make_obs("validation", "SOURCE_CONVERGENCE_SCORE", "0.10", "NM", seq=1),
        _make_obs("validation", "BLINDSPOT_SCORE", "0.05", "NM", seq=2),
        _make_obs("validation", "CROSS_SPECTRUM_CORROBORATION", "TRUE^True^FCK", "CWE", seq=3),
    ]


class TestSynthesizerNode:
    """Test the full synthesizer_node function."""

    @pytest.mark.asyncio
    async def test_synthesis_with_rich_observations(self):
        """Full pipeline with rich upstream data produces a verdict."""
        ctx = FakePipelineContext()
        observations = _build_rich_observations()
        state = _build_full_state(observations)

        with patch.object(
            NarrativeGenerator,
            "generate",
            new_callable=AsyncMock,
            return_value="X" * 250,
        ):
            result = await synthesizer_node(state, _make_config(ctx))

        assert result["verdict"] is not None
        assert result["verdict"] != "UNVERIFIABLE"
        assert result["confidence"] is not None
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0
        assert result["narrative"] is not None
        assert isinstance(result["verdict_observations"], list)
        assert len(result["verdict_observations"]) > 0

    @pytest.mark.asyncio
    async def test_synthesis_with_no_observations_is_unverifiable(self):
        """Empty observations produce UNVERIFIABLE verdict."""
        ctx = FakePipelineContext()
        state = _build_full_state([])

        with patch.object(
            NarrativeGenerator,
            "generate",
            new_callable=AsyncMock,
            return_value="X" * 250,
        ):
            result = await synthesizer_node(state, _make_config(ctx))

        assert result["verdict"] == "UNVERIFIABLE"
        assert result["confidence"] is None

    @pytest.mark.asyncio
    async def test_synthesis_publishes_signal_count(self):
        """SYNTHESIS_SIGNAL_COUNT observation is always published."""
        ctx = FakePipelineContext()
        observations = _build_rich_observations()
        state = _build_full_state(observations)

        with patch.object(
            NarrativeGenerator,
            "generate",
            new_callable=AsyncMock,
            return_value="X" * 250,
        ):
            await synthesizer_node(state, _make_config(ctx))

        signal_count_obs = [
            o for o in ctx.published_observations
            if str(o["code"]) in ("SYNTHESIS_SIGNAL_COUNT", "ObservationCode.SYNTHESIS_SIGNAL_COUNT")
        ]
        assert len(signal_count_obs) >= 1

    @pytest.mark.asyncio
    async def test_synthesis_publishes_verdict(self):
        """VERDICT observation is published."""
        ctx = FakePipelineContext()
        observations = _build_rich_observations()
        state = _build_full_state(observations)

        with patch.object(
            NarrativeGenerator,
            "generate",
            new_callable=AsyncMock,
            return_value="X" * 250,
        ):
            await synthesizer_node(state, _make_config(ctx))

        verdict_obs = [
            o for o in ctx.published_observations
            if str(o["code"]) in ("VERDICT", "ObservationCode.VERDICT")
        ]
        assert len(verdict_obs) >= 1

    @pytest.mark.asyncio
    async def test_synthesis_publishes_progress(self):
        """Progress messages are published for SSE relay."""
        ctx = FakePipelineContext()
        state = _build_full_state([])

        with patch.object(
            NarrativeGenerator,
            "generate",
            new_callable=AsyncMock,
            return_value="X" * 250,
        ):
            await synthesizer_node(state, _make_config(ctx))

        assert len(ctx.published_progress) >= 2
        messages = [p["message"] for p in ctx.published_progress]
        assert any("Beginning" in m for m in messages)
        assert any("Verdict" in m for m in messages)

    @pytest.mark.asyncio
    async def test_default_is_check_worthy_when_missing(self):
        """When is_check_worthy is not in state, default to True (normal path)."""
        ctx = FakePipelineContext()
        state = {
            "claim_text": "test",
            "run_id": "r",
            "session_id": "s",
            "observations": [],
            "errors": [],
        }

        with patch.object(
            NarrativeGenerator,
            "generate",
            new_callable=AsyncMock,
            return_value="X" * 250,
        ):
            result = await synthesizer_node(state, _make_config(ctx))

        # Should NOT be bypass (verdict != NOT_CHECK_WORTHY)
        assert result["verdict"] != "NOT_CHECK_WORTHY"

    @pytest.mark.asyncio
    async def test_verdict_observations_contain_expected_codes(self):
        """Returned verdict_observations include key observation codes."""
        ctx = FakePipelineContext()
        observations = _build_rich_observations()
        state = _build_full_state(observations)

        with patch.object(
            NarrativeGenerator,
            "generate",
            new_callable=AsyncMock,
            return_value="X" * 250,
        ):
            result = await synthesizer_node(state, _make_config(ctx))

        codes = {o["code"] for o in result["verdict_observations"]}
        assert "SYNTHESIS_SIGNAL_COUNT" in codes
        assert "VERDICT" in codes
        assert "VERDICT_NARRATIVE" in codes


class TestSynthesizerConfidenceThresholds:
    """Test verdict mapping based on confidence score thresholds."""

    @pytest.mark.asyncio
    async def test_high_confidence_false_claim(self):
        """Rich contradicting evidence produces FALSE or PANTS_FIRE verdict."""
        ctx = FakePipelineContext()
        observations = _build_rich_observations()
        state = _build_full_state(observations)

        with patch.object(
            NarrativeGenerator,
            "generate",
            new_callable=AsyncMock,
            return_value="X" * 250,
        ):
            result = await synthesizer_node(state, _make_config(ctx))

        # With all evidence contradicting + ClaimReview=FALSE, expect FALSE verdict
        assert result["verdict"] in ("FALSE", "PANTS_FIRE", "MOSTLY_FALSE")

    @pytest.mark.asyncio
    async def test_fewer_than_5_signals_is_unverifiable(self):
        """Confidence scorer returns None when < 5 signals."""
        ctx = FakePipelineContext()
        observations = [
            _make_obs("evidence", "DOMAIN_EVIDENCE_ALIGNMENT", "SUPPORTS^Supports^FCK", "CWE"),
            _make_obs("evidence", "DOMAIN_CONFIDENCE", "0.9", "NM", seq=2),
        ]
        state = _build_full_state(observations)

        with patch.object(
            NarrativeGenerator,
            "generate",
            new_callable=AsyncMock,
            return_value="X" * 250,
        ):
            result = await synthesizer_node(state, _make_config(ctx))

        assert result["verdict"] == "UNVERIFIABLE"
        assert result["confidence"] is None
