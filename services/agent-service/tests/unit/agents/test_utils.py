"""Unit tests for the shared agent utilities module (_utils.py)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from swarm_reasoning.agents._utils import (
    STOP_WORDS,
    StreamNotFoundError,
    now_iso,
    resilient_get,
)

# ---------------------------------------------------------------------------
# now_iso()
# ---------------------------------------------------------------------------


class TestNowIso:
    def test_returns_utc_iso_string(self):
        result = now_iso()
        # Must parse as a valid ISO timestamp
        parsed = datetime.fromisoformat(result)
        assert parsed.tzinfo is not None
        assert parsed.tzinfo == timezone.utc

    def test_close_to_current_time(self):
        before = datetime.now(timezone.utc)
        result = datetime.fromisoformat(now_iso())
        after = datetime.now(timezone.utc)
        assert before <= result <= after


# ---------------------------------------------------------------------------
# StreamNotFoundError
# ---------------------------------------------------------------------------


class TestStreamNotFoundError:
    def test_is_exception(self):
        assert issubclass(StreamNotFoundError, Exception)

    def test_message_preserved(self):
        err = StreamNotFoundError("ingestion-agent stream missing")
        assert str(err) == "ingestion-agent stream missing"

    def test_raise_and_catch(self):
        with pytest.raises(StreamNotFoundError, match="not found"):
            raise StreamNotFoundError("stream not found")


# ---------------------------------------------------------------------------
# STOP_WORDS
# ---------------------------------------------------------------------------


class TestStopWords:
    def test_is_frozenset(self):
        assert isinstance(STOP_WORDS, frozenset)

    def test_contains_common_words(self):
        for word in ("a", "an", "the", "is", "and", "or", "not"):
            assert word in STOP_WORDS

    def test_contains_prepositions(self):
        """STOP_WORDS includes common prepositions."""
        prepositions = {"to", "of", "in", "for", "on", "with", "at", "by", "from", "into", "through"}
        assert prepositions <= STOP_WORDS

    def test_contains_pronouns(self):
        """STOP_WORDS includes common pronouns."""
        pronouns = {"it", "its", "he", "she", "they", "them", "his", "her", "their"}
        assert pronouns <= STOP_WORDS

    def test_immutable(self):
        with pytest.raises(AttributeError):
            STOP_WORDS.add("foo")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# resilient_get()
# ---------------------------------------------------------------------------


class TestResilientGet:
    async def test_success_no_retry(self):
        mock_response = httpx.Response(200, text="ok")
        with patch("swarm_reasoning.agents._utils.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            resp = await resilient_get("https://example.com/api")
            assert resp.status_code == 200
            assert mock_client.get.call_count == 1

    async def test_retry_on_429(self):
        rate_limited = httpx.Response(429, text="rate limited")
        ok = httpx.Response(200, text="ok")
        with patch("swarm_reasoning.agents._utils.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = [rate_limited, ok]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("swarm_reasoning.agents._utils.asyncio.sleep", new_callable=AsyncMock):
                resp = await resilient_get("https://example.com/api")

            assert resp.status_code == 200
            assert mock_client.get.call_count == 2

    async def test_retry_on_500(self):
        server_error = httpx.Response(500, text="server error")
        ok = httpx.Response(200, text="ok")
        with patch("swarm_reasoning.agents._utils.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = [server_error, ok]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("swarm_reasoning.agents._utils.asyncio.sleep", new_callable=AsyncMock):
                resp = await resilient_get("https://example.com/api")

            assert resp.status_code == 200
            assert mock_client.get.call_count == 2

    async def test_returns_error_after_retries_exhausted(self):
        rate_limited = httpx.Response(429, text="rate limited")
        with patch("swarm_reasoning.agents._utils.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = rate_limited
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            with patch("swarm_reasoning.agents._utils.asyncio.sleep", new_callable=AsyncMock):
                resp = await resilient_get("https://example.com/api", max_retries=2)

            assert resp.status_code == 429
            # 1 initial + 2 retries = 3
            assert mock_client.get.call_count == 3

    async def test_no_retry_on_4xx(self):
        not_found = httpx.Response(404, text="not found")
        with patch("swarm_reasoning.agents._utils.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = not_found
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            resp = await resilient_get("https://example.com/api")
            assert resp.status_code == 404
            assert mock_client.get.call_count == 1

    async def test_passes_params(self):
        mock_response = httpx.Response(200, text="ok")
        with patch("swarm_reasoning.agents._utils.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await resilient_get("https://example.com/api", params={"q": "test"})
            mock_client.get.assert_called_once_with("https://example.com/api", params={"q": "test"})

    async def test_follow_redirects_option(self):
        mock_response = httpx.Response(200, text="ok")
        with patch("swarm_reasoning.agents._utils.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await resilient_get("https://example.com", follow_redirects=True, max_redirects=3)
            mock_cls.assert_called_once_with(timeout=10.0, follow_redirects=True, max_redirects=3)

    async def test_custom_backoff(self):
        rate_limited = httpx.Response(429, text="rate limited")
        ok = httpx.Response(200, text="ok")
        with patch("swarm_reasoning.agents._utils.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = [rate_limited, ok]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            mock_sleep = AsyncMock()
            with patch("swarm_reasoning.agents._utils.asyncio.sleep", mock_sleep):
                await resilient_get("https://example.com/api", backoff=2.0)

            mock_sleep.assert_called_once_with(2.0)
