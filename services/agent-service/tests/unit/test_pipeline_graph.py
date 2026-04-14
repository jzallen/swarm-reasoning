"""Tests for pipeline graph skeleton (M0.3).

Verifies graph structure (correct nodes/edges) and routing behavior
(check-worthy fan-out vs. not-check-worthy shortcut).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from swarm_reasoning.pipeline.context import PipelineContext
from swarm_reasoning.pipeline.graph import (
    build_pipeline_graph,
    pipeline_graph,
    route_after_intake,
)
from swarm_reasoning.pipeline.state import PipelineState


def _make_mock_pipeline_context() -> PipelineContext:
    """Create a mock PipelineContext for tests that traverse the validation node."""
    ctx = MagicMock(spec=PipelineContext)
    ctx.publish_observation = AsyncMock()
    ctx.publish_progress = AsyncMock()
    ctx.heartbeat = MagicMock()
    ctx.next_seq = MagicMock(return_value=1)
    return ctx


def _make_config_with_context() -> dict:
    """Build a LangGraph-compatible config dict with a mock PipelineContext."""
    return {"configurable": {"pipeline_context": _make_mock_pipeline_context()}}


class TestGraphStructure:
    """Verify the compiled graph has the expected nodes and topology."""

    def test_graph_compiles(self):
        graph = build_pipeline_graph()
        assert graph is not None

    def test_all_nodes_present(self):
        nodes = set(pipeline_graph.get_graph().nodes)
        expected = {
            "__start__",
            "intake",
            "evidence",
            "coverage",
            "validation",
            "synthesizer",
            "__end__",
        }
        assert expected == nodes

    def test_build_pipeline_graph_is_idempotent(self):
        g1 = build_pipeline_graph()
        g2 = build_pipeline_graph()
        assert set(g1.get_graph().nodes) == set(g2.get_graph().nodes)


class TestRouting:
    """Verify route_after_intake conditional logic."""

    def test_check_worthy_fans_out(self):
        state: PipelineState = {
            "claim_text": "x",
            "run_id": "r",
            "session_id": "s",
            "is_check_worthy": True,
        }
        sends = route_after_intake(state)
        targets = sorted(s.node for s in sends)
        assert targets == ["coverage", "evidence"]

    def test_not_check_worthy_shortcuts_to_synthesizer(self):
        state: PipelineState = {
            "claim_text": "x",
            "run_id": "r",
            "session_id": "s",
            "is_check_worthy": False,
        }
        sends = route_after_intake(state)
        assert len(sends) == 1
        assert sends[0].node == "synthesizer"

    def test_missing_is_check_worthy_defaults_to_check_worthy(self):
        """When intake hasn't set is_check_worthy, default to True (fan-out)."""
        state: PipelineState = {"claim_text": "x", "run_id": "r", "session_id": "s"}
        sends = route_after_intake(state)
        targets = sorted(s.node for s in sends)
        assert targets == ["coverage", "evidence"]


class TestPipelineExecution:
    """End-to-end execution of the skeleton graph with placeholder nodes."""

    @pytest.mark.asyncio
    async def test_check_worthy_path(self):
        state: PipelineState = {
            "claim_text": "Test claim",
            "run_id": "run-1",
            "session_id": "sess-1",
            "is_check_worthy": True,
            "observations": [],
            "errors": [],
        }
        result = await pipeline_graph.ainvoke(state, _make_config_with_context())
        assert result["claim_text"] == "Test claim"
        assert result["run_id"] == "run-1"

    @pytest.mark.asyncio
    async def test_not_check_worthy_path(self):
        state: PipelineState = {
            "claim_text": "What time is it?",
            "run_id": "run-2",
            "session_id": "sess-2",
            "is_check_worthy": False,
            "observations": [],
            "errors": [],
        }
        result = await pipeline_graph.ainvoke(state)
        assert result["claim_text"] == "What time is it?"
        assert result["is_check_worthy"] is False

    @pytest.mark.asyncio
    async def test_observations_and_errors_merge(self):
        """Verify that list fields with add reducer don't lose data across branches."""
        state: PipelineState = {
            "claim_text": "Test",
            "run_id": "run-3",
            "session_id": "sess-3",
            "is_check_worthy": True,
            "observations": [],
            "errors": [],
        }
        result = await pipeline_graph.ainvoke(state, _make_config_with_context())
        # Placeholder nodes don't append, so lists remain empty
        assert result["observations"] == []
        assert result["errors"] == []
