"""Unit tests for source-validator URL validation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from swarm_reasoning.agents.source_validator.models import ValidationStatus
from swarm_reasoning.agents.source_validator.validator import UrlValidator, _is_soft_404


class TestSoft404Detection:
    def test_title_page_not_found(self):
        body = "<html><head><title>Page Not Found</title></head><body>sorry</body></html>"
        assert _is_soft_404(body) is True

    def test_title_404(self):
        body = "<html><head><title>404 - Error</title></head><body></body></html>"
        assert _is_soft_404(body) is True

    def test_title_not_found(self):
        body = "<html><head><title>Not Found</title></head><body></body></html>"
        assert _is_soft_404(body) is True

    def test_title_no_longer_available(self):
        body = "<html><head><title>No Longer Available</title></head><body></body></html>"
        assert _is_soft_404(body) is True

    def test_body_page_doesnt_exist(self):
        body = (
            "<html><head><title>Example</title></head><body>this page doesn't exist</body></html>"
        )
        assert _is_soft_404(body) is True

    def test_body_has_been_removed(self):
        body = (
            "<html><head><title>Example</title></head>"
            "<body>The content has been removed.</body></html>"
        )
        assert _is_soft_404(body) is True

    def test_legitimate_page(self):
        body = (
            "<html><head><title>Clinical Study Results</title></head>"
            "<body>The study found that vaccines are effective.</body></html>"
        )
        assert _is_soft_404(body) is False

    def test_empty_body(self):
        assert _is_soft_404("") is False


class TestUrlValidatorSingle:
    @pytest.mark.asyncio
    async def test_live_url_returns_200(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.history = []
        resp.url = "https://reuters.com/article/123"

        body_resp = MagicMock()
        body_resp.text = "<html><title>Reuters Article</title><body>Normal content</body></html>"

        client = AsyncMock()
        client.head = AsyncMock(return_value=resp)
        client.get = AsyncMock(return_value=body_resp)

        validator = UrlValidator()
        result = await validator._validate_url(client, "https://reuters.com/article/123")
        assert result.status == ValidationStatus.LIVE

    @pytest.mark.asyncio
    async def test_dead_url_returns_404(self):
        resp = MagicMock()
        resp.status_code = 404
        resp.history = []

        client = AsyncMock()
        client.head = AsyncMock(return_value=resp)

        validator = UrlValidator()
        result = await validator._validate_url(client, "https://example.com/removed")
        assert result.status == ValidationStatus.DEAD

    @pytest.mark.asyncio
    async def test_redirect_detected(self):
        redirect_resp = MagicMock()
        redirect_resp.status_code = 301

        final_resp = MagicMock()
        final_resp.status_code = 200
        final_resp.history = [redirect_resp]
        final_resp.url = "https://new-location.com/page"

        client = AsyncMock()
        client.head = AsyncMock(return_value=final_resp)

        validator = UrlValidator()
        result = await validator._validate_url(client, "https://old-location.com/page")
        assert result.status == ValidationStatus.REDIRECT
        assert result.final_url == "https://new-location.com/page"

    @pytest.mark.asyncio
    async def test_timeout_on_head(self):
        client = AsyncMock()
        client.head = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        validator = UrlValidator()
        result = await validator._validate_url(client, "https://slow.example.com")
        assert result.status == ValidationStatus.TIMEOUT

    @pytest.mark.asyncio
    async def test_soft_404_detected(self):
        head_resp = MagicMock()
        head_resp.status_code = 200
        head_resp.history = []

        body_resp = MagicMock()
        body_resp.text = (
            "<html><head><title>Page Not Found</title></head>"
            "<body>Sorry, this page doesn't exist</body></html>"
        )

        client = AsyncMock()
        client.head = AsyncMock(return_value=head_resp)
        client.get = AsyncMock(return_value=body_resp)

        validator = UrlValidator()
        result = await validator._validate_url(client, "https://example.com/gone")
        assert result.status == ValidationStatus.SOFT404

    @pytest.mark.asyncio
    async def test_head_405_fallback_to_get(self):
        head_resp = MagicMock()
        head_resp.status_code = 405

        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.history = []
        get_resp.text = "<html><title>Normal Page</title><body>Content here</body></html>"

        client = AsyncMock()
        client.head = AsyncMock(return_value=head_resp)
        client.get = AsyncMock(return_value=get_resp)

        validator = UrlValidator()
        result = await validator._validate_url(client, "https://example.com/no-head")
        # After 405 fallback, GET returns 200 -> check for soft-404 -> LIVE
        assert result.status == ValidationStatus.LIVE


class TestUrlValidatorConcurrent:
    @pytest.mark.asyncio
    async def test_validates_multiple_urls_concurrently(self):
        urls = [f"https://example.com/page{i}" for i in range(15)]

        resp = MagicMock()
        resp.status_code = 200
        resp.history = []

        body_resp = MagicMock()
        body_resp.text = "<html><title>Normal</title><body>Content</body></html>"

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=resp)
        mock_client.get = AsyncMock(return_value=body_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "swarm_reasoning.agents.source_validator.validator.httpx.AsyncClient",
            return_value=mock_client,
        ):
            validator = UrlValidator()
            results = await validator.validate_all(urls)

        assert len(results) == 15
        assert all(r.status == ValidationStatus.LIVE for r in results.values())

    @pytest.mark.asyncio
    async def test_empty_urls_returns_empty(self):
        validator = UrlValidator()
        results = await validator.validate_all([])
        assert results == {}
