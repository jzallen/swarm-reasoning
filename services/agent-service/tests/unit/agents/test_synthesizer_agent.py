"""Tests for synthesizer agent StateGraph (resolve → score → map → narrate).

Verifies:
- Graph topology (4 nodes in fixed sequence)
- Agent graph invocation with and without PipelineContext
- SynthesizerInput/Output typed contracts
- Observation publishing via PipelineContext through graph nodes
- Module re-exports from agents.synthesizer package
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

from swarm_reasoning.agents.synthesizer.agent import (
    AGENT_NAME,
    SynthesizerGraphState,
    build_synthesizer_graph,
    map_node,
    narrate_node,
    resolve_node,
    score_node,
    synthesizer_graph,
)
from swarm_reasoning.agents.synthesizer.models import (
    SynthesizerInput,
    SynthesizerOutput,
)
from swarm_reasoning.agents.synthesizer.narrator import NarrativeGenerator


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


# ---------------------------------------------------------------------------
# Graph topology tests
# ---------------------------------------------------------------------------


class TestGraphTopology:
    """Verify the StateGraph has the correct nodes and edges."""

    def test_graph_has_four_nodes(self):
        graph = build_synthesizer_graph()
        # LangGraph compiled graphs expose node names
        node_names = set(graph.get_graph().nodes.keys()) - {"__start__", "__end__"}
        assert node_names == {"resolve", "score", "map", "narrate"}

    def test_module_level_graph_is_compiled(self):
        assert synthesizer_graph is not None
        # Should be invokable
        assert hasattr(synthesizer_graph, "ainvoke")


# ---------------------------------------------------------------------------
# Individual node tests
# ---------------------------------------------------------------------------


class TestResolveNode:
    """Test the resolve graph node in isolation."""

    @pytest.mark.asyncio
    async def test_resolve_empty_observations(self):
        state: SynthesizerGraphState = {"observations": []}
        result = await resolve_node(state, _make_config())
        assert result["resolved"].synthesis_signal_count == 0

    @pytest.mark.asyncio
    async def test_resolve_publishes_signal_count(self):
        ctx = FakePipelineContext()
        state: SynthesizerGraphState = {"observations": _build_rich_observations()}
        await resolve_node(state, _make_config(ctx))
        signal_obs = [
            o for o in ctx.published_observations
            if "SYNTHESIS_SIGNAL_COUNT" in str(o["code"])
        ]
        assert len(signal_obs) == 1

    @pytest.mark.asyncio
    async def test_resolve_without_pipeline_context(self):
        """Graph nodes work without PipelineContext (no publishing)."""
        state: SynthesizerGraphState = {"observations": _build_rich_observations()}
        config = {"configurable": {}}
        result = await resolve_node(state, config)
        assert result["resolved"].synthesis_signal_count > 0


class TestScoreNode:
    """Test the score graph node in isolation."""

    @pytest.mark.asyncio
    async def test_score_with_rich_observations(self):
        from swarm_reasoning.agents.synthesizer.resolver import resolve_from_state

        resolved = resolve_from_state(_build_rich_observations())
        state: SynthesizerGraphState = {"resolved": resolved}
        result = await score_node(state, _make_config())
        assert result["confidence_score"] is not None
        assert 0.0 <= result["confidence_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_score_insufficient_signals(self):
        from swarm_reasoning.agents.synthesizer.resolver import resolve_from_state

        resolved = resolve_from_state([
            _make_obs("evidence", "DOMAIN_CONFIDENCE", "0.8", "NM"),
        ])
        state: SynthesizerGraphState = {"resolved": resolved}
        result = await score_node(state, _make_config())
        assert result["confidence_score"] is None

    @pytest.mark.asyncio
    async def test_score_publishes_observation(self):
        from swarm_reasoning.agents.synthesizer.resolver import resolve_from_state

        ctx = FakePipelineContext()
        resolved = resolve_from_state(_build_rich_observations())
        state: SynthesizerGraphState = {"resolved": resolved}
        await score_node(state, _make_config(ctx))
        score_obs = [
            o for o in ctx.published_observations
            if "CONFIDENCE_SCORE" in str(o["code"])
        ]
        assert len(score_obs) == 1


class TestMapNode:
    """Test the map graph node in isolation."""

    @pytest.mark.asyncio
    async def test_map_unverifiable(self):
        from swarm_reasoning.agents.synthesizer.resolver import resolve_from_state

        resolved = resolve_from_state([])
        state: SynthesizerGraphState = {
            "resolved": resolved,
            "confidence_score": None,
        }
        result = await map_node(state, _make_config())
        assert result["verdict_code"] == "UNVERIFIABLE"

    @pytest.mark.asyncio
    async def test_map_high_confidence(self):
        from swarm_reasoning.agents.synthesizer.resolver import resolve_from_state

        # Use observations without ClaimReview to avoid override
        obs_no_cr = [
            _make_obs("evidence", "DOMAIN_EVIDENCE_ALIGNMENT", "SUPPORTS^Supports^FCK", "CWE", seq=1),
            _make_obs("evidence", "DOMAIN_CONFIDENCE", "0.95", "NM", seq=2),
            _make_obs("coverage-left", "COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK", "CWE", seq=1),
            _make_obs("coverage-center", "COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK", "CWE", seq=1),
            _make_obs("coverage-right", "COVERAGE_FRAMING", "SUPPORTIVE^Supportive^FCK", "CWE", seq=1),
            _make_obs("validation", "SOURCE_CONVERGENCE_SCORE", "0.90", "NM", seq=1),
        ]
        resolved = resolve_from_state(obs_no_cr)
        state: SynthesizerGraphState = {
            "resolved": resolved,
            "confidence_score": 0.95,
        }
        result = await map_node(state, _make_config())
        assert result["verdict_code"] == "TRUE"

    @pytest.mark.asyncio
    async def test_map_publishes_verdict(self):
        from swarm_reasoning.agents.synthesizer.resolver import resolve_from_state

        ctx = FakePipelineContext()
        resolved = resolve_from_state([])
        state: SynthesizerGraphState = {
            "resolved": resolved,
            "confidence_score": None,
        }
        await map_node(state, _make_config(ctx))
        verdict_obs = [
            o for o in ctx.published_observations
            if "VERDICT" in str(o["code"]) and "NARRATIVE" not in str(o["code"])
        ]
        assert len(verdict_obs) >= 1


# ---------------------------------------------------------------------------
# Full graph invocation tests
# ---------------------------------------------------------------------------


class TestSynthesizerGraph:
    """Test the compiled synthesizer graph end-to-end."""

    @pytest.mark.asyncio
    async def test_full_graph_with_rich_observations(self):
        ctx = FakePipelineContext()
        synth_input: SynthesizerInput = {
            "observations": _build_rich_observations(),
        }
        with patch.object(
            NarrativeGenerator,
            "generate",
            new_callable=AsyncMock,
            return_value="X" * 250,
        ):
            result = await synthesizer_graph.ainvoke(synth_input, config=_make_config(ctx))

        assert result["verdict_code"] is not None
        assert result["confidence_score"] is not None
        assert result["narrative"] == "X" * 250
        assert isinstance(result["verdict_observations"], list)
        assert len(result["verdict_observations"]) > 0

    @pytest.mark.asyncio
    async def test_full_graph_unverifiable(self):
        ctx = FakePipelineContext()
        synth_input: SynthesizerInput = {"observations": []}
        with patch.object(
            NarrativeGenerator,
            "generate",
            new_callable=AsyncMock,
            return_value="X" * 250,
        ):
            result = await synthesizer_graph.ainvoke(synth_input, config=_make_config(ctx))

        assert result["verdict_code"] == "UNVERIFIABLE"
        assert result["confidence_score"] is None

    @pytest.mark.asyncio
    async def test_full_graph_publishes_all_observations(self):
        """Graph publishes observations for each step via PipelineContext."""
        ctx = FakePipelineContext()
        synth_input: SynthesizerInput = {
            "observations": _build_rich_observations(),
        }
        with patch.object(
            NarrativeGenerator,
            "generate",
            new_callable=AsyncMock,
            return_value="X" * 250,
        ):
            await synthesizer_graph.ainvoke(synth_input, config=_make_config(ctx))

        codes = [str(o["code"]) for o in ctx.published_observations]
        # Should have SYNTHESIS_SIGNAL_COUNT, CONFIDENCE_SCORE, VERDICT, VERDICT_NARRATIVE
        assert any("SYNTHESIS_SIGNAL_COUNT" in c for c in codes)
        assert any("CONFIDENCE_SCORE" in c for c in codes)
        assert any("VERDICT" in c and "NARRATIVE" not in c for c in codes)
        assert any("VERDICT_NARRATIVE" in c for c in codes)

    @pytest.mark.asyncio
    async def test_full_graph_without_pipeline_context(self):
        """Graph runs without PipelineContext (no observation publishing)."""
        synth_input: SynthesizerInput = {
            "observations": _build_rich_observations(),
        }
        config = {"configurable": {}}
        with patch.object(
            NarrativeGenerator,
            "generate",
            new_callable=AsyncMock,
            return_value="X" * 250,
        ):
            result = await synthesizer_graph.ainvoke(synth_input, config=config)

        assert result["verdict_code"] is not None
        assert result["narrative"] == "X" * 250

    @pytest.mark.asyncio
    async def test_graph_publishes_progress_events(self):
        """Graph nodes publish progress events for SSE relay."""
        ctx = FakePipelineContext()
        synth_input: SynthesizerInput = {
            "observations": _build_rich_observations(),
        }
        with patch.object(
            NarrativeGenerator,
            "generate",
            new_callable=AsyncMock,
            return_value="X" * 250,
        ):
            await synthesizer_graph.ainvoke(synth_input, config=_make_config(ctx))

        messages = [p["message"] for p in ctx.published_progress]
        assert any("Resolving" in m for m in messages)


# ---------------------------------------------------------------------------
# Typed I/O contract tests
# ---------------------------------------------------------------------------


class TestSynthesizerIO:
    """Test the SynthesizerInput/Output typed contracts."""

    def test_synthesizer_input_type(self):
        inp: SynthesizerInput = {"observations": []}
        assert "observations" in inp

    def test_synthesizer_output_type(self):
        out: SynthesizerOutput = {
            "verdict": "TRUE",
            "confidence": 0.95,
            "narrative": "Test",
            "verdict_observations": [],
            "override_reason": "",
        }
        assert out["verdict"] == "TRUE"

    def test_agent_name_constant(self):
        assert AGENT_NAME == "synthesizer"


# ---------------------------------------------------------------------------
# Package re-export tests
# ---------------------------------------------------------------------------


class TestPackageReexports:
    """Test that the synthesizer package re-exports correctly."""

    def test_import_graph_from_package(self):
        from swarm_reasoning.agents.synthesizer import synthesizer_graph as sg
        assert sg is not None

    def test_import_build_graph_from_package(self):
        from swarm_reasoning.agents.synthesizer import build_synthesizer_graph as bsg
        assert callable(bsg)

    def test_import_input_output_from_package(self):
        from swarm_reasoning.agents.synthesizer import SynthesizerInput, SynthesizerOutput
        assert SynthesizerInput is not None
        assert SynthesizerOutput is not None

    def test_import_resolution_models_from_package(self):
        from swarm_reasoning.agents.synthesizer import ResolvedObservation, ResolvedObservationSet
        assert ResolvedObservation is not None
        assert ResolvedObservationSet is not None
