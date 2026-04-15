"""Unit tests for PipelineState, PipelineContext, and graph topology (M0.1 / M0.2 / M0.3).

Covers:
- PipelineState TypedDict structure and ``add`` reducer annotations
- PipelineContext sequence management, observation publishing, progress
  publishing, heartbeat forwarding, and get_pipeline_context extraction
- Graph topology: edge connections, entry/exit points, node count
"""

from __future__ import annotations

import threading
from operator import add
from typing import get_type_hints
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.pipeline.context import PipelineContext, get_pipeline_context
from swarm_reasoning.pipeline.graph import pipeline_graph
from swarm_reasoning.pipeline.state import PipelineState

# ---------------------------------------------------------------------------
# PipelineState tests
# ---------------------------------------------------------------------------


class TestPipelineState:
    """Verify PipelineState TypedDict structure and reducer annotations."""

    def test_is_typed_dict(self):
        assert issubclass(PipelineState, dict)

    def test_total_false(self):
        """PipelineState uses total=False so all keys are optional."""
        assert PipelineState.__total__ is False

    def test_required_input_fields_present(self):
        """Fields needed at pipeline invocation are declared."""
        hints = get_type_hints(PipelineState, include_extras=True)
        for field in ("claim_text", "run_id", "session_id"):
            assert field in hints, f"Missing required input field: {field}"

    def test_intake_output_fields_present(self):
        hints = get_type_hints(PipelineState, include_extras=True)
        for field in (
            "normalized_claim",
            "claim_domain",
            "check_worthy_score",
            "entities",
            "is_check_worthy",
        ):
            assert field in hints, f"Missing intake output field: {field}"

    def test_evidence_output_fields_present(self):
        hints = get_type_hints(PipelineState, include_extras=True)
        for field in ("claimreview_matches", "domain_sources", "evidence_confidence"):
            assert field in hints, f"Missing evidence output field: {field}"

    def test_coverage_output_fields_present(self):
        hints = get_type_hints(PipelineState, include_extras=True)
        for field in (
            "coverage_left",
            "coverage_center",
            "coverage_right",
            "framing_analysis",
        ):
            assert field in hints, f"Missing coverage output field: {field}"

    def test_validation_output_fields_present(self):
        hints = get_type_hints(PipelineState, include_extras=True)
        for field in (
            "validated_urls",
            "convergence_score",
            "citations",
            "blindspot_score",
            "blindspot_direction",
        ):
            assert field in hints, f"Missing validation output field: {field}"

    def test_synthesizer_output_fields_present(self):
        hints = get_type_hints(PipelineState, include_extras=True)
        for field in ("verdict", "confidence", "narrative", "verdict_observations"):
            assert field in hints, f"Missing synthesizer output field: {field}"

    def test_observations_has_add_reducer(self):
        """observations field uses Annotated[list[dict], add] for parallel append."""
        hints = get_type_hints(PipelineState, include_extras=True)
        obs_hint = hints["observations"]
        assert hasattr(obs_hint, "__metadata__"), "observations should be Annotated"
        assert add in obs_hint.__metadata__

    def test_errors_has_add_reducer(self):
        """errors field uses Annotated[list[str], add] for parallel append."""
        hints = get_type_hints(PipelineState, include_extras=True)
        err_hint = hints["errors"]
        assert hasattr(err_hint, "__metadata__"), "errors should be Annotated"
        assert add in err_hint.__metadata__

    def test_non_reducer_fields_lack_annotation(self):
        """Fields without reducers should not have add metadata."""
        hints = get_type_hints(PipelineState, include_extras=True)
        for field in ("claim_text", "run_id", "verdict", "confidence"):
            hint = hints[field]
            if hasattr(hint, "__metadata__"):
                assert add not in hint.__metadata__, f"{field} should not use add reducer"

    def test_can_construct_minimal_state(self):
        """Minimal state dict is valid (total=False means no required keys)."""
        state: PipelineState = {
            "claim_text": "test claim",
            "run_id": "run-1",
            "session_id": "sess-1",
        }
        assert state["claim_text"] == "test claim"

    def test_can_construct_full_state(self):
        """Full state dict with all fields is valid."""
        state: PipelineState = {
            "claim_text": "test",
            "claim_url": None,
            "submission_date": "2026-01-01",
            "run_id": "r",
            "session_id": "s",
            "normalized_claim": "test",
            "claim_domain": "politics",
            "check_worthy_score": 0.85,
            "entities": {"persons": ["Joe"]},
            "is_check_worthy": True,
            "claimreview_matches": [],
            "domain_sources": [],
            "evidence_confidence": 0.7,
            "coverage_left": [],
            "coverage_center": [],
            "coverage_right": [],
            "framing_analysis": {},
            "validated_urls": [],
            "convergence_score": 0.5,
            "citations": [],
            "blindspot_score": 0.1,
            "blindspot_direction": "left",
            "verdict": "TRUE",
            "confidence": 0.9,
            "narrative": "Test narrative",
            "verdict_observations": [],
            "observations": [],
            "errors": [],
        }
        assert state["verdict"] == "TRUE"
        assert state["confidence"] == 0.9


