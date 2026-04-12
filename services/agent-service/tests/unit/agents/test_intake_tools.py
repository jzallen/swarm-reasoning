"""Unit tests for intake agent @tool definitions (hq-423.39)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from swarm_reasoning.agents.intake.tools import classify_domain, validate_claim
from swarm_reasoning.agents.ingestion_agent.tools.claim_intake import (
    IngestionResult,
    StreamNotOpenError,
    StreamPublishError,
)
from swarm_reasoning.agents.ingestion_agent.tools.domain_cls import (
    ClassificationResult,
    ClassificationServiceError,
    StreamStateError,
)
from swarm_reasoning.agents.tool_runtime import AgentContext


def _make_context(
    agent_name: str = "ingestion-agent",
    run_id: str = "run-001",
    anthropic_client: object | None = None,
) -> AgentContext:
    """Create an AgentContext with mocked stream and Redis client."""
    stream = AsyncMock()
    stream.publish = AsyncMock()
    stream.read_latest = AsyncMock(return_value=None)
    redis_client = AsyncMock()
    redis_client.xadd = AsyncMock()
    redis_client.set = AsyncMock(return_value=True)

    return AgentContext(
        stream=stream,
        redis_client=redis_client,
        run_id=run_id,
        sk=f"reasoning:{run_id}:{agent_name}",
        agent_name=agent_name,
        anthropic_client=anthropic_client,
    )


class TestValidateClaim:
    @patch("swarm_reasoning.agents.intake.tools._ingest_claim")
    async def test_accepted_claim(self, mock_ingest):
        ctx = _make_context()
        mock_ingest.return_value = IngestionResult(
            accepted=True, run_id="run-001", normalized_date="20260101"
        )

        result = await validate_claim.ainvoke(
            {
                "claim_text": "The sky is blue",
                "context": ctx,
            }
        )

        assert "Claim accepted" in result
        assert "run_id=run-001" in result
        assert "normalized_date=20260101" in result
        mock_ingest.assert_awaited_once_with(
            run_id="run-001",
            claim_text="The sky is blue",
            source_url=None,
            source_date=None,
            stream=ctx.stream,
            redis_client=ctx.redis_client,
        )

    @patch("swarm_reasoning.agents.intake.tools._ingest_claim")
    async def test_accepted_without_date(self, mock_ingest):
        ctx = _make_context()
        mock_ingest.return_value = IngestionResult(
            accepted=True, run_id="run-001"
        )

        result = await validate_claim.ainvoke(
            {"claim_text": "Test claim", "context": ctx}
        )

        assert "Claim accepted" in result
        assert "normalized_date" not in result

    @patch("swarm_reasoning.agents.intake.tools._ingest_claim")
    async def test_rejected_claim(self, mock_ingest):
        ctx = _make_context()
        mock_ingest.return_value = IngestionResult(
            accepted=False,
            run_id="run-001",
            rejection_reason="CLAIM_TEXT_EMPTY",
        )

        result = await validate_claim.ainvoke(
            {"claim_text": "", "context": ctx}
        )

        assert "Claim rejected" in result
        assert "CLAIM_TEXT_EMPTY" in result

    @patch("swarm_reasoning.agents.intake.tools._ingest_claim")
    async def test_passes_source_url_and_date(self, mock_ingest):
        ctx = _make_context()
        mock_ingest.return_value = IngestionResult(
            accepted=True, run_id="run-001", normalized_date="20260401"
        )

        await validate_claim.ainvoke(
            {
                "claim_text": "Test claim",
                "source_url": "https://example.com",
                "source_date": "2026-04-01",
                "context": ctx,
            }
        )

        mock_ingest.assert_awaited_once_with(
            run_id="run-001",
            claim_text="Test claim",
            source_url="https://example.com",
            source_date="2026-04-01",
            stream=ctx.stream,
            redis_client=ctx.redis_client,
        )

    @patch("swarm_reasoning.agents.intake.tools._ingest_claim")
    async def test_stream_not_open_error(self, mock_ingest):
        ctx = _make_context()
        mock_ingest.side_effect = StreamNotOpenError("already has messages")

        result = await validate_claim.ainvoke(
            {"claim_text": "Test", "context": ctx}
        )

        assert "Error: stream already open" in result

    @patch("swarm_reasoning.agents.intake.tools._ingest_claim")
    async def test_stream_publish_error(self, mock_ingest):
        ctx = _make_context()
        mock_ingest.side_effect = StreamPublishError("Redis unavailable")

        result = await validate_claim.ainvoke(
            {"claim_text": "Test", "context": ctx}
        )

        assert "Error: failed to publish" in result


class TestClassifyDomain:
    @patch("swarm_reasoning.agents.intake.tools._classify_domain")
    async def test_high_confidence_classification(self, mock_classify):
        anthropic = AsyncMock()
        ctx = _make_context(anthropic_client=anthropic)
        mock_classify.return_value = ClassificationResult(
            run_id="run-001",
            domain="HEALTHCARE",
            confidence="HIGH",
            attempt_count=1,
        )

        result = await classify_domain.ainvoke(
            {"claim_text": "Vaccines cause autism", "context": ctx}
        )

        assert "Domain: HEALTHCARE" in result
        assert "confidence=HIGH" in result
        assert "attempts=1" in result
        mock_classify.assert_awaited_once_with(
            run_id="run-001",
            claim_text="Vaccines cause autism",
            stream=ctx.stream,
            anthropic_client=anthropic,
            redis_client=ctx.redis_client,
        )

    @patch("swarm_reasoning.agents.intake.tools._classify_domain")
    async def test_low_confidence_fallback(self, mock_classify):
        anthropic = AsyncMock()
        ctx = _make_context(anthropic_client=anthropic)
        mock_classify.return_value = ClassificationResult(
            run_id="run-001",
            domain="OTHER",
            confidence="LOW",
            attempt_count=2,
        )

        result = await classify_domain.ainvoke(
            {"claim_text": "Something vague", "context": ctx}
        )

        assert "Domain: OTHER" in result
        assert "confidence=LOW" in result
        assert "attempts=2" in result

    async def test_no_anthropic_client_returns_error(self):
        ctx = _make_context(anthropic_client=None)

        result = await classify_domain.ainvoke(
            {"claim_text": "Test", "context": ctx}
        )

        assert "Error: no Anthropic client" in result

    @patch("swarm_reasoning.agents.intake.tools._classify_domain")
    async def test_stream_state_error(self, mock_classify):
        anthropic = AsyncMock()
        ctx = _make_context(anthropic_client=anthropic)
        mock_classify.side_effect = StreamStateError("no START message")

        result = await classify_domain.ainvoke(
            {"claim_text": "Test", "context": ctx}
        )

        assert "Error: stream precondition failed" in result

    @patch("swarm_reasoning.agents.intake.tools._classify_domain")
    async def test_classification_service_error(self, mock_classify):
        anthropic = AsyncMock()
        ctx = _make_context(anthropic_client=anthropic)
        mock_classify.side_effect = ClassificationServiceError(
            "Authentication failed", retryable=False
        )

        result = await classify_domain.ainvoke(
            {"claim_text": "Test", "context": ctx}
        )

        assert "Error: classification service" in result
