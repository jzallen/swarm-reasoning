"""Unit tests for coverage agent @tool definitions."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.coverage_core_tools import (
    build_coverage_query,
    detect_coverage_framing,
    find_top_coverage_source,
    search_coverage,
)
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType


def _make_context() -> AgentContext:
    """Build a mock AgentContext for tool testing."""
    stream = AsyncMock()
    redis_client = AsyncMock()
    ctx = AgentContext(
        stream=stream,
        redis_client=redis_client,
        run_id="run-test-001",
        sk="reasoning:run-test-001:coverage-left",
        agent_name="coverage-left",
    )
    ctx.publish_obs = AsyncMock()
    return ctx


class TestBuildCoverageQuery:
    def test_basic_claim(self):
        result = build_coverage_query.invoke(
            {"normalized_claim": "the unemployment rate fell to 3.4% in january 2023"}
        )
        assert "the" not in result.split()
        assert "unemployment" in result
        assert "3.4%" in result

    def test_truncates_long_input(self):
        result = build_coverage_query.invoke(
            {"normalized_claim": "word " * 100}
        )
        assert len(result) <= 100


class TestSearchCoverage:
    @pytest.mark.asyncio
    async def test_successful_search_publishes_article_count(self):
        ctx = _make_context()
        articles = [
            {"source": {"id": "msnbc", "name": "MSNBC"}, "title": "Test", "url": "https://example.com"},
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"articles": articles}

        with (
            patch.dict("os.environ", {"NEWSAPI_KEY": "test-key"}),
            patch("swarm_reasoning.agents.coverage_core_tools.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result_str = await search_coverage.ainvoke(
                {"query": "unemployment", "source_ids": "msnbc", "context": ctx}
            )

        result = json.loads(result_str)
        assert result["article_count"] == 1
        assert len(result["articles"]) == 1
        assert "error" not in result

        ctx.publish_obs.assert_called_once()
        call_kwargs = ctx.publish_obs.call_args[1]
        assert call_kwargs["code"] == ObservationCode.COVERAGE_ARTICLE_COUNT
        assert call_kwargs["value"] == "1"
        assert call_kwargs["value_type"] == ValueType.NM

    @pytest.mark.asyncio
    async def test_missing_api_key_publishes_x_status(self):
        ctx = _make_context()

        with patch.dict("os.environ", {}, clear=True):
            result_str = await search_coverage.ainvoke(
                {"query": "test", "source_ids": "msnbc", "context": ctx}
            )

        result = json.loads(result_str)
        assert result["article_count"] == 0
        assert result["error"] == "API key not configured"

        # Should publish 2 X-status observations
        assert ctx.publish_obs.call_count == 2
        for call in ctx.publish_obs.call_args_list:
            assert call[1]["status"] == "X"


class TestDetectCoverageFraming:
    @pytest.mark.asyncio
    async def test_positive_framing(self):
        ctx = _make_context()
        headlines = ["Economy shows strong growth", "Record gains boost confidence"]
        result_str = await detect_coverage_framing.ainvoke(
            {"headlines_json": json.dumps(headlines), "context": ctx}
        )

        result = json.loads(result_str)
        assert result["compound"] > 0.05
        assert "SUPPORTIVE" in result["framing"]

        ctx.publish_obs.assert_called_once()
        call_kwargs = ctx.publish_obs.call_args[1]
        assert call_kwargs["code"] == ObservationCode.COVERAGE_FRAMING
        assert call_kwargs["value_type"] == ValueType.CWE

    @pytest.mark.asyncio
    async def test_negative_framing(self):
        ctx = _make_context()
        headlines = ["Crisis deepens as losses mount", "Failed policies lead to collapse"]
        result_str = await detect_coverage_framing.ainvoke(
            {"headlines_json": json.dumps(headlines), "context": ctx}
        )

        result = json.loads(result_str)
        assert result["compound"] < -0.05
        assert "CRITICAL" in result["framing"]

    @pytest.mark.asyncio
    async def test_empty_headlines_publishes_absent(self):
        ctx = _make_context()
        result_str = await detect_coverage_framing.ainvoke(
            {"headlines_json": "[]", "context": ctx}
        )

        result = json.loads(result_str)
        assert result["compound"] == 0.0
        assert "ABSENT" in result["framing"]

        ctx.publish_obs.assert_called_once()
        assert "ABSENT" in ctx.publish_obs.call_args[1]["value"]


class TestFindTopCoverageSource:
    @pytest.mark.asyncio
    async def test_selects_highest_credibility(self):
        ctx = _make_context()
        articles = [
            {"source": {"id": "the-hill", "name": "The Hill"}, "url": "https://thehill.com/a"},
            {"source": {"id": "reuters", "name": "Reuters"}, "url": "https://reuters.com/a"},
        ]
        sources = [
            {"id": "reuters", "name": "Reuters", "credibility_rank": 95},
            {"id": "the-hill", "name": "The Hill", "credibility_rank": 72},
        ]

        result_str = await find_top_coverage_source.ainvoke(
            {
                "articles_json": json.dumps(articles),
                "sources_json": json.dumps(sources),
                "context": ctx,
            }
        )

        result = json.loads(result_str)
        assert result["name"] == "Reuters"
        assert result["url"] == "https://reuters.com/a"

        # Should publish TOP_SOURCE and TOP_SOURCE_URL
        assert ctx.publish_obs.call_count == 2
        codes = [c[1]["code"] for c in ctx.publish_obs.call_args_list]
        assert ObservationCode.COVERAGE_TOP_SOURCE in codes
        assert ObservationCode.COVERAGE_TOP_SOURCE_URL in codes

    @pytest.mark.asyncio
    async def test_empty_articles_publishes_nothing(self):
        ctx = _make_context()
        result_str = await find_top_coverage_source.ainvoke(
            {
                "articles_json": "[]",
                "sources_json": "[]",
                "context": ctx,
            }
        )

        result = json.loads(result_str)
        assert result["name"] is None
        assert result["url"] is None
        ctx.publish_obs.assert_not_called()
