"""Tests for pipeline graph wiring and state output (M0.3 / M1.2 / M2.2 / M4.2 / M5.2).

Verifies graph structure (correct nodes/edges), routing behavior
(check-worthy fan-out vs. not-check-worthy shortcut), that real
node implementations are wired in and execute through the graph,
that the validation node populates validated_urls, convergence_score,
citations, blindspot_score, and blindspot_direction in the output state,
and that the synthesizer terminal node populates verdict, confidence,
narrative, and verdict_observations in the output state.
"""

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.synthesizer.narrator import NarrativeGenerator
from swarm_reasoning.pipeline.context import PipelineContext
from swarm_reasoning.pipeline.graph import (
    build_pipeline_graph,
    coverage_node,
    intake_node,
    pipeline_graph,
    route_after_intake,
    synthesizer_node,
    validation_node,
)
from swarm_reasoning.pipeline.state import PipelineState


def _make_mock_pipeline_context() -> MagicMock:
    """Create a mock PipelineContext for tests that traverse pipeline nodes."""
    ctx = MagicMock()
    ctx.publish_observation = AsyncMock()
    ctx.publish_progress = AsyncMock()
    ctx.heartbeat = MagicMock()
    ctx.next_seq = MagicMock(return_value=1)
    ctx.run_id = "test-run"
    ctx.session_id = "test-session"
    ctx.redis_client = AsyncMock()
    ctx.stream = AsyncMock()
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

    def test_coverage_node_is_wired(self):
        """Verify coverage_node is the real implementation, not a placeholder."""
        from swarm_reasoning.pipeline.nodes.coverage import (
            coverage_node as real_coverage,
        )

        assert coverage_node is real_coverage

    def test_synthesizer_node_is_wired(self):
        """Verify synthesizer_node is the real implementation, not a placeholder."""
        from swarm_reasoning.pipeline.nodes.synthesizer import (
            synthesizer_node as real_synthesizer,
        )

        assert synthesizer_node is real_synthesizer

    def test_validation_node_is_wired(self):
        """Verify validation_node is the real implementation, not a placeholder."""
        from swarm_reasoning.pipeline.nodes.validation import (
            validation_node as real_validation,
        )

        assert validation_node is real_validation


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
    @patch("swarm_reasoning.pipeline.nodes.evidence.resilient_get", new_callable=AsyncMock)
    async def test_check_worthy_path(self, mock_get):
        """Intake accepts claim and routes through fan-out path."""
        mock_get.side_effect = ConnectionError("no network in tests")
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
        # Rejected claim -> is_check_worthy=False -> synthesizer shortcut
        assert result["is_check_worthy"] is False
        assert any("rejected" in e.lower() for e in result["errors"])


