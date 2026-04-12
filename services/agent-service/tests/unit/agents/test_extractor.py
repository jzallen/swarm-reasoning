"""Unit tests for entity extractor LLM logic."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from swarm_reasoning.agents.entity_extractor.extractor import (
    EntityExtractionResult,
    LLMUnavailableError,
    extract_entities_llm,
)


def _mock_claude_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(data))]
    return resp


class TestExtractEntitiesLLM:
    @pytest.mark.asyncio
    async def test_two_persons_extracted(self):
        client = AsyncMock()
        client.messages.create = AsyncMock(
            return_value=_mock_claude_response(
                {
                    "persons": ["Joe Biden", "Kamala Harris"],
                    "organizations": [],
                    "dates": [],
                    "locations": [],
                    "statistics": [],
                }
            )
        )

        result = await extract_entities_llm("Biden and Harris signed the bill.", client)

        assert isinstance(result, EntityExtractionResult)
        assert result.persons == ["Joe Biden", "Kamala Harris"]
        assert result.organizations == []
        assert result.dates == []

    @pytest.mark.asyncio
    async def test_empty_result(self):
        client = AsyncMock()
        client.messages.create = AsyncMock(
            return_value=_mock_claude_response(
                {
                    "persons": [],
                    "organizations": [],
                    "dates": [],
                    "locations": [],
                    "statistics": [],
                }
            )
        )

        result = await extract_entities_llm("The sky is blue.", client)

        assert result.persons == []
        assert result.organizations == []
        assert result.dates == []
        assert result.locations == []
        assert result.statistics == []

    @pytest.mark.asyncio
    async def test_api_failure_raises_llm_unavailable(self):
        import anthropic as anthropic_lib

        client = AsyncMock()
        client.messages.create = AsyncMock(
            side_effect=anthropic_lib.APIConnectionError(request=MagicMock())
        )

        with pytest.raises(LLMUnavailableError):
            await extract_entities_llm("Test claim.", client)

    @pytest.mark.asyncio
    async def test_mixed_entity_types(self):
        client = AsyncMock()
        client.messages.create = AsyncMock(
            return_value=_mock_claude_response(
                {
                    "persons": ["Barack Obama"],
                    "organizations": ["CDC", "WHO"],
                    "dates": ["20210115"],
                    "locations": ["Washington D.C."],
                    "statistics": ["87% of adults"],
                }
            )
        )

        result = await extract_entities_llm("Obama cited CDC and WHO data.", client)

        assert result.persons == ["Barack Obama"]
        assert result.organizations == ["CDC", "WHO"]
        assert result.dates == ["20210115"]
        assert result.locations == ["Washington D.C."]
        assert result.statistics == ["87% of adults"]

    @pytest.mark.asyncio
    async def test_non_json_response_returns_empty(self):
        client = AsyncMock()
        resp = MagicMock()
        resp.content = [MagicMock(text="I cannot extract entities from this.")]
        client.messages.create = AsyncMock(return_value=resp)

        result = await extract_entities_llm("Test claim.", client)

        assert result.persons == []
        assert result.organizations == []

    @pytest.mark.asyncio
    async def test_rate_limit_raises_llm_unavailable(self):
        import anthropic as anthropic_lib

        client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 429
        resp.headers = {}
        client.messages.create = AsyncMock(
            side_effect=anthropic_lib.RateLimitError(
                message="rate limited",
                response=resp,
                body=None,
            )
        )

        with pytest.raises(LLMUnavailableError):
            await extract_entities_llm("Test claim.", client)
