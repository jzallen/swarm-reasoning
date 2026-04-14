"""Tests for pipeline graph wiring (M0.3 + M1.2).

Verifies graph structure (correct nodes/edges), routing behavior
(check-worthy fan-out vs. not-check-worthy shortcut), and that real
node implementations are wired in and execute through the graph.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.pipeline.context import PipelineContext
from swarm_reasoning.pipeline.graph import (
    build_pipeline_graph,
    intake_node,
    pipeline_graph,
    route_after_intake,
)
from swarm_reasoning.pipeline.state import PipelineState


def _make_mock_pipeline_context() -> PipelineContext:
    """Create a mock PipelineContext for tests that traverse real nodes."""
    ctx = MagicMock(spec=PipelineContext)
    ctx.run_id = "run-test"
    ctx.session_id = "sess-test"
    ctx.redis_client = AsyncMock()
    ctx.publish_observation = AsyncMock()
    ctx.publish_progress = AsyncMock()
    ctx.heartbeat = MagicMock()
    ctx.next_seq = MagicMock(return_value=1)
    return ctx


def _make_config_with_context() -> dict:
    """Build a LangGraph-compatible config dict with a mock PipelineContext."""
    return {"configurable": {"pipeline_context": _make_mock_pipeline_context()}}


def _intake_mocks():
    """Context manager stack that mocks intake node's external dependencies."""
    return (
        patch(
            "swarm_reasoning.pipeline.nodes.intake._get_anthropic_client",
            return_value=AsyncMock(),
        ),
        patch(
            "swarm_reasoning.pipeline.nodes.intake.check_duplicate",
            return_value=False,
        ),
        patch(
            "swarm_reasoning.pipeline.nodes.intake.call_claude",
            return_value="POLITICS",
        ),
    )


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

    def test_intake_node_is_wired(self):
        """Verify intake_node is the real implementation, not a placeholder."""
        from swarm_reasoning.pipeline.nodes.intake import (
            intake_node as real_intake,
        )

        assert intake_node is real_intake


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
    """End-to-end execution of the pipeline graph with wired nodes."""

    @pytest.mark.asyncio
    async def test_check_worthy_path(self):
        """Intake accepts claim and routes through fan-out path."""
        state: PipelineState = {
            "claim_text": "The unemployment rate dropped to 3.5% in January 2024",
            "run_id": "run-1",
            "session_id": "sess-1",
            "observations": [],
            "errors": [],
        }
        mock_dup, mock_client, mock_claude = _intake_mocks()
        with mock_dup, mock_client, mock_claude, patch(
            "swarm_reasoning.pipeline.nodes.intake.score_claim_text",
        ) as mock_score, patch(
            "swarm_reasoning.pipeline.nodes.intake.extract_entities_llm",
        ) as mock_extract:
            mock_score.return_value = MagicMock(
                score=0.85, rationale="Strong factual claim",
                proceed=True, passes=[0.85],
            )
            mock_extract.return_value = MagicMock(
                persons=[], organizations=[], dates=["January 2024"],
                locations=[], statistics=["3.5%"],
            )
            result = await pipeline_graph.ainvoke(
                state, _make_config_with_context(),
            )

        assert result["is_check_worthy"] is True
        assert result["normalized_claim"] is not None
        assert result["run_id"] == "run-1"

    @pytest.mark.asyncio
    async def test_not_check_worthy_path(self):
        """Intake scores claim below threshold, shortcuts to synthesizer."""
        state: PipelineState = {
            "claim_text": "The unemployment rate dropped to 3.5% in January 2024",
            "run_id": "run-2",
            "session_id": "sess-2",
            "observations": [],
            "errors": [],
        }
        mock_dup, mock_client, mock_claude = _intake_mocks()
        with mock_dup, mock_client, mock_claude, patch(
            "swarm_reasoning.pipeline.nodes.intake.score_claim_text",
        ) as mock_score:
            mock_score.return_value = MagicMock(
                score=0.15, rationale="Not check-worthy",
                proceed=False, passes=[0.15],
            )
            result = await pipeline_graph.ainvoke(
                state, _make_config_with_context(),
            )

        assert result["is_check_worthy"] is False

    @pytest.mark.asyncio
    async def test_rejected_claim_routes_to_synthesizer(self):
        """Claim too short for validation is rejected and routes to synthesizer."""
        state: PipelineState = {
            "claim_text": "Hi",
            "run_id": "run-3",
            "session_id": "sess-3",
            "observations": [],
            "errors": [],
        }
        result = await pipeline_graph.ainvoke(
            state, _make_config_with_context(),
        )
        # Rejected claim → is_check_worthy=False → synthesizer shortcut
        assert result["is_check_worthy"] is False
        assert any("rejected" in e.lower() for e in result["errors"])
