"""Tests for intake pipeline node (M1.1).

Tests cover:
- Full happy path: validate → classify → normalize → score → extract
- Validation rejection (short claim, duplicate)
- Not-check-worthy gate (score below threshold)
- Domain classification fallback to OTHER
- Entity extraction with empty results
- Observation publishing side-effects
- Heartbeat calls during execution
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.pipeline.context import PipelineContext
from swarm_reasoning.pipeline.nodes.intake import (
    AGENT_NAME,
    _classify_domain,
    _extract_entities,
    _ingest_claim,
    _normalize_claim,
    _score_check_worthiness,
    intake_node,
)
from swarm_reasoning.pipeline.state import PipelineState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ctx():
    """Create a mock PipelineContext with tracking for published observations."""
    ctx = MagicMock(spec=PipelineContext)
    ctx.run_id = "run-test"
    ctx.session_id = "sess-test"
    ctx.redis_client = AsyncMock()
    ctx.publish_observation = AsyncMock()
    ctx.publish_progress = AsyncMock()
    ctx.heartbeat = MagicMock()
    return ctx


@pytest.fixture
def mock_config(mock_ctx):
    """Create a mock RunnableConfig with PipelineContext."""
    return {"configurable": {"pipeline_context": mock_ctx}}


@pytest.fixture
def base_state() -> PipelineState:
    """Minimal valid PipelineState for intake testing."""
    return {
        "claim_text": "The unemployment rate dropped to 3.5% in 2024",
        "claim_url": None,
        "submission_date": None,
        "run_id": "run-test",
        "session_id": "sess-test",
        "observations": [],
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Tool 1: _ingest_claim
# ---------------------------------------------------------------------------


class TestIngestClaim:
    """Tests for the claim validation tool."""

    @pytest.mark.asyncio
    async def test_accepts_valid_claim(self, mock_ctx):
        accepted, reason, _ = await _ingest_claim(
            mock_ctx, "A valid claim about something important", None, None,
        )
        assert accepted is True
        assert reason is None
        # Should publish 3 observations: CLAIM_TEXT, CLAIM_SOURCE_URL, CLAIM_SOURCE_DATE
        assert mock_ctx.publish_observation.call_count == 3

    @pytest.mark.asyncio
    async def test_rejects_empty_claim(self, mock_ctx):
        accepted, reason, _ = await _ingest_claim(mock_ctx, "", None, None)
        assert accepted is False
        assert reason == "CLAIM_TEXT_EMPTY"
        # Should publish 1 observation with X status
        assert mock_ctx.publish_observation.call_count == 1
        call_kwargs = mock_ctx.publish_observation.call_args.kwargs
        assert call_kwargs["status"] == "X"

    @pytest.mark.asyncio
    async def test_rejects_short_claim(self, mock_ctx):
        accepted, reason, _ = await _ingest_claim(mock_ctx, "Hi", None, None)
        assert accepted is False
        assert reason == "CLAIM_TEXT_TOO_SHORT"

    @pytest.mark.asyncio
    async def test_rejects_invalid_url(self, mock_ctx):
        accepted, reason, _ = await _ingest_claim(
            mock_ctx, "A valid claim text here", "not-a-url", None,
        )
        assert accepted is False
        assert reason == "SOURCE_URL_INVALID_FORMAT"

    @pytest.mark.asyncio
    async def test_normalizes_date(self, mock_ctx):
        accepted, _, normalized_date = await _ingest_claim(
            mock_ctx, "A valid claim text here", None, "2024-01-15",
        )
        assert accepted is True
        assert normalized_date == "20240115"

    @pytest.mark.asyncio
    async def test_publishes_progress_on_accept(self, mock_ctx):
        await _ingest_claim(mock_ctx, "A valid claim text here", None, None)
        progress_calls = [
            call.args[1] for call in mock_ctx.publish_progress.call_args_list
        ]
        assert any("Validating" in msg for msg in progress_calls)
        assert any("accepted" in msg for msg in progress_calls)

    @pytest.mark.asyncio
    async def test_duplicate_check(self, mock_ctx):
        # Simulate duplicate: redis SET NX returns None
        mock_ctx.redis_client.set = AsyncMock(return_value=None)
        accepted, reason, _ = await _ingest_claim(
            mock_ctx, "A valid claim text here", None, None,
        )
        assert accepted is False
        assert reason == "DUPLICATE_CLAIM_IN_RUN"


# ---------------------------------------------------------------------------
# Tool 2: _classify_domain
# ---------------------------------------------------------------------------


class TestClassifyDomain:
    """Tests for the domain classification tool."""

    @pytest.mark.asyncio
    async def test_classifies_known_domain(self, mock_ctx):
        mock_client = AsyncMock()
        with patch(
            "swarm_reasoning.pipeline.nodes.intake.call_claude",
            return_value="HEALTHCARE",
        ):
            domain = await _classify_domain(mock_ctx, "Vaccines prevent disease", mock_client)
        assert domain == "HEALTHCARE"
        # Should publish P then F observation
        assert mock_ctx.publish_observation.call_count == 2

    @pytest.mark.asyncio
    async def test_falls_back_to_other(self, mock_ctx):
        mock_client = AsyncMock()
        with patch(
            "swarm_reasoning.pipeline.nodes.intake.call_claude",
            return_value="INVALID_DOMAIN",
        ):
            domain = await _classify_domain(mock_ctx, "Some claim", mock_client)
        assert domain == "OTHER"
        # Should publish 1 observation with fallback note
        assert mock_ctx.publish_observation.call_count == 1
        call_kwargs = mock_ctx.publish_observation.call_args.kwargs
        assert "fallback" in call_kwargs["note"]


# ---------------------------------------------------------------------------
# Tool 3: _normalize_claim
# ---------------------------------------------------------------------------


class TestNormalizeClaim:
    """Tests for the claim normalization tool."""

    @pytest.mark.asyncio
    async def test_normalizes_text(self, mock_ctx):
        result = await _normalize_claim(mock_ctx, "REPORTEDLY the rate dropped")
        assert result == "the rate dropped"
        assert mock_ctx.publish_observation.call_count == 1

    @pytest.mark.asyncio
    async def test_preserves_simple_text(self, mock_ctx):
        result = await _normalize_claim(mock_ctx, "The rate dropped to 3.5%")
        assert "the rate dropped to 3.5%" == result


# ---------------------------------------------------------------------------
# Tool 4: _score_check_worthiness
# ---------------------------------------------------------------------------


class TestScoreCheckWorthiness:
    """Tests for the check-worthiness scoring tool."""

    @pytest.mark.asyncio
    async def test_check_worthy_claim(self, mock_ctx):
        mock_client = AsyncMock()
        with patch(
            "swarm_reasoning.pipeline.nodes.intake.score_claim_text",
        ) as mock_score:
            mock_score.return_value = MagicMock(
                score=0.8, rationale="Factual claim", proceed=True, passes=[0.8],
            )
            score, proceed = await _score_check_worthiness(
                mock_ctx, "the rate dropped to 3.5%", mock_client,
            )
        assert score == 0.8
        assert proceed is True
        # Should publish P (pass-1) and F (final) observations
        assert mock_ctx.publish_observation.call_count == 2

    @pytest.mark.asyncio
    async def test_not_check_worthy_claim(self, mock_ctx):
        mock_client = AsyncMock()
        with patch(
            "swarm_reasoning.pipeline.nodes.intake.score_claim_text",
        ) as mock_score:
            mock_score.return_value = MagicMock(
                score=0.2, rationale="Opinion, not factual", proceed=False, passes=[0.2],
            )
            score, proceed = await _score_check_worthiness(
                mock_ctx, "i like pizza", mock_client,
            )
        assert score == 0.2
        assert proceed is False


# ---------------------------------------------------------------------------
# Tool 5: _extract_entities
# ---------------------------------------------------------------------------


class TestExtractEntities:
    """Tests for the entity extraction tool."""

    @pytest.mark.asyncio
    async def test_extracts_entities(self, mock_ctx):
        mock_client = AsyncMock()
        with patch(
            "swarm_reasoning.pipeline.nodes.intake.extract_entities_llm",
        ) as mock_extract:
            mock_extract.return_value = MagicMock(
                persons=["Joe Biden"],
                organizations=["CDC"],
                dates=["20240115"],
                locations=["Washington"],
                statistics=["3.5%"],
            )
            entities = await _extract_entities(
                mock_ctx, "joe biden announced at the cdc", mock_client,
            )
        assert entities["persons"] == ["Joe Biden"]
        assert entities["organizations"] == ["CDC"]
        assert entities["dates"] == ["20240115"]
        assert entities["locations"] == ["Washington"]
        assert entities["statistics"] == ["3.5%"]
        # 5 entities = 5 observations
        assert mock_ctx.publish_observation.call_count == 5

    @pytest.mark.asyncio
    async def test_handles_empty_entities(self, mock_ctx):
        mock_client = AsyncMock()
        with patch(
            "swarm_reasoning.pipeline.nodes.intake.extract_entities_llm",
        ) as mock_extract:
            mock_extract.return_value = MagicMock(
                persons=[], organizations=[], dates=[],
                locations=[], statistics=[],
            )
            entities = await _extract_entities(mock_ctx, "nothing here", mock_client)
        assert all(v == [] for v in entities.values())
        assert mock_ctx.publish_observation.call_count == 0


# ---------------------------------------------------------------------------
# Full node integration tests
# ---------------------------------------------------------------------------


class TestIntakeNode:
    """Integration tests for the full intake_node function."""

    @pytest.mark.asyncio
    async def test_happy_path(self, mock_config, mock_ctx, base_state):
        """Full successful path: validate → classify → normalize → score → extract."""
        with (
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
                return_value="ECONOMICS",
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.intake.score_claim_text",
            ) as mock_score,
            patch(
                "swarm_reasoning.pipeline.nodes.intake.extract_entities_llm",
            ) as mock_extract,
        ):
            mock_score.return_value = MagicMock(
                score=0.85, rationale="Strong factual claim", proceed=True, passes=[0.85],
            )
            mock_extract.return_value = MagicMock(
                persons=[], organizations=[], dates=["2024"],
                locations=[], statistics=["3.5%"],
            )
            result = await intake_node(base_state, mock_config)

        assert result["is_check_worthy"] is True
        assert result["normalized_claim"] is not None
        assert result["claim_domain"] == "ECONOMICS"
        assert result["check_worthy_score"] == 0.85
        assert "dates" in result["entities"]
        assert "statistics" in result["entities"]
        # Heartbeat called multiple times
        assert mock_ctx.heartbeat.call_count >= 5

    @pytest.mark.asyncio
    async def test_rejected_claim(self, mock_config, mock_ctx):
        """Rejected claim returns is_check_worthy=False with error."""
        state: PipelineState = {
            "claim_text": "Hi",
            "run_id": "run-rej",
            "session_id": "sess-rej",
            "observations": [],
            "errors": [],
        }
        result = await intake_node(state, mock_config)
        assert result["is_check_worthy"] is False
        assert len(result["errors"]) == 1
        assert "CLAIM_TEXT_TOO_SHORT" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_not_check_worthy_skips_entities(self, mock_config, mock_ctx, base_state):
        """Not-check-worthy claims skip entity extraction."""
        with (
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
                return_value="OTHER",
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.intake.score_claim_text",
            ) as mock_score,
            patch(
                "swarm_reasoning.pipeline.nodes.intake.extract_entities_llm",
            ) as mock_extract,
        ):
            mock_score.return_value = MagicMock(
                score=0.1, rationale="Not factual", proceed=False, passes=[0.1],
            )
            result = await intake_node(base_state, mock_config)

        assert result["is_check_worthy"] is False
        assert result["check_worthy_score"] == 0.1
        assert "entities" not in result
        # extract_entities_llm should NOT have been called
        mock_extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_agent_name_is_intake(self, mock_config, mock_ctx, base_state):
        """All observations should use 'intake' as the agent name."""
        with (
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
                return_value="SCIENCE",
            ),
            patch(
                "swarm_reasoning.pipeline.nodes.intake.score_claim_text",
            ) as mock_score,
            patch(
                "swarm_reasoning.pipeline.nodes.intake.extract_entities_llm",
            ) as mock_extract,
        ):
            mock_score.return_value = MagicMock(
                score=0.9, rationale="Factual", proceed=True, passes=[0.9],
            )
            mock_extract.return_value = MagicMock(
                persons=[], organizations=[], dates=[],
                locations=[], statistics=[],
            )
            await intake_node(base_state, mock_config)

        for call in mock_ctx.publish_observation.call_args_list:
            assert call.kwargs["agent"] == "intake"
