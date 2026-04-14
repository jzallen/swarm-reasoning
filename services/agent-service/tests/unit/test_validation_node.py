"""Tests for validation pipeline node (M4.1).

Tests the 5-tool procedural chain: extract → validate → convergence →
aggregate → blindspots. Uses mock PipelineContext to avoid Redis/network.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.source_validator.models import (
    ValidationResult,
    ValidationStatus,
)
from swarm_reasoning.models.observation import ObservationCode
from swarm_reasoning.pipeline.context import PipelineContext
from swarm_reasoning.pipeline.nodes.validation import (
    _build_coverage_snapshot,
    _build_cross_agent_data,
    validation_node,
)
from swarm_reasoning.pipeline.state import PipelineState


def _make_mock_ctx() -> PipelineContext:
    ctx = MagicMock(spec=PipelineContext)
    ctx.publish_observation = AsyncMock()
    ctx.publish_progress = AsyncMock()
    ctx.heartbeat = MagicMock()
    ctx.next_seq = MagicMock(return_value=1)
    return ctx


def _make_config(ctx: PipelineContext | None = None) -> dict:
    if ctx is None:
        ctx = _make_mock_ctx()
    return {"configurable": {"pipeline_context": ctx}}


def _make_state(**overrides) -> PipelineState:
    base: PipelineState = {
        "claim_text": "Test claim",
        "run_id": "run-test",
        "session_id": "sess-test",
        "observations": [],
        "errors": [],
    }
    base.update(overrides)
    return base


class TestBuildCrossAgentData:
    """Test _build_cross_agent_data extracts URLs from PipelineState."""

    def test_empty_state(self):
        state = _make_state()
        data = _build_cross_agent_data(state)
        assert data == {"urls": []}

    def test_claimreview_matches(self):
        state = _make_state(claimreview_matches=[
            {"url": "https://example.com/fact-check", "publisher": "PolitiFact"},
        ])
        data = _build_cross_agent_data(state)
        assert len(data["urls"]) == 1
        assert data["urls"][0]["url"] == "https://example.com/fact-check"
        assert data["urls"][0]["agent"] == "evidence"

    def test_domain_sources(self):
        state = _make_state(domain_sources=[
            {"url": "https://cdc.gov/data", "name": "CDC"},
        ])
        data = _build_cross_agent_data(state)
        assert len(data["urls"]) == 1
        assert data["urls"][0]["url"] == "https://cdc.gov/data"
        assert data["urls"][0]["source_name"] == "CDC"

    def test_coverage_segments(self):
        state = _make_state(
            coverage_left=[{"url": "https://left.com/a", "source": "LeftNews"}],
            coverage_center=[{"url": "https://center.com/a", "source": "CenterNews"}],
            coverage_right=[{"url": "https://right.com/a", "source": "RightNews"}],
        )
        data = _build_cross_agent_data(state)
        assert len(data["urls"]) == 3
        agents = {u["agent"] for u in data["urls"]}
        assert agents == {"coverage-left", "coverage-center", "coverage-right"}

    def test_entries_without_urls_skipped(self):
        state = _make_state(
            claimreview_matches=[{"publisher": "NoUrl"}],
            domain_sources=[{"name": "NoUrl"}],
        )
        data = _build_cross_agent_data(state)
        assert data == {"urls": []}


class TestBuildCoverageSnapshot:
    """Test _build_coverage_snapshot builds CoverageSnapshot from state."""

    def test_empty_coverage(self):
        state = _make_state()
        snapshot = _build_coverage_snapshot(state, None)
        assert snapshot.left.article_count == 0
        assert snapshot.left.framing == "ABSENT"
        assert snapshot.center.article_count == 0
        assert snapshot.right.article_count == 0
        assert snapshot.source_convergence_score is None

    def test_full_coverage(self):
        state = _make_state(
            coverage_left=[{"framing": "SUPPORTIVE"}],
            coverage_center=[{"framing": "NEUTRAL"}, {"framing": "NEUTRAL"}],
            coverage_right=[{"framing": "CRITICAL"}],
        )
        snapshot = _build_coverage_snapshot(state, 0.75)
        assert snapshot.left.article_count == 1
        assert snapshot.left.framing == "SUPPORTIVE"
        assert snapshot.center.article_count == 2
        assert snapshot.right.article_count == 1
        assert snapshot.source_convergence_score == 0.75


class TestValidationNode:
    """Integration tests for the full validation_node."""

    @pytest.mark.asyncio
    async def test_empty_state_returns_defaults(self):
        """With no upstream data, validation produces zero-value defaults."""
        ctx = _make_mock_ctx()
        state = _make_state()
        result = await validation_node(state, _make_config(ctx))

        assert result["validated_urls"] == []
        assert result["convergence_score"] == 0.0
        assert result["citations"] == []
        assert result["blindspot_score"] == 1.0  # All 3 segments absent
        assert "MULTIPLE" in result["blindspot_direction"]

    @pytest.mark.asyncio
    async def test_publishes_observations(self):
        """Validation node publishes observations via PipelineContext."""
        ctx = _make_mock_ctx()
        state = _make_state(
            claimreview_matches=[
                {"url": "https://example.com/check", "publisher": "Test"},
            ],
        )

        # Mock UrlValidator to avoid real HTTP
        mock_validations = {
            "https://example.com/check": ValidationResult(
                url="https://example.com/check",
                status=ValidationStatus.LIVE,
            ),
        }
        with patch(
            "swarm_reasoning.pipeline.nodes.validation.UrlValidator"
        ) as MockValidator:
            instance = MockValidator.return_value
            instance.validate_all = AsyncMock(return_value=mock_validations)

            result = await validation_node(state, _make_config(ctx))

        assert len(result["validated_urls"]) == 1
        assert result["validated_urls"][0]["status"] == "LIVE"

        # Check observations were published
        obs_codes = [
            call.kwargs["code"]
            for call in ctx.publish_observation.call_args_list
        ]
        assert ObservationCode.SOURCE_EXTRACTED_URL in obs_codes
        assert ObservationCode.SOURCE_VALIDATION_STATUS in obs_codes
        assert ObservationCode.SOURCE_CONVERGENCE_SCORE in obs_codes
        assert ObservationCode.CITATION_LIST in obs_codes
        assert ObservationCode.BLINDSPOT_SCORE in obs_codes
        assert ObservationCode.BLINDSPOT_DIRECTION in obs_codes
        assert ObservationCode.CROSS_SPECTRUM_CORROBORATION in obs_codes

    @pytest.mark.asyncio
    async def test_heartbeats_during_execution(self):
        """Validation node sends heartbeats between tool steps."""
        ctx = _make_mock_ctx()
        state = _make_state()
        await validation_node(state, _make_config(ctx))

        # 6 heartbeats: initial + after each of 5 tools
        assert ctx.heartbeat.call_count == 6
        for call in ctx.heartbeat.call_args_list:
            assert call.args[0] == "validation"

    @pytest.mark.asyncio
    async def test_partial_coverage_blindspot(self):
        """Missing coverage segments produce non-zero blindspot score."""
        ctx = _make_mock_ctx()
        # Only left coverage present
        state = _make_state(
            coverage_left=[{"url": "https://left.com/a", "source": "L", "framing": "SUPPORTIVE"}],
        )

        with patch(
            "swarm_reasoning.pipeline.nodes.validation.UrlValidator"
        ) as MockValidator:
            instance = MockValidator.return_value
            instance.validate_all = AsyncMock(return_value={
                "https://left.com/a": ValidationResult(
                    url="https://left.com/a", status=ValidationStatus.LIVE,
                ),
            })
            result = await validation_node(state, _make_config(ctx))

        # 2 of 3 segments absent -> score = 2/3 ≈ 0.6667
        assert result["blindspot_score"] == pytest.approx(0.6667, abs=0.001)
        assert "MULTIPLE" in result["blindspot_direction"]

    @pytest.mark.asyncio
    async def test_full_coverage_no_blindspot(self):
        """All 3 coverage segments present -> blindspot score 0."""
        ctx = _make_mock_ctx()
        state = _make_state(
            coverage_left=[{"url": "https://l.com", "source": "L", "framing": "NEUTRAL"}],
            coverage_center=[{"url": "https://c.com", "source": "C", "framing": "NEUTRAL"}],
            coverage_right=[{"url": "https://r.com", "source": "R", "framing": "NEUTRAL"}],
        )

        with patch(
            "swarm_reasoning.pipeline.nodes.validation.UrlValidator"
        ) as MockValidator:
            instance = MockValidator.return_value
            instance.validate_all = AsyncMock(return_value={
                "https://l.com": ValidationResult(url="https://l.com", status=ValidationStatus.LIVE),
                "https://c.com": ValidationResult(url="https://c.com", status=ValidationStatus.LIVE),
                "https://r.com": ValidationResult(url="https://r.com", status=ValidationStatus.LIVE),
            })
            result = await validation_node(state, _make_config(ctx))

        assert result["blindspot_score"] == 0.0
        assert "NONE" in result["blindspot_direction"]

    @pytest.mark.asyncio
    async def test_convergence_with_shared_urls(self):
        """URLs cited by multiple agents produce higher convergence score."""
        ctx = _make_mock_ctx()
        # Same URL from both evidence and coverage
        state = _make_state(
            domain_sources=[{"url": "https://shared.com/fact", "name": "SourceA"}],
            coverage_center=[{"url": "https://shared.com/fact", "source": "SourceB"}],
        )

        with patch(
            "swarm_reasoning.pipeline.nodes.validation.UrlValidator"
        ) as MockValidator:
            instance = MockValidator.return_value
            instance.validate_all = AsyncMock(return_value={
                "https://shared.com/fact": ValidationResult(
                    url="https://shared.com/fact", status=ValidationStatus.LIVE,
                ),
            })
            result = await validation_node(state, _make_config(ctx))

        # 1 unique URL cited by 2 agents -> convergence = 1.0
        assert result["convergence_score"] == 1.0

    @pytest.mark.asyncio
    async def test_progress_messages_published(self):
        """Validation node publishes start and completion progress."""
        ctx = _make_mock_ctx()
        state = _make_state()
        await validation_node(state, _make_config(ctx))

        assert ctx.publish_progress.call_count == 2
        messages = [call.args[1] for call in ctx.publish_progress.call_args_list]
        assert "Starting" in messages[0]
        assert "complete" in messages[1].lower()
