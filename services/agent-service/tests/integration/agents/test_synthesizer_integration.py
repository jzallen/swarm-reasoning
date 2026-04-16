"""Integration tests for the synthesizer agent (sr-l0y.7.6).

Exercises run_synthesizer() end-to-end with a capturing FakePipelineContext.
Unlike unit tests that test individual nodes in isolation, these tests invoke
the complete synthesizer graph through its public entry point and verify:
  - Observation publishing sequence (SYNTHESIS_SIGNAL_COUNT, CONFIDENCE_SCORE,
    VERDICT, VERDICT_NARRATIVE published in correct order)
  - Progress event publishing (beginning + final verdict)
  - SynthesizerOutput contract (all fields, correct types)
  - ClaimReview override path through run_synthesizer
  - Heartbeat signaling
  - Multiple observation scenarios (rich, sparse, empty, override)

All external I/O (Anthropic API) is mocked. The synthesizer StateGraph
and observation resolution run for real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

from swarm_reasoning.agents.synthesizer.agent import AGENT_NAME, run_synthesizer
from swarm_reasoning.agents.synthesizer.models import SynthesizerInput
from swarm_reasoning.agents.synthesizer.narrator import NarrativeGenerator

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class CapturingPipelineContext:
    """PipelineContext double that captures all side-effects for assertions."""

    run_id: str = "integ-synth-run"
    session_id: str = "integ-synth-sess"
    published_observations: list = field(default_factory=list)
    published_progress: list = field(default_factory=list)
    heartbeat_calls: list = field(default_factory=list)

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
        self.heartbeat_calls.append(node_name)


@pytest.fixture
def ctx():
    return CapturingPipelineContext()


def _obs(agent, code, value, value_type="ST", seq=1, status="F", **kwargs):
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


def _rich_observations() -> list[dict]:
    """Full upstream observation set: evidence + coverage + validation."""
    return [
        _obs("evidence", "DOMAIN_EVIDENCE_ALIGNMENT", "CONTRADICTS^Contradicts^FCK", "CWE", seq=1),
        _obs("evidence", "DOMAIN_CONFIDENCE", "0.95", "NM", seq=2),
        _obs("evidence", "CLAIMREVIEW_MATCH", "TRUE^True^FCK", "CWE", seq=3),
        _obs("evidence", "CLAIMREVIEW_VERDICT", "FALSE^False^POLITIFACT", "CWE", seq=4),
        _obs("evidence", "CLAIMREVIEW_SOURCE", "PolitiFact", "ST", seq=5),
        _obs("evidence", "CLAIMREVIEW_MATCH_SCORE", "0.95", "NM", seq=6),
        _obs("coverage-left", "COVERAGE_FRAMING", "CRITICAL^Critical^FCK", "CWE", seq=1),
        _obs("coverage-center", "COVERAGE_FRAMING", "CRITICAL^Critical^FCK", "CWE", seq=1),
        _obs("coverage-right", "COVERAGE_FRAMING", "CRITICAL^Critical^FCK", "CWE", seq=1),
        _obs("validation", "SOURCE_CONVERGENCE_SCORE", "0.10", "NM", seq=1),
        _obs("validation", "BLINDSPOT_SCORE", "0.05", "NM", seq=2),
        _obs("validation", "CROSS_SPECTRUM_CORROBORATION", "TRUE^True^FCK", "CWE", seq=3),
    ]


def _supporting_observations() -> list[dict]:
    """Observations where evidence supports the claim (high-confidence TRUE path)."""
    return [
        _obs("evidence", "DOMAIN_EVIDENCE_ALIGNMENT", "SUPPORTS^Supports^FCK", "CWE", seq=1),
        _obs("evidence", "DOMAIN_CONFIDENCE", "0.95", "NM", seq=2),
        _obs("coverage-left", "COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK", "CWE", seq=1),
        _obs("coverage-center", "COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK", "CWE", seq=1),
        _obs("coverage-right", "COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK", "CWE", seq=1),
        _obs("validation", "SOURCE_CONVERGENCE_SCORE", "0.90", "NM", seq=1),
        _obs("validation", "BLINDSPOT_SCORE", "0.00", "NM", seq=2),
        _obs("validation", "CROSS_SPECTRUM_CORROBORATION", "TRUE^True^FCK", "CWE", seq=3),
    ]


def _override_observations() -> list[dict]:
    """Observations where swarm evidence is positive but ClaimReview says FALSE."""
    return [
        _obs("evidence", "DOMAIN_EVIDENCE_ALIGNMENT", "SUPPORTS^Supports^FCK", "CWE", seq=1),
        _obs("evidence", "DOMAIN_CONFIDENCE", "0.95", "NM", seq=2),
        _obs("evidence", "CLAIMREVIEW_MATCH", "TRUE^True^FCK", "CWE", seq=3),
        _obs("evidence", "CLAIMREVIEW_VERDICT", "FALSE^False^POLITIFACT", "CWE", seq=4),
        _obs("evidence", "CLAIMREVIEW_SOURCE", "PolitiFact", "ST", seq=5),
        _obs("evidence", "CLAIMREVIEW_MATCH_SCORE", "0.95", "NM", seq=6),
        _obs("coverage-left", "COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK", "CWE", seq=1),
        _obs("coverage-center", "COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK", "CWE", seq=1),
        _obs("coverage-right", "COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK", "CWE", seq=1),
        _obs("validation", "SOURCE_CONVERGENCE_SCORE", "0.90", "NM", seq=1),
        _obs("validation", "BLINDSPOT_SCORE", "0.00", "NM", seq=2),
        _obs("validation", "CROSS_SPECTRUM_CORROBORATION", "TRUE^True^FCK", "CWE", seq=3),
    ]


def _sparse_observations() -> list[dict]:
    """Minimal observation set: exactly at the 5-signal threshold."""
    return [
        _obs("evidence", "DOMAIN_EVIDENCE_ALIGNMENT", "SUPPORTS^Supports^FCK", "CWE", seq=1),
        _obs("evidence", "DOMAIN_CONFIDENCE", "0.80", "NM", seq=2),
        _obs("coverage-left", "COVERAGE_FRAMING", "NEUTRAL^Neutral^FCK", "CWE", seq=1),
        _obs("coverage-center", "COVERAGE_FRAMING", "NEUTRAL^Neutral^FCK", "CWE", seq=1),
        _obs("validation", "SOURCE_CONVERGENCE_SCORE", "0.50", "NM", seq=1),
    ]


def _mock_narrator():
    """Patch NarrativeGenerator.generate to avoid LLM calls."""
    return patch.object(
        NarrativeGenerator,
        "generate",
        new_callable=AsyncMock,
        return_value=(
            "Based on the available evidence from multiple verification agents, "
            "this claim has been evaluated against domain evidence, media coverage "
            "analysis, and source validation. The determination reflects the "
            "consensus of independent verification signals."
        ),
    )


# ---------------------------------------------------------------------------
# End-to-end run_synthesizer() tests
# ---------------------------------------------------------------------------


class TestSynthesizerEndToEnd:
    """End-to-end tests for run_synthesizer() with full graph execution."""

    @pytest.mark.asyncio
    async def test_rich_observations_produce_verdict(self, ctx):
        synth_input: SynthesizerInput = {"observations": _rich_observations()}
        with _mock_narrator():
            result = await run_synthesizer(synth_input, ctx)

        assert result["verdict"] is not None
        assert isinstance(result["verdict"], str)
        assert len(result["verdict"]) > 0
        assert result["verdict"] != "UNVERIFIABLE"

    @pytest.mark.asyncio
    async def test_supporting_evidence_produces_true_verdict(self, ctx):
        synth_input: SynthesizerInput = {"observations": _supporting_observations()}
        with _mock_narrator():
            result = await run_synthesizer(synth_input, ctx)

        # All evidence supports the claim with high confidence
        assert result["verdict"] == "TRUE"
        assert result["confidence"] is not None
        assert result["confidence"] >= 0.90

    @pytest.mark.asyncio
    async def test_empty_observations_produce_unverifiable(self, ctx):
        synth_input: SynthesizerInput = {"observations": []}
        with _mock_narrator():
            result = await run_synthesizer(synth_input, ctx)

        assert result["verdict"] == "UNVERIFIABLE"
        assert result["confidence"] is None

    @pytest.mark.asyncio
    async def test_sparse_observations_at_threshold(self, ctx):
        """Exactly 5 signals (MIN_SIGNAL_COUNT) should produce a score, not None."""
        synth_input: SynthesizerInput = {"observations": _sparse_observations()}
        with _mock_narrator():
            result = await run_synthesizer(synth_input, ctx)

        assert result["verdict"] != "UNVERIFIABLE"
        assert result["confidence"] is not None
        assert 0.0 <= result["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# Observation publishing verification
# ---------------------------------------------------------------------------


class TestObservationPublishing:
    """Verify correct observation codes published through run_synthesizer()."""

    @pytest.mark.asyncio
    async def test_publishes_synthesis_signal_count(self, ctx):
        synth_input: SynthesizerInput = {"observations": _rich_observations()}
        with _mock_narrator():
            await run_synthesizer(synth_input, ctx)

        codes = [str(o["code"]) for o in ctx.published_observations]
        assert any("SYNTHESIS_SIGNAL_COUNT" in c for c in codes)

    @pytest.mark.asyncio
    async def test_publishes_confidence_score(self, ctx):
        synth_input: SynthesizerInput = {"observations": _rich_observations()}
        with _mock_narrator():
            await run_synthesizer(synth_input, ctx)

        codes = [str(o["code"]) for o in ctx.published_observations]
        assert any("CONFIDENCE_SCORE" in c for c in codes)

    @pytest.mark.asyncio
    async def test_publishes_verdict(self, ctx):
        synth_input: SynthesizerInput = {"observations": _rich_observations()}
        with _mock_narrator():
            await run_synthesizer(synth_input, ctx)

        codes = [str(o["code"]) for o in ctx.published_observations]
        # VERDICT (not VERDICT_NARRATIVE)
        assert any(c == "VERDICT" or c == "ObservationCode.VERDICT" for c in codes)

    @pytest.mark.asyncio
    async def test_publishes_verdict_narrative(self, ctx):
        synth_input: SynthesizerInput = {"observations": _rich_observations()}
        with _mock_narrator():
            await run_synthesizer(synth_input, ctx)

        codes = [str(o["code"]) for o in ctx.published_observations]
        assert any("VERDICT_NARRATIVE" in c for c in codes)

    @pytest.mark.asyncio
    async def test_no_confidence_published_when_unverifiable(self, ctx):
        """CONFIDENCE_SCORE is NOT published when score is None."""
        synth_input: SynthesizerInput = {"observations": []}
        with _mock_narrator():
            await run_synthesizer(synth_input, ctx)

        codes = [str(o["code"]) for o in ctx.published_observations]
        assert not any("CONFIDENCE_SCORE" in c for c in codes)

    @pytest.mark.asyncio
    async def test_observation_publishing_order(self, ctx):
        """Observations are published in graph node order: signal_count before verdict."""
        synth_input: SynthesizerInput = {"observations": _rich_observations()}
        with _mock_narrator():
            await run_synthesizer(synth_input, ctx)

        codes = [str(o["code"]) for o in ctx.published_observations]
        signal_idx = next(
            i for i, c in enumerate(codes) if "SYNTHESIS_SIGNAL_COUNT" in c
        )
        verdict_idx = next(
            i for i, c in enumerate(codes)
            if "VERDICT" in c and "NARRATIVE" not in c
        )
        narrative_idx = next(
            i for i, c in enumerate(codes) if "VERDICT_NARRATIVE" in c
        )

        assert signal_idx < verdict_idx < narrative_idx

    @pytest.mark.asyncio
    async def test_all_observations_have_synthesizer_agent(self, ctx):
        """All published observations have agent='synthesizer'."""
        synth_input: SynthesizerInput = {"observations": _rich_observations()}
        with _mock_narrator():
            await run_synthesizer(synth_input, ctx)

        for obs in ctx.published_observations:
            assert obs["agent"] == AGENT_NAME

    @pytest.mark.asyncio
    async def test_override_publishes_override_reason_observation(self, ctx):
        """ClaimReview override publishes a SYNTHESIS_OVERRIDE_REASON observation."""
        synth_input: SynthesizerInput = {"observations": _override_observations()}
        with _mock_narrator():
            await run_synthesizer(synth_input, ctx)

        codes = [str(o["code"]) for o in ctx.published_observations]
        assert any("SYNTHESIS_OVERRIDE_REASON" in c for c in codes)


# ---------------------------------------------------------------------------
# Progress and heartbeat verification
# ---------------------------------------------------------------------------


class TestProgressAndHeartbeat:
    """Verify progress events and heartbeat signaling."""

    @pytest.mark.asyncio
    async def test_heartbeat_called_at_start(self, ctx):
        synth_input: SynthesizerInput = {"observations": []}
        with _mock_narrator():
            await run_synthesizer(synth_input, ctx)

        assert "synthesizer" in ctx.heartbeat_calls

    @pytest.mark.asyncio
    async def test_publishes_beginning_progress(self, ctx):
        synth_input: SynthesizerInput = {"observations": []}
        with _mock_narrator():
            await run_synthesizer(synth_input, ctx)

        messages = [p["message"] for p in ctx.published_progress]
        assert any("Beginning" in m for m in messages)

    @pytest.mark.asyncio
    async def test_publishes_verdict_progress(self, ctx):
        synth_input: SynthesizerInput = {"observations": _rich_observations()}
        with _mock_narrator():
            await run_synthesizer(synth_input, ctx)

        messages = [p["message"] for p in ctx.published_progress]
        assert any("Verdict" in m for m in messages)

    @pytest.mark.asyncio
    async def test_progress_confidence_format_verifiable(self, ctx):
        """Verifiable verdict includes numeric confidence in progress message."""
        synth_input: SynthesizerInput = {"observations": _rich_observations()}
        with _mock_narrator():
            await run_synthesizer(synth_input, ctx)

        verdict_msgs = [p["message"] for p in ctx.published_progress if "Verdict" in p["message"]]
        assert len(verdict_msgs) >= 1
        # Should contain "confidence: 0.XXXX" format, not "unverifiable"
        assert "unverifiable" not in verdict_msgs[-1]

    @pytest.mark.asyncio
    async def test_progress_confidence_format_unverifiable(self, ctx):
        """Unverifiable verdict shows 'unverifiable' in progress message."""
        synth_input: SynthesizerInput = {"observations": []}
        with _mock_narrator():
            await run_synthesizer(synth_input, ctx)

        verdict_msgs = [p["message"] for p in ctx.published_progress if "Verdict" in p["message"]]
        assert len(verdict_msgs) >= 1
        assert "unverifiable" in verdict_msgs[-1]

    @pytest.mark.asyncio
    async def test_all_progress_from_synthesizer_agent(self, ctx):
        """All progress events are published with agent='synthesizer'."""
        synth_input: SynthesizerInput = {"observations": _rich_observations()}
        with _mock_narrator():
            await run_synthesizer(synth_input, ctx)

        for progress in ctx.published_progress:
            assert progress["agent"] == AGENT_NAME


# ---------------------------------------------------------------------------
# ClaimReview override integration
# ---------------------------------------------------------------------------


class TestClaimReviewOverrideIntegration:
    """End-to-end ClaimReview override through the full synthesizer graph."""

    @pytest.mark.asyncio
    async def test_override_changes_verdict(self, ctx):
        """Swarm says TRUE but ClaimReview says FALSE -> verdict is FALSE."""
        synth_input: SynthesizerInput = {"observations": _override_observations()}
        with _mock_narrator():
            result = await run_synthesizer(synth_input, ctx)

        assert result["verdict"] == "FALSE"

    @pytest.mark.asyncio
    async def test_override_reason_contains_source(self, ctx):
        synth_input: SynthesizerInput = {"observations": _override_observations()}
        with _mock_narrator():
            result = await run_synthesizer(synth_input, ctx)

        assert "PolitiFact" in result["override_reason"]
        assert "ClaimReview override" in result["override_reason"]

    @pytest.mark.asyncio
    async def test_no_override_when_verdicts_agree(self, ctx):
        """No override when ClaimReview and swarm agree on the verdict."""
        # ClaimReview says TRUE, swarm evidence supports → both TRUE
        obs = [
            _obs("evidence", "DOMAIN_EVIDENCE_ALIGNMENT", "SUPPORTS^Supports^FCK", "CWE", seq=1),
            _obs("evidence", "DOMAIN_CONFIDENCE", "0.95", "NM", seq=2),
            _obs("evidence", "CLAIMREVIEW_MATCH", "TRUE^True^FCK", "CWE", seq=3),
            _obs("evidence", "CLAIMREVIEW_VERDICT", "TRUE^True^POLITIFACT", "CWE", seq=4),
            _obs("evidence", "CLAIMREVIEW_SOURCE", "PolitiFact", "ST", seq=5),
            _obs("evidence", "CLAIMREVIEW_MATCH_SCORE", "0.95", "NM", seq=6),
            _obs("coverage-left", "COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK", "CWE", seq=1),
            _obs("coverage-center", "COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK", "CWE", seq=1),
            _obs("coverage-right", "COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK", "CWE", seq=1),
            _obs("validation", "SOURCE_CONVERGENCE_SCORE", "0.90", "NM", seq=1),
            _obs("validation", "BLINDSPOT_SCORE", "0.00", "NM", seq=2),
            _obs("validation", "CROSS_SPECTRUM_CORROBORATION", "TRUE^True^FCK", "CWE", seq=3),
        ]
        synth_input: SynthesizerInput = {"observations": obs}
        with _mock_narrator():
            result = await run_synthesizer(synth_input, ctx)

        assert result["verdict"] == "TRUE"
        assert result["override_reason"] == ""

    @pytest.mark.asyncio
    async def test_override_verdict_observations_reflect_override(self, ctx):
        """verdict_observations contain the overridden verdict code."""
        synth_input: SynthesizerInput = {"observations": _override_observations()}
        with _mock_narrator():
            result = await run_synthesizer(synth_input, ctx)

        verdict_obs = [o for o in result["verdict_observations"] if o["code"] == "VERDICT"]
        assert len(verdict_obs) == 1
        assert "FALSE" in verdict_obs[0]["value"]


# ---------------------------------------------------------------------------
# Output contract verification
# ---------------------------------------------------------------------------


class TestOutputContract:
    """Verify SynthesizerOutput typed contract compliance."""

    @pytest.mark.asyncio
    async def test_all_output_fields_present(self, ctx):
        synth_input: SynthesizerInput = {"observations": _rich_observations()}
        with _mock_narrator():
            result = await run_synthesizer(synth_input, ctx)

        assert "verdict" in result
        assert "confidence" in result
        assert "narrative" in result
        assert "verdict_observations" in result
        assert "override_reason" in result

    @pytest.mark.asyncio
    async def test_verdict_observations_are_well_formed(self, ctx):
        synth_input: SynthesizerInput = {"observations": _rich_observations()}
        with _mock_narrator():
            result = await run_synthesizer(synth_input, ctx)

        for obs in result["verdict_observations"]:
            assert "agent" in obs
            assert obs["agent"] == "synthesizer"
            assert "code" in obs
            assert "value" in obs
            assert "value_type" in obs

    @pytest.mark.asyncio
    async def test_verdict_observations_contain_expected_codes(self, ctx):
        synth_input: SynthesizerInput = {"observations": _rich_observations()}
        with _mock_narrator():
            result = await run_synthesizer(synth_input, ctx)

        codes = {o["code"] for o in result["verdict_observations"]}
        assert "SYNTHESIS_SIGNAL_COUNT" in codes
        assert "VERDICT" in codes
        assert "VERDICT_NARRATIVE" in codes
        # CONFIDENCE_SCORE only present when score is not None
        assert "CONFIDENCE_SCORE" in codes

    @pytest.mark.asyncio
    async def test_unverifiable_verdict_observations(self, ctx):
        """UNVERIFIABLE output still includes signal count, verdict, and narrative."""
        synth_input: SynthesizerInput = {"observations": []}
        with _mock_narrator():
            result = await run_synthesizer(synth_input, ctx)

        codes = {o["code"] for o in result["verdict_observations"]}
        assert "SYNTHESIS_SIGNAL_COUNT" in codes
        assert "VERDICT" in codes
        assert "VERDICT_NARRATIVE" in codes
        # No CONFIDENCE_SCORE when unverifiable
        assert "CONFIDENCE_SCORE" not in codes