# ---------------------------------------------------------------------------
# PipelineContext tests
# ---------------------------------------------------------------------------


def _make_context(**overrides) -> PipelineContext:
    """Build a PipelineContext with mock infrastructure handles."""
    defaults = {
        "stream": AsyncMock(),
        "redis_client": AsyncMock(),
        "run_id": "run-test",
        "session_id": "sess-test",
        "heartbeat_callback": MagicMock(),
    }
    defaults.update(overrides)
    return PipelineContext(**defaults)


class TestPipelineContextNextSeq:
    """Verify atomic per-agent sequence counter."""

    def test_first_call_returns_one(self):
        ctx = _make_context()
        assert ctx.next_seq("agent-a") == 1

    def test_increments_per_agent(self):
        ctx = _make_context()
        assert ctx.next_seq("agent-a") == 1
        assert ctx.next_seq("agent-a") == 2
        assert ctx.next_seq("agent-a") == 3

    def test_independent_agents(self):
        ctx = _make_context()
        assert ctx.next_seq("agent-a") == 1
        assert ctx.next_seq("agent-b") == 1
        assert ctx.next_seq("agent-a") == 2
        assert ctx.next_seq("agent-b") == 2

    def test_thread_safety(self):
        """Concurrent next_seq calls from multiple threads produce unique sequences."""
        ctx = _make_context()
        results: list[int] = []
        count = 100

        def bump():
            for _ in range(count):
                results.append(ctx.next_seq("shared-agent"))

        threads = [threading.Thread(target=bump) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 400
        assert sorted(results) == list(range(1, 401))


class TestPipelineContextPublishObservation:
    """Verify observation publishing via the ReasoningStream."""

    @pytest.mark.asyncio
    async def test_publishes_to_stream(self):
        ctx = _make_context()
        seq = await ctx.publish_observation(
            agent="intake",
            code=ObservationCode.CLAIM_TEXT,
            value="test claim",
            value_type=ValueType.ST,
        )
        assert seq == 1
        ctx.stream.publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stream_key_format(self):
        ctx = _make_context(run_id="run-42")
        await ctx.publish_observation(
            agent="evidence",
            code=ObservationCode.DOMAIN_CONFIDENCE,
            value="0.8",
            value_type=ValueType.NM,
        )
        call_args = ctx.stream.publish.await_args
        assert call_args[0][0] == "reasoning:run-42:evidence"

    @pytest.mark.asyncio
    async def test_increments_sequence_per_agent(self):
        ctx = _make_context()
        seq1 = await ctx.publish_observation(
            agent="intake",
            code=ObservationCode.CLAIM_TEXT,
            value="first",
            value_type=ValueType.ST,
        )
        seq2 = await ctx.publish_observation(
            agent="intake",
            code=ObservationCode.CLAIM_DOMAIN,
            value="politics",
            value_type=ValueType.ST,
        )
        assert seq1 == 1
        assert seq2 == 2

    @pytest.mark.asyncio
    async def test_different_agents_get_independent_sequences(self):
        ctx = _make_context()
        seq_a = await ctx.publish_observation(
            agent="intake",
            code=ObservationCode.CLAIM_TEXT,
            value="v",
            value_type=ValueType.ST,
        )
        seq_b = await ctx.publish_observation(
            agent="evidence",
            code=ObservationCode.DOMAIN_CONFIDENCE,
            value="0.5",
            value_type=ValueType.NM,
        )
        assert seq_a == 1
        assert seq_b == 1

    @pytest.mark.asyncio
    async def test_observation_message_structure(self):
        """Published ObsMessage wraps an Observation with correct fields."""
        ctx = _make_context(run_id="run-x")
        await ctx.publish_observation(
            agent="intake",
            code=ObservationCode.CLAIM_TEXT,
            value="hello",
            value_type=ValueType.ST,
            status="F",
            method="manual",
            note="test note",
        )
        msg = ctx.stream.publish.await_args[0][1]
        obs = msg.observation
        assert obs.run_id == "run-x"
        assert obs.agent == "intake"
        assert obs.code == ObservationCode.CLAIM_TEXT
        assert obs.value == "hello"
        assert obs.value_type == ValueType.ST
        assert obs.status == "F"
        assert obs.method == "manual"
        assert obs.note == "test note"
        assert obs.seq == 1

    @pytest.mark.asyncio
    async def test_optional_fields_default_to_none(self):
        ctx = _make_context()
        await ctx.publish_observation(
            agent="intake",
            code=ObservationCode.CLAIM_TEXT,
            value="v",
            value_type=ValueType.ST,
        )
        msg = ctx.stream.publish.await_args[0][1]
        obs = msg.observation
        assert obs.method is None
        assert obs.note is None
        assert obs.units is None
        assert obs.reference_range is None


class TestPipelineContextPublishProgress:
    """Verify progress event publishing to Redis."""

    @pytest.mark.asyncio
    async def test_publishes_to_progress_stream(self):
        ctx = _make_context(run_id="run-prog")
        await ctx.publish_progress("intake", "Processing claim")
        ctx.redis_client.xadd.assert_awaited_once()
        call_args = ctx.redis_client.xadd.await_args
        assert call_args[0][0] == "progress:run-prog"
        payload = call_args[0][1]
        assert payload["agent"] == "intake"
        assert payload["message"] == "Processing claim"
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_suppresses_redis_errors(self):
        """publish_progress should not raise even if Redis fails."""
        redis_mock = AsyncMock()
        redis_mock.xadd.side_effect = ConnectionError("Redis down")
        ctx = _make_context(redis_client=redis_mock)
        # Should not raise
        await ctx.publish_progress("intake", "msg")


class TestPipelineContextHeartbeat:
    """Verify heartbeat forwarding to Temporal."""

    def test_forwards_to_callback(self):
        cb = MagicMock()
        ctx = _make_context(heartbeat_callback=cb)
        ctx.heartbeat("intake")
        cb.assert_called_once_with("intake")

    def test_multiple_heartbeats(self):
        cb = MagicMock()
        ctx = _make_context(heartbeat_callback=cb)
        ctx.heartbeat("intake")
        ctx.heartbeat("evidence")
        ctx.heartbeat("intake")
        assert cb.call_count == 3
        cb.assert_has_calls([call("intake"), call("evidence"), call("intake")])


class TestGetPipelineContext:
    """Verify get_pipeline_context extracts context from RunnableConfig."""

    def test_extracts_from_valid_config(self):
        ctx = _make_context()
        config = {"configurable": {"pipeline_context": ctx}}
        assert get_pipeline_context(config) is ctx

    def test_raises_key_error_when_missing(self):
        with pytest.raises(KeyError):
            get_pipeline_context({"configurable": {}})

    def test_raises_key_error_when_no_configurable(self):
        with pytest.raises(KeyError):
            get_pipeline_context({})


# ---------------------------------------------------------------------------
# Graph topology tests (supplements TestGraphStructure in test_pipeline_graph.py)
# ---------------------------------------------------------------------------


class TestGraphTopology:
    """Verify graph edge connections and structural invariants.

    Uses ``pipeline_graph.builder.edges`` (set of (source, target) tuples)
    for full edge inspection since the compiled graph's ``get_graph().edges``
    only exposes a simplified view that omits conditional and Send-based edges.
    """

    def _edges(self):
        return pipeline_graph.builder.edges

    def test_entry_point_is_intake(self):
        """Graph entry point is __start__ -> intake."""
        assert ("__start__", "intake") in self._edges()

    def test_synthesizer_connects_to_end(self):
        """synthesizer -> __end__ edge exists."""
        assert ("synthesizer", "__end__") in self._edges()

    def test_evidence_routes_to_validation(self):
        assert ("evidence", "validation") in self._edges()

    def test_coverage_routes_to_validation(self):
        assert ("coverage", "validation") in self._edges()

    def test_validation_routes_to_synthesizer(self):
        assert ("validation", "synthesizer") in self._edges()

    def test_node_count(self):
        """5 domain nodes present in the builder."""
        nodes = set(pipeline_graph.builder.nodes.keys())
        expected = {"intake", "evidence", "coverage", "validation", "synthesizer"}
        assert expected == nodes

    def test_graph_has_all_nodes_in_compiled_view(self):
        """Compiled graph has 5 domain nodes + __start__ + __end__ = 7 total."""
        g = pipeline_graph.get_graph()
        assert len(g.nodes) == 7

    def test_no_direct_edge_from_intake_to_validation(self):
        """intake uses conditional edges (route_after_intake), not a direct edge."""
        assert ("intake", "validation") not in self._edges()

    def test_no_direct_edge_from_intake_to_evidence(self):
        """intake fans out via Send, not a static edge to evidence."""
        assert ("intake", "evidence") not in self._edges()

    def test_no_cycles_in_sequential_tail(self):
        """validation -> synthesizer -> END has no back-edges."""
        synth_targets = {t for s, t in self._edges() if s == "synthesizer"}
        assert synth_targets == {"__end__"}
        val_targets = {t for s, t in self._edges() if s == "validation"}
        assert "validation" not in val_targets

    def test_edge_count(self):
        """Exactly 5 static edges in the builder (conditional edges excluded)."""
        assert len(self._edges()) == 5

    def test_compiled_graph_is_reusable(self):
        """Module-level pipeline_graph can be used for multiple invocations."""
        g1 = pipeline_graph.get_graph()
        g2 = pipeline_graph.get_graph()
        assert set(g1.nodes) == set(g2.nodes)
