"""Integration test for the full LangGraph pipeline (M6.4 / M7.4).

Exercises the compiled pipeline graph end-to-end through both major paths:
  1. Check-worthy path: intake -> evidence + coverage (fan-out) -> validation -> synthesizer
  2. Not-check-worthy path: intake -> synthesizer (shortcut)

All external I/O (Anthropic API, NewsAPI, HTTP fetches, Redis) is mocked.
The graph topology, node wiring, state propagation, fan-out routing,
fan-in merging, and observation accumulation are exercised for real.

M7.4 additions: per-stage PipelineState verification via streaming, and
specific observation code publishing verification per node.
"""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.synthesizer.narrator import NarrativeGenerator
from swarm_reasoning.pipeline.graph import pipeline_graph
from swarm_reasoning.pipeline.state import PipelineState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_pipeline_context() -> MagicMock:
    """Create a mock PipelineContext for integration tests."""
    ctx = MagicMock()
    ctx.publish_observation = AsyncMock()
    ctx.publish_progress = AsyncMock()
    ctx.heartbeat = MagicMock()
    ctx.next_seq = MagicMock(return_value=1)
    ctx.run_id = "integ-run"
    ctx.session_id = "integ-session"
    ctx.redis_client = AsyncMock()
    ctx.stream = AsyncMock()
    return ctx


def _make_config() -> dict:
    """Build a LangGraph config dict with a mock PipelineContext."""
    return {"configurable": {"pipeline_context": _make_mock_pipeline_context()}}


def _intake_external_mocks():
    """Return patch context managers for intake node external dependencies."""
    return [
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
    ]


def _check_worthy_intake_mocks():
    """Intake mocks that produce a check-worthy claim (score > 0.5)."""
    return _intake_external_mocks() + [
        patch(
            "swarm_reasoning.pipeline.nodes.intake.score_claim_text",
            return_value=MagicMock(
                score=0.85,
                rationale="Strong factual claim",
                proceed=True,
                passes=[0.85],
            ),
        ),
        patch(
            "swarm_reasoning.pipeline.nodes.intake.extract_entities_llm",
            return_value=MagicMock(
                persons=["Joe Biden"],
                organizations=["BLS"],
                dates=["January 2024"],
                locations=["United States"],
                statistics=["3.5%"],
            ),
        ),
    ]


def _not_check_worthy_intake_mocks():
    """Intake mocks that produce a not-check-worthy claim (score < 0.5)."""
    return _intake_external_mocks() + [
        patch(
            "swarm_reasoning.pipeline.nodes.intake.score_claim_text",
            return_value=MagicMock(
                score=0.15,
                rationale="Not a verifiable factual claim",
                proceed=False,
                passes=[0.15],
            ),
        ),
    ]


def _downstream_mocks():
    """Mocks for evidence, coverage, and synthesizer external I/O."""
    return [
        # Evidence: block HTTP calls
        patch(
            "swarm_reasoning.pipeline.nodes.evidence.resilient_get",
            new_callable=AsyncMock,
            side_effect=ConnectionError("no network in integration tests"),
        ),
        # Synthesizer: mock LLM narrative generation
        patch.object(
            NarrativeGenerator,
            "generate",
            new_callable=AsyncMock,
            return_value="Based on the available evidence, the claim has been evaluated.",
        ),
    ]


def _newsapi_env():
    """Patch environment to include a NewsAPI key for coverage fan-out."""
    return patch.dict("os.environ", {"NEWSAPI_KEY": "test-integration-key"})


def _no_newsapi_env():
    """Patch environment to remove NewsAPI key (evidence-only fan-out)."""
    return patch.dict("os.environ", {}, clear=True)