class TestValidationStateOutput:
    """Verify validation node populates state output fields (M4.2).

    The validation node runs after evidence+coverage fan-in on the
    check-worthy path. These tests verify that after full graph execution,
    the output state contains the five validation fields: validated_urls,
    convergence_score, citations, blindspot_score, blindspot_direction.
    """

    @staticmethod
    def _check_worthy_mocks():
        """Return context managers that mock all external deps for check-worthy path."""
        mock_dup, mock_client, mock_claude = _intake_mocks()
        return [
            mock_dup,
            mock_client,
            mock_claude,
            patch(
                "swarm_reasoning.pipeline.nodes.intake.score_claim_text",
                return_value=MagicMock(
                    score=0.85, rationale="Factual claim", proceed=True, passes=[0.85],
                ),
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.intake.extract_entities_llm",
                return_value=MagicMock(
                    persons=[], organizations=[], dates=[], locations=[], statistics=[],
                ),
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
                new_callable=AsyncMock,
                side_effect=ConnectionError("no network in tests"),
            ),
            patch.object(
                NarrativeGenerator, "generate",
                new_callable=AsyncMock, return_value="X" * 250,
            ),
        ]

    async def _invoke_check_worthy(self, state):
        """Run pipeline through check-worthy path with all external deps mocked."""
        with ExitStack() as stack:
            for cm in self._check_worthy_mocks():
                stack.enter_context(cm)
            return await pipeline_graph.ainvoke(state, _make_config_with_context())

    @pytest.mark.asyncio
    async def test_check_worthy_path_populates_validated_urls(self):
        """Check-worthy path with no upstream URLs produces empty validated_urls."""
        state: PipelineState = {
            "claim_text": "The unemployment rate dropped to 3.5% in January 2024",
            "run_id": "run-m42-1",
            "session_id": "sess-m42-1",
            "observations": [],
            "errors": [],
        }
        result = await self._invoke_check_worthy(state)

        assert "validated_urls" in result
        assert isinstance(result["validated_urls"], list)

    @pytest.mark.asyncio
    async def test_check_worthy_path_populates_convergence_score(self):
        """Check-worthy path populates convergence_score as a float."""
        state: PipelineState = {
            "claim_text": "The unemployment rate dropped to 3.5% in January 2024",
            "run_id": "run-m42-2",
            "session_id": "sess-m42-2",
            "observations": [],
            "errors": [],
        }
        result = await self._invoke_check_worthy(state)

        assert "convergence_score" in result
        assert isinstance(result["convergence_score"], float)
        assert 0.0 <= result["convergence_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_check_worthy_path_populates_citations(self):
        """Check-worthy path populates citations list."""
        state: PipelineState = {
            "claim_text": "The unemployment rate dropped to 3.5% in January 2024",
            "run_id": "run-m42-3",
            "session_id": "sess-m42-3",
            "observations": [],
            "errors": [],
        }
        result = await self._invoke_check_worthy(state)

        assert "citations" in result
        assert isinstance(result["citations"], list)

    @pytest.mark.asyncio
    async def test_check_worthy_path_populates_blindspot_score(self):
        """Check-worthy path populates blindspot_score as a float."""
        state: PipelineState = {
            "claim_text": "The unemployment rate dropped to 3.5% in January 2024",
            "run_id": "run-m42-4",
            "session_id": "sess-m42-4",
            "observations": [],
            "errors": [],
        }
        result = await self._invoke_check_worthy(state)

        assert "blindspot_score" in result
        assert isinstance(result["blindspot_score"], float)
        assert 0.0 <= result["blindspot_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_check_worthy_path_populates_blindspot_direction(self):
        """Check-worthy path populates blindspot_direction as a string."""
        state: PipelineState = {
            "claim_text": "The unemployment rate dropped to 3.5% in January 2024",
            "run_id": "run-m42-5",
            "session_id": "sess-m42-5",
            "observations": [],
            "errors": [],
        }
        result = await self._invoke_check_worthy(state)

        assert "blindspot_direction" in result
        assert isinstance(result["blindspot_direction"], str)
        assert len(result["blindspot_direction"]) > 0

    @pytest.mark.asyncio
    async def test_all_validation_fields_present(self):
        """All five validation output fields survive to final pipeline state."""
        state: PipelineState = {
            "claim_text": "The unemployment rate dropped to 3.5% in January 2024",
            "run_id": "run-m42-6",
            "session_id": "sess-m42-6",
            "observations": [],
            "errors": [],
        }
        result = await self._invoke_check_worthy(state)

        for field in (
            "validated_urls",
            "convergence_score",
            "citations",
            "blindspot_score",
            "blindspot_direction",
        ):
            assert field in result, f"Missing validation output field: {field}"

    @pytest.mark.asyncio
    async def test_not_check_worthy_skips_validation(self):
        """Not-check-worthy path shortcuts to synthesizer, skipping validation fields."""
        state: PipelineState = {
            "claim_text": "Hi",
            "run_id": "run-m42-7",
            "session_id": "sess-m42-7",
            "observations": [],
            "errors": [],
        }
        result = await pipeline_graph.ainvoke(state, _make_config_with_context())

        # Rejected claim -> is_check_worthy=False -> synthesizer shortcut
        # Validation fields should not be in output
        assert "validated_urls" not in result
        assert "convergence_score" not in result


class TestSynthesizerStateOutput:
    """Verify synthesizer terminal node populates state output fields (M5.2).

    The synthesizer is the terminal node. These tests verify that after
    full graph execution, the output state contains the four key fields:
    verdict, confidence, narrative, verdict_observations.
    """

    @staticmethod
    def _check_worthy_mocks():
        """Return context managers that mock all external deps for check-worthy path."""
        mock_dup, mock_client, mock_claude = _intake_mocks()
        return [
            mock_dup,
            mock_client,
            mock_claude,
            patch(
                "swarm_reasoning.pipeline.nodes.intake.score_claim_text",
                return_value=MagicMock(
                    score=0.85, rationale="Factual claim", proceed=True, passes=[0.85],
                ),
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.intake.extract_entities_llm",
                return_value=MagicMock(
                    persons=[], organizations=[], dates=[], locations=[], statistics=[],
                ),
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
                new_callable=AsyncMock,
                side_effect=ConnectionError("no network in tests"),
            ),
            patch.object(
                NarrativeGenerator, "generate",
                new_callable=AsyncMock, return_value="X" * 250,
            ),
        ]

    async def _invoke_check_worthy(self, state):
        """Run pipeline through check-worthy path with all external deps mocked."""
        with ExitStack() as stack:
            for cm in self._check_worthy_mocks():
                stack.enter_context(cm)
            return await pipeline_graph.ainvoke(state, _make_config_with_context())

    @pytest.mark.asyncio
    async def test_check_worthy_path_populates_verdict(self):
        """Check-worthy path with no upstream observations produces UNVERIFIABLE."""
        state: PipelineState = {
            "claim_text": "The economy grew 5% last quarter",
            "run_id": "run-m52-1",
            "session_id": "sess-m52-1",
            "observations": [],
            "errors": [],
        }
        result = await self._invoke_check_worthy(state)

        assert "verdict" in result
        assert result["verdict"] == "UNVERIFIABLE"

    @pytest.mark.asyncio
    async def test_check_worthy_path_populates_confidence(self):
        """Check-worthy with no upstream data yields None confidence."""
        state: PipelineState = {
            "claim_text": "Claim for confidence test",
            "run_id": "run-m52-2",
            "session_id": "sess-m52-2",
            "observations": [],
            "errors": [],
        }
        result = await self._invoke_check_worthy(state)

        assert "confidence" in result
        assert result["confidence"] is None

    @pytest.mark.asyncio
    async def test_check_worthy_path_populates_narrative(self):
        """Narrative field populated by synthesizer."""
        state: PipelineState = {
            "claim_text": "Claim for narrative test",
            "run_id": "run-m52-3",
            "session_id": "sess-m52-3",
            "observations": [],
            "errors": [],
        }
        result = await self._invoke_check_worthy(state)

        assert "narrative" in result
        assert isinstance(result["narrative"], str)
        assert len(result["narrative"]) > 0

    @pytest.mark.asyncio
    async def test_check_worthy_path_populates_verdict_observations(self):
        """verdict_observations list is present and well-structured."""
        state: PipelineState = {
            "claim_text": "Claim for observations test",
            "run_id": "run-m52-4",
            "session_id": "sess-m52-4",
            "observations": [],
            "errors": [],
        }
        result = await self._invoke_check_worthy(state)

        assert "verdict_observations" in result
        assert isinstance(result["verdict_observations"], list)
        for obs in result["verdict_observations"]:
            assert "agent" in obs
            assert "code" in obs
            assert "value" in obs

    @pytest.mark.asyncio
    async def test_not_check_worthy_populates_verdict_state(self):
        """Not-check-worthy shortcut populates all four synthesizer output fields."""
        state: PipelineState = {
            "claim_text": "What time is it?",
            "run_id": "run-m52-5",
            "session_id": "sess-m52-5",
            "observations": [],
            "errors": [],
        }
        mock_dup, mock_client, mock_claude = _intake_mocks()
        with ExitStack() as stack:
            stack.enter_context(mock_dup)
            stack.enter_context(mock_client)
            stack.enter_context(mock_claude)
            stack.enter_context(patch(
                "swarm_reasoning.pipeline.nodes.intake.score_claim_text",
                return_value=MagicMock(
                    score=0.12, rationale="Not check-worthy",
                    proceed=False, passes=[0.12],
                ),
            ))
            result = await pipeline_graph.ainvoke(state, _make_config_with_context())

        assert result["verdict"] == "NOT_CHECK_WORTHY"
        assert result["confidence"] == 1.0
        assert "not check-worthy" in result["narrative"].lower()
        assert isinstance(result["verdict_observations"], list)

    @pytest.mark.asyncio
    async def test_synthesizer_is_terminal_node(self):
        """Verify synthesizer output fields survive to final state (no post-processing)."""
        state: PipelineState = {
            "claim_text": "Terminal node test",
            "run_id": "run-m52-6",
            "session_id": "sess-m52-6",
            "observations": [],
            "errors": [],
        }
        mock_dup, mock_client, mock_claude = _intake_mocks()
        with ExitStack() as stack:
            stack.enter_context(mock_dup)
            stack.enter_context(mock_client)
            stack.enter_context(mock_claude)
            stack.enter_context(patch(
                "swarm_reasoning.pipeline.nodes.intake.score_claim_text",
                return_value=MagicMock(
                    score=0.12, rationale="Not check-worthy",
                    proceed=False, passes=[0.12],
                ),
            ))
            result = await pipeline_graph.ainvoke(state, _make_config_with_context())

        # All four synthesizer output fields must be present at graph output
        for field in ("verdict", "confidence", "narrative", "verdict_observations"):
            assert field in result, f"Missing synthesizer output field: {field}"