def _base_state(run_suffix: str = "1") -> PipelineState:
    """Build a minimal valid pipeline input state."""
    return {
        "claim_text": "The unemployment rate dropped to 3.5% in January 2024",
        "run_id": f"integ-run-{run_suffix}",
        "session_id": f"integ-sess-{run_suffix}",
        "observations": [],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Check-worthy path: full fan-out through all 5 nodes
# ---------------------------------------------------------------------------


class TestCheckWorthyFullPipeline:
    """Exercises the full check-worthy path.

    intake -> [evidence, coverage] -> validation -> synthesizer
    """

    async def _invoke(self, state: PipelineState) -> dict:
        """Run the pipeline through the check-worthy fan-out path."""
        mocks = _check_worthy_intake_mocks() + _downstream_mocks() + [_newsapi_env()]
        with ExitStack() as stack:
            for cm in mocks:
                stack.enter_context(cm)
            return await pipeline_graph.ainvoke(state, _make_config())

    @pytest.mark.asyncio
    async def test_produces_verdict(self):
        """Full pipeline produces a verdict string."""
        result = await self._invoke(_base_state("cw-1"))
        assert "verdict" in result
        assert isinstance(result["verdict"], str)
        assert len(result["verdict"]) > 0

    @pytest.mark.asyncio
    async def test_produces_narrative(self):
        """Full pipeline produces a narrative string."""
        result = await self._invoke(_base_state("cw-2"))
        assert "narrative" in result
        assert isinstance(result["narrative"], str)
        assert len(result["narrative"]) > 0

    @pytest.mark.asyncio
    async def test_produces_confidence(self):
        """Full pipeline produces a confidence score (float or None)."""
        result = await self._invoke(_base_state("cw-3"))
        assert "confidence" in result
        if result["confidence"] is not None:
            assert isinstance(result["confidence"], float)

    @pytest.mark.asyncio
    async def test_verdict_observations_well_structured(self):
        """verdict_observations is a list of dicts with agent, code, value."""
        result = await self._invoke(_base_state("cw-4"))
        assert "verdict_observations" in result
        assert isinstance(result["verdict_observations"], list)
        for obs in result["verdict_observations"]:
            assert "agent" in obs
            assert "code" in obs
            assert "value" in obs

    @pytest.mark.asyncio
    async def test_intake_fields_propagated(self):
        """Intake output fields survive to the final state."""
        result = await self._invoke(_base_state("cw-5"))
        assert result["is_check_worthy"] is True
        assert isinstance(result["normalized_claim"], str)
        assert len(result["normalized_claim"]) > 0
        assert isinstance(result["claim_domain"], str)
        assert isinstance(result["check_worthy_score"], float)
        assert isinstance(result["entities"], dict)

    @pytest.mark.asyncio
    async def test_validation_fields_populated(self):
        """Validation output fields are present in final state."""
        result = await self._invoke(_base_state("cw-6"))
        assert "validated_urls" in result
        assert isinstance(result["validated_urls"], list)
        assert "convergence_score" in result
        assert isinstance(result["convergence_score"], float)
        assert 0.0 <= result["convergence_score"] <= 1.0
        assert "citations" in result
        assert isinstance(result["citations"], list)
        assert "blindspot_score" in result
        assert isinstance(result["blindspot_score"], float)
        assert "blindspot_direction" in result
        assert isinstance(result["blindspot_direction"], str)

    @pytest.mark.asyncio
    async def test_observations_accumulated(self):
        """Observations list grows as nodes execute -- at least one per node."""
        result = await self._invoke(_base_state("cw-7"))
        assert "observations" in result
        assert isinstance(result["observations"], list)
        # Intake alone produces several observations; full pipeline should have many
        assert len(result["observations"]) >= 5

    @pytest.mark.asyncio
    async def test_run_id_preserved(self):
        """run_id from input state survives through the entire pipeline."""
        result = await self._invoke(_base_state("cw-8"))
        assert result["run_id"] == "integ-run-cw-8"

    @pytest.mark.asyncio
    async def test_all_output_fields_present(self):
        """Comprehensive check: all expected output fields present after full pipeline."""
        result = await self._invoke(_base_state("cw-all"))
        expected_fields = [
            # Intake
            "normalized_claim",
            "claim_domain",
            "check_worthy_score",
            "entities",
            "is_check_worthy",
            # Validation
            "validated_urls",
            "convergence_score",
            "citations",
            "blindspot_score",
            "blindspot_direction",
            # Synthesizer
            "verdict",
            "confidence",
            "narrative",
            "verdict_observations",
            # Metadata
            "observations",
            "errors",
        ]
        for field in expected_fields:
            assert field in result, f"Missing output field: {field}"


# ---------------------------------------------------------------------------
# Check-worthy path without NewsAPI (evidence-only, no coverage)
# ---------------------------------------------------------------------------


class TestCheckWorthyNoCoverage:
    """Check-worthy path with no NewsAPI key: evidence only, no coverage node."""

    async def _invoke(self, state: PipelineState) -> dict:
        mocks = _check_worthy_intake_mocks() + _downstream_mocks() + [_no_newsapi_env()]
        with ExitStack() as stack:
            for cm in mocks:
                stack.enter_context(cm)
            return await pipeline_graph.ainvoke(state, _make_config())

    @pytest.mark.asyncio
    async def test_produces_verdict_without_coverage(self):
        """Pipeline produces a verdict even without coverage data."""
        result = await self._invoke(_base_state("nc-1"))
        assert "verdict" in result
        assert isinstance(result["verdict"], str)

    @pytest.mark.asyncio
    async def test_validation_runs_without_coverage(self):
        """Validation node runs and populates fields even without coverage input."""
        result = await self._invoke(_base_state("nc-2"))
        assert "validated_urls" in result
        assert "convergence_score" in result
        assert "blindspot_score" in result

    @pytest.mark.asyncio
    async def test_coverage_fields_absent(self):
        """Coverage output fields should not be in state when coverage was skipped."""
        result = await self._invoke(_base_state("nc-3"))
        assert "coverage_left" not in result
        assert "coverage_center" not in result
        assert "coverage_right" not in result


# ---------------------------------------------------------------------------
# Not-check-worthy path: intake -> synthesizer shortcut
# ---------------------------------------------------------------------------


class TestNotCheckWorthyShortcut:
    """Not-check-worthy path bypasses evidence, coverage, and validation."""

    async def _invoke(self, state: PipelineState) -> dict:
        mocks = _not_check_worthy_intake_mocks()
        with ExitStack() as stack:
            for cm in mocks:
                stack.enter_context(cm)
            return await pipeline_graph.ainvoke(state, _make_config())

    @pytest.mark.asyncio
    async def test_verdict_is_not_check_worthy(self):
        """Shortcut path produces NOT_CHECK_WORTHY verdict."""
        result = await self._invoke(_base_state("ncw-1"))
        assert result["verdict"] == "NOT_CHECK_WORTHY"

    @pytest.mark.asyncio
    async def test_confidence_is_1_0(self):
        """NOT_CHECK_WORTHY verdict has full confidence."""
        result = await self._invoke(_base_state("ncw-2"))
        assert result["confidence"] == 1.0

    @pytest.mark.asyncio
    async def test_narrative_mentions_not_check_worthy(self):
        """Narrative explains the claim was not check-worthy."""
        result = await self._invoke(_base_state("ncw-3"))
        assert "not check-worthy" in result["narrative"].lower()

    @pytest.mark.asyncio
    async def test_skips_validation_fields(self):
        """Validation fields should not be in state when path was shortcut."""
        result = await self._invoke(_base_state("ncw-4"))
        assert "validated_urls" not in result
        assert "convergence_score" not in result

    @pytest.mark.asyncio
    async def test_skips_evidence_fields(self):
        """Evidence fields should not be in state when path was shortcut."""
        result = await self._invoke(_base_state("ncw-5"))
        assert "claimreview_matches" not in result
        assert "domain_sources" not in result

    @pytest.mark.asyncio
    async def test_is_check_worthy_false(self):
        """is_check_worthy flag is False in final state."""
        result = await self._invoke(_base_state("ncw-6"))
        assert result["is_check_worthy"] is False


# ---------------------------------------------------------------------------
# Rejected claim (too short): intake rejects -> synthesizer shortcut
# ---------------------------------------------------------------------------


class TestRejectedClaim:
    """Claims rejected by intake validation (too short, etc.) route to synthesizer."""

    @pytest.mark.asyncio
    async def test_rejected_claim_produces_verdict(self):
        """A claim too short for validation still produces a verdict."""
        state: PipelineState = {
            "claim_text": "Hi",
            "run_id": "integ-rejected-1",
            "session_id": "integ-rejected-sess",
            "observations": [],
            "errors": [],
        }
        result = await pipeline_graph.ainvoke(state, _make_config())
        assert result["is_check_worthy"] is False
        assert "verdict" in result
        assert any("rejected" in e.lower() for e in result["errors"])

    @pytest.mark.asyncio
    async def test_rejected_claim_has_error(self):
        """Rejected claim includes an error message explaining rejection."""
        state: PipelineState = {
            "claim_text": "No",
            "run_id": "integ-rejected-2",
            "session_id": "integ-rejected-sess-2",
            "observations": [],
            "errors": [],
        }
        result = await pipeline_graph.ainvoke(state, _make_config())
        assert len(result["errors"]) > 0


# ---------------------------------------------------------------------------
# Context publishing side-effects
# ---------------------------------------------------------------------------


class TestObservationPublishing:
    """Verify that pipeline nodes publish observations via PipelineContext."""

    @pytest.mark.asyncio
    async def test_check_worthy_publishes_observations(self):
        """Check-worthy path causes publish_observation calls on the context."""
        ctx = _make_mock_pipeline_context()
        config = {"configurable": {"pipeline_context": ctx}}
        state = _base_state("pub-1")

        mocks = _check_worthy_intake_mocks() + _downstream_mocks() + [_newsapi_env()]
        with ExitStack() as stack:
            for cm in mocks:
                stack.enter_context(cm)
            await pipeline_graph.ainvoke(state, config)

        assert ctx.publish_observation.call_count > 0

    @pytest.mark.asyncio
    async def test_check_worthy_publishes_progress(self):
        """Check-worthy path causes publish_progress calls on the context."""
        ctx = _make_mock_pipeline_context()
        config = {"configurable": {"pipeline_context": ctx}}
        state = _base_state("pub-2")

        mocks = _check_worthy_intake_mocks() + _downstream_mocks() + [_newsapi_env()]
        with ExitStack() as stack:
            for cm in mocks:
                stack.enter_context(cm)
            await pipeline_graph.ainvoke(state, config)

        assert ctx.publish_progress.call_count > 0

    @pytest.mark.asyncio
    async def test_heartbeat_called_during_execution(self):
        """Nodes call heartbeat on the context during execution."""
        ctx = _make_mock_pipeline_context()
        config = {"configurable": {"pipeline_context": ctx}}
        state = _base_state("pub-3")

        mocks = _check_worthy_intake_mocks() + _downstream_mocks() + [_newsapi_env()]
        with ExitStack() as stack:
            for cm in mocks:
                stack.enter_context(cm)
            await pipeline_graph.ainvoke(state, config)

        assert ctx.heartbeat.call_count > 0


# ---------------------------------------------------------------------------
# Per-stage PipelineState verification via streaming (M7.4)
# ---------------------------------------------------------------------------


def _collect_observation_codes(ctx: MagicMock) -> list[str]:
    """Extract observation code values from all publish_observation calls."""
    codes: list[str] = []
    for call in ctx.publish_observation.call_args_list:
        code = call.kwargs.get("code") or (call.args[1] if len(call.args) > 1 else None)
        if code is not None:
            codes.append(code.value if hasattr(code, "value") else str(code))
    return codes


class TestPerStageState:
    """Verify correct PipelineState at each pipeline stage via streaming.

    Uses astream(stream_mode='updates') to capture per-node state updates
    and verify the expected fields appear after each stage.
    """

    async def _stream_updates(self, state: PipelineState) -> dict[str, dict]:
        """Run the pipeline with streaming and collect per-node state updates."""
        mocks = _check_worthy_intake_mocks() + _downstream_mocks() + [_newsapi_env()]
        updates: dict[str, dict] = {}
        with ExitStack() as stack:
            for cm in mocks:
                stack.enter_context(cm)
            async for chunk in pipeline_graph.astream(state, _make_config(), stream_mode="updates"):
                for node_name, node_update in chunk.items():
                    updates[node_name] = node_update
        return updates

    @pytest.mark.asyncio
    async def test_intake_stage_populates_required_fields(self):
        """After intake node, state contains normalized_claim, domain, score, entities."""
        updates = await self._stream_updates(_base_state("stage-1"))
        intake = updates["intake"]
        assert isinstance(intake["normalized_claim"], str)
        assert len(intake["normalized_claim"]) > 0
        assert isinstance(intake["claim_domain"], str)
        assert isinstance(intake["check_worthy_score"], float)
        assert intake["check_worthy_score"] > 0.5  # check-worthy path
        assert isinstance(intake["entities"], dict)
        assert intake["is_check_worthy"] is True

    @pytest.mark.asyncio
    async def test_evidence_stage_populates_required_fields(self):
        """After evidence node, state contains claimreview_matches and evidence_confidence."""
        updates = await self._stream_updates(_base_state("stage-2"))
        assert "evidence" in updates
        evidence = updates["evidence"]
        assert "claimreview_matches" in evidence
        assert isinstance(evidence["claimreview_matches"], list)
        assert "evidence_confidence" in evidence

    @pytest.mark.asyncio
    async def test_coverage_stage_populates_required_fields(self):
        """After coverage node, state contains per-spectrum results and framing analysis."""
        updates = await self._stream_updates(_base_state("stage-3"))
        assert "coverage" in updates
        coverage = updates["coverage"]
        assert "coverage_left" in coverage
        assert "coverage_center" in coverage
        assert "coverage_right" in coverage
        assert isinstance(coverage["coverage_left"], list)
        assert isinstance(coverage["coverage_center"], list)
        assert isinstance(coverage["coverage_right"], list)
        assert "framing_analysis" in coverage
        assert isinstance(coverage["framing_analysis"], dict)

    @pytest.mark.asyncio
    async def test_validation_stage_populates_required_fields(self):
        """After validation node, state contains URL validation, convergence, and blindspot data."""
        updates = await self._stream_updates(_base_state("stage-4"))
        assert "validation" in updates
        validation = updates["validation"]
        assert "validated_urls" in validation
        assert isinstance(validation["validated_urls"], list)
        assert "convergence_score" in validation
        assert isinstance(validation["convergence_score"], float)
        assert 0.0 <= validation["convergence_score"] <= 1.0
        assert "citations" in validation
        assert isinstance(validation["citations"], list)
        assert "blindspot_score" in validation
        assert isinstance(validation["blindspot_score"], float)
        assert "blindspot_direction" in validation
        assert isinstance(validation["blindspot_direction"], str)

    @pytest.mark.asyncio
    async def test_synthesizer_stage_populates_required_fields(self):
        """After synthesizer node, state contains verdict, confidence, and narrative."""
        updates = await self._stream_updates(_base_state("stage-5"))
        assert "synthesizer" in updates
        synth = updates["synthesizer"]
        assert "verdict" in synth
        assert isinstance(synth["verdict"], str)
        assert len(synth["verdict"]) > 0
        assert "confidence" in synth
        assert "narrative" in synth
        assert isinstance(synth["narrative"], str)
        assert "verdict_observations" in synth
        assert isinstance(synth["verdict_observations"], list)

    @pytest.mark.asyncio
    async def test_all_five_nodes_execute(self):
        """Full check-worthy pipeline streams updates from all 5 nodes."""
        updates = await self._stream_updates(_base_state("stage-all"))
        expected_nodes = {"intake", "evidence", "coverage", "validation", "synthesizer"}
        assert expected_nodes == set(updates.keys())

    @pytest.mark.asyncio
    async def test_not_check_worthy_skips_middle_nodes(self):
        """Not-check-worthy path streams only intake and synthesizer updates."""
        mocks = _not_check_worthy_intake_mocks()
        updates: dict[str, dict] = {}
        with ExitStack() as stack:
            for cm in mocks:
                stack.enter_context(cm)
            async for chunk in pipeline_graph.astream(
                _base_state("stage-ncw"), _make_config(), stream_mode="updates"
            ):
                for node_name, node_update in chunk.items():
                    updates[node_name] = node_update

        assert "intake" in updates
        assert "synthesizer" in updates
        assert "evidence" not in updates
        assert "coverage" not in updates
        assert "validation" not in updates


# ---------------------------------------------------------------------------
# Observation code publishing verification (M7.4)
# ---------------------------------------------------------------------------


class TestObservationCodesByNode:
    """Verify that specific observation codes are published by each pipeline node."""

    @pytest.mark.asyncio
    async def test_intake_publishes_expected_codes(self):
        """Intake node publishes CLAIM_TEXT, CLAIM_SOURCE_URL, CLAIM_DOMAIN,
        CLAIM_NORMALIZED, CHECK_WORTHY_SCORE, and ENTITY_* codes."""
        ctx = _make_mock_pipeline_context()
        config = {"configurable": {"pipeline_context": ctx}}
        state = _base_state("obs-intake")

        mocks = _check_worthy_intake_mocks() + _downstream_mocks() + [_newsapi_env()]
        with ExitStack() as stack:
            for cm in mocks:
                stack.enter_context(cm)
            await pipeline_graph.ainvoke(state, config)

        codes = _collect_observation_codes(ctx)
        # Intake must publish these core observation codes
        assert "CLAIM_TEXT" in codes
        assert "CLAIM_DOMAIN" in codes
        assert "CLAIM_NORMALIZED" in codes
        assert "CHECK_WORTHY_SCORE" in codes

    @pytest.mark.asyncio
    async def test_intake_publishes_entity_codes(self):
        """Intake node publishes entity observation codes for extracted entities."""
        ctx = _make_mock_pipeline_context()
        config = {"configurable": {"pipeline_context": ctx}}
        state = _base_state("obs-entity")

        mocks = _check_worthy_intake_mocks() + _downstream_mocks() + [_newsapi_env()]
        with ExitStack() as stack:
            for cm in mocks:
                stack.enter_context(cm)
            await pipeline_graph.ainvoke(state, config)

        codes = _collect_observation_codes(ctx)
        # Entity extraction publishes codes for each entity type
        assert "ENTITY_PERSON" in codes
        assert "ENTITY_ORG" in codes
        assert "ENTITY_DATE" in codes
        assert "ENTITY_LOCATION" in codes
        assert "ENTITY_STATISTIC" in codes

    @pytest.mark.asyncio
    async def test_evidence_publishes_expected_codes(self):
        """Evidence node publishes CLAIMREVIEW_MATCH and related codes."""
        ctx = _make_mock_pipeline_context()
        config = {"configurable": {"pipeline_context": ctx}}
        state = _base_state("obs-ev")

        mocks = _check_worthy_intake_mocks() + _downstream_mocks() + [_newsapi_env()]
        with ExitStack() as stack:
            for cm in mocks:
                stack.enter_context(cm)
            await pipeline_graph.ainvoke(state, config)

        codes = _collect_observation_codes(ctx)
        assert "CLAIMREVIEW_MATCH" in codes

    @pytest.mark.asyncio
    async def test_validation_publishes_expected_codes(self):
        """Validation node publishes convergence, blindspot, and citation codes."""
        ctx = _make_mock_pipeline_context()
        config = {"configurable": {"pipeline_context": ctx}}
        state = _base_state("obs-val")

        mocks = _check_worthy_intake_mocks() + _downstream_mocks() + [_newsapi_env()]
        with ExitStack() as stack:
            for cm in mocks:
                stack.enter_context(cm)
            await pipeline_graph.ainvoke(state, config)

        codes = _collect_observation_codes(ctx)
        assert "SOURCE_CONVERGENCE_SCORE" in codes
        assert "BLINDSPOT_SCORE" in codes
        assert "BLINDSPOT_DIRECTION" in codes
        assert "CROSS_SPECTRUM_CORROBORATION" in codes

    @pytest.mark.asyncio
    async def test_synthesizer_publishes_expected_codes(self):
        """Synthesizer node publishes VERDICT, VERDICT_NARRATIVE, and SYNTHESIS_SIGNAL_COUNT.

        CONFIDENCE_SCORE is only published when the scorer returns a non-None value,
        so it is not asserted here (it depends on evidence quality).
        """
        ctx = _make_mock_pipeline_context()
        config = {"configurable": {"pipeline_context": ctx}}
        state = _base_state("obs-synth")

        mocks = _check_worthy_intake_mocks() + _downstream_mocks() + [_newsapi_env()]
        with ExitStack() as stack:
            for cm in mocks:
                stack.enter_context(cm)
            await pipeline_graph.ainvoke(state, config)

        codes = _collect_observation_codes(ctx)
        assert "VERDICT" in codes
        assert "VERDICT_NARRATIVE" in codes
        assert "SYNTHESIS_SIGNAL_COUNT" in codes

    @pytest.mark.asyncio
    async def test_observation_count_full_pipeline(self):
        """Full check-worthy pipeline publishes a substantial number of observations."""
        ctx = _make_mock_pipeline_context()
        config = {"configurable": {"pipeline_context": ctx}}
        state = _base_state("obs-count")

        mocks = _check_worthy_intake_mocks() + _downstream_mocks() + [_newsapi_env()]
        with ExitStack() as stack:
            for cm in mocks:
                stack.enter_context(cm)
            await pipeline_graph.ainvoke(state, config)

        # Each node publishes multiple observations; full pipeline should have many
        # Intake: ~10+, Evidence: ~2+, Coverage: ~6+, Validation: ~4+, Synthesizer: ~5+
        assert ctx.publish_observation.call_count >= 15

    @pytest.mark.asyncio
    async def test_progress_events_from_multiple_agents(self):
        """Progress events are published by agents across all pipeline nodes."""
        ctx = _make_mock_pipeline_context()
        config = {"configurable": {"pipeline_context": ctx}}
        state = _base_state("obs-prog")

        mocks = _check_worthy_intake_mocks() + _downstream_mocks() + [_newsapi_env()]
        with ExitStack() as stack:
            for cm in mocks:
                stack.enter_context(cm)
            await pipeline_graph.ainvoke(state, config)

        # Collect unique agent names from publish_progress calls
        agents = set()
        for call in ctx.publish_progress.call_args_list:
            agent = call.args[0] if call.args else call.kwargs.get("agent")
            if agent:
                agents.add(agent)

        # At least intake, evidence, validation, and synthesizer publish progress
        assert len(agents) >= 4
