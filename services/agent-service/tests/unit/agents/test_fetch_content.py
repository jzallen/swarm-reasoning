"""Unit tests for the fetch_content tool module.

Tests cover:
- URL validation (valid/invalid formats)
- fetch_html (timeout, HTTP errors, connection errors, oversized responses)
- extract_with_trafilatura (text, title, date extraction)
- extract_with_beautifulsoup (fallback extraction)
- _count_words helper
- fetch_content orchestrator (happy path, fallback, error cases)
- FetchResult dataclass shape
- FetchError exception
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from swarm_reasoning.agents.intake.tools.fetch_content import (
    MAX_CONTENT_BYTES,
    MIN_WORD_COUNT,
    FetchError,
    FetchResult,
    _count_words,
    extract_with_beautifulsoup,
    extract_with_trafilatura,
    fetch_content,
    fetch_html,
    validate_url,
)

# Common patch prefix for fetch_content module
_P = "swarm_reasoning.agents.intake.tools.fetch_content"


# ---------------------------------------------------------------------------
# validate_url
# ---------------------------------------------------------------------------


class TestValidateUrl:
    def test_valid_http(self):
        validate_url("http://example.com/article")

    def test_valid_https(self):
        validate_url("https://www.example.com/path/to/article")

    def test_rejects_empty(self):
        with pytest.raises(FetchError, match="URL_INVALID_FORMAT"):
            validate_url("")

    def test_rejects_no_scheme(self):
        with pytest.raises(FetchError, match="URL_INVALID_FORMAT"):
            validate_url("example.com/article")

    def test_rejects_ftp(self):
        with pytest.raises(FetchError, match="URL_INVALID_FORMAT"):
            validate_url("ftp://example.com/file")

    def test_rejects_whitespace(self):
        with pytest.raises(FetchError, match="URL_INVALID_FORMAT"):
            validate_url("https://example .com/article")


# ---------------------------------------------------------------------------
# fetch_html
# ---------------------------------------------------------------------------


def _mock_httpx_client(**get_kwargs):
    """Build a mock httpx.AsyncClient with the given get() behavior."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(**get_kwargs)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestFetchHtml:
    @pytest.mark.asyncio
    async def test_success(self):
        mock_response = MagicMock()
        mock_response.text = "<html><body>Hello</body></html>"
        mock_response.content = b"<html><body>Hello</body></html>"
        mock_response.raise_for_status = MagicMock()

        client = _mock_httpx_client(return_value=mock_response)
        with patch(f"{_P}.httpx.AsyncClient", return_value=client):
            result = await fetch_html("https://example.com")
        assert result == "<html><body>Hello</body></html>"

    @pytest.mark.asyncio
    async def test_timeout(self):
        exc = httpx.TimeoutException("timeout")
        client = _mock_httpx_client(side_effect=exc)
        with patch(f"{_P}.httpx.AsyncClient", return_value=client):
            with pytest.raises(FetchError, match="FETCH_TIMEOUT"):
                await fetch_html("https://example.com")

    @pytest.mark.asyncio
    async def test_http_error(self):
        exc = httpx.HTTPStatusError(
            "not found",
            request=MagicMock(),
            response=MagicMock(status_code=404),
        )
        client = _mock_httpx_client(side_effect=exc)
        with patch(f"{_P}.httpx.AsyncClient", return_value=client):
            with pytest.raises(FetchError, match="HTTP_404"):
                await fetch_html("https://example.com")

    @pytest.mark.asyncio
    async def test_connection_error(self):
        exc = httpx.ConnectError("refused")
        client = _mock_httpx_client(side_effect=exc)
        with patch(f"{_P}.httpx.AsyncClient", return_value=client):
            with pytest.raises(FetchError, match="FETCH_CONNECTION_ERROR"):
                await fetch_html("https://example.com")

    @pytest.mark.asyncio
    async def test_oversized_response(self):
        mock_response = MagicMock()
        mock_response.text = "x"
        mock_response.content = b"x" * (MAX_CONTENT_BYTES + 1)
        mock_response.raise_for_status = MagicMock()

        client = _mock_httpx_client(return_value=mock_response)
        with patch(f"{_P}.httpx.AsyncClient", return_value=client):
            with pytest.raises(FetchError, match="CONTENT_TOO_LARGE"):
                await fetch_html("https://example.com")


# ---------------------------------------------------------------------------
# extract_with_trafilatura
# ---------------------------------------------------------------------------


class TestExtractWithTrafilatura:
    def test_extracts_text_and_metadata(self):
        mock_metadata = MagicMock()
        mock_metadata.title = "Test Article"
        mock_metadata.date = "2024-01-15"

        with (
            patch(
                f"{_P}.trafilatura.extract",
                return_value="Article body text here",
            ),
            patch(
                f"{_P}.trafilatura.extract_metadata",
                return_value=mock_metadata,
            ),
        ):
            text, title, date = extract_with_trafilatura(
                "<html>...</html>", "https://example.com"
            )

        assert text == "Article body text here"
        assert title == "Test Article"
        assert date == "2024-01-15"

    def test_returns_none_when_extraction_fails(self):
        with (
            patch(f"{_P}.trafilatura.extract", return_value=None),
            patch(
                f"{_P}.trafilatura.extract_metadata",
                return_value=None,
            ),
        ):
            text, title, date = extract_with_trafilatura(
                "<html>...</html>", "https://example.com"
            )

        assert text is None
        assert title is None
        assert date is None

    def test_metadata_none(self):
        with (
            patch(
                f"{_P}.trafilatura.extract",
                return_value="Some text",
            ),
            patch(
                f"{_P}.trafilatura.extract_metadata",
                return_value=None,
            ),
        ):
            text, title, date = extract_with_trafilatura(
                "<html>...</html>", "https://example.com"
            )

        assert text == "Some text"
        assert title is None
        assert date is None


# ---------------------------------------------------------------------------
# extract_with_beautifulsoup
# ---------------------------------------------------------------------------


class TestExtractWithBeautifulsoup:
    def test_extracts_text_and_title(self):
        html = """
        <html>
        <head><title>My Article</title></head>
        <body>
            <nav>Navigation</nav>
            <p>This is the main article body with enough words.</p>
            <footer>Footer content</footer>
        </body>
        </html>
        """
        text, title, date = extract_with_beautifulsoup(html)
        assert title == "My Article"
        assert "main article body" in text
        # nav and footer should be stripped
        assert "Navigation" not in text
        assert "Footer content" not in text

    def test_extracts_date_from_meta(self):
        html = """
        <html>
        <head>
            <meta property="article:published_time"
                  content="2024-03-15T10:00:00Z">
        </head>
        <body><p>Content here</p></body>
        </html>
        """
        _, _, date = extract_with_beautifulsoup(html)
        assert date == "2024-03-15T10:00:00Z"

    def test_no_title(self):
        html = "<html><body><p>Just text</p></body></html>"
        text, title, date = extract_with_beautifulsoup(html)
        assert title is None
        assert "Just text" in text

    def test_empty_html(self):
        text, title, date = extract_with_beautifulsoup("")
        assert title is None
        assert date is None


# ---------------------------------------------------------------------------
# _count_words
# ---------------------------------------------------------------------------


class TestCountWords:
    def test_simple(self):
        assert _count_words("one two three") == 3

    def test_empty(self):
        assert _count_words("") == 0

    def test_extra_whitespace(self):
        assert _count_words("  one   two  three  ") == 3


# ---------------------------------------------------------------------------
# FetchResult dataclass
# ---------------------------------------------------------------------------


class TestFetchResult:
    def test_fields(self):
        r = FetchResult(
            url="https://example.com",
            title="Title",
            date="2024-01-15",
            text="Article text",
            word_count=2,
            extraction_method="trafilatura",
        )
        assert r.url == "https://example.com"
        assert r.title == "Title"
        assert r.date == "2024-01-15"
        assert r.text == "Article text"
        assert r.word_count == 2
        assert r.extraction_method == "trafilatura"


# ---------------------------------------------------------------------------
# FetchError
# ---------------------------------------------------------------------------


class TestFetchError:
    def test_reason_attribute(self):
        err = FetchError("URL_INVALID_FORMAT")
        assert err.reason == "URL_INVALID_FORMAT"
        assert str(err) == "URL_INVALID_FORMAT"


# ---------------------------------------------------------------------------
# fetch_content (orchestrator)
# ---------------------------------------------------------------------------


class TestFetchContent:
    @pytest.mark.asyncio
    async def test_happy_path_trafilatura(self):
        html = "<html><body>Lots of words here</body></html>"
        body_text = " ".join(["word"] * MIN_WORD_COUNT)

        mock_metadata = MagicMock()
        mock_metadata.title = "Great Article"
        mock_metadata.date = "2024-06-01"

        with (
            patch(f"{_P}.fetch_html", return_value=html),
            patch(
                f"{_P}.trafilatura.extract",
                return_value=body_text,
            ),
            patch(
                f"{_P}.trafilatura.extract_metadata",
                return_value=mock_metadata,
            ),
        ):
            result = await fetch_content(
                "https://example.com/article"
            )

        assert result.url == "https://example.com/article"
        assert result.title == "Great Article"
        assert result.date == "2024-06-01"
        assert result.text == body_text
        assert result.word_count == MIN_WORD_COUNT
        assert result.extraction_method == "trafilatura"

    @pytest.mark.asyncio
    async def test_fallback_to_beautifulsoup(self):
        body_text = " ".join(["word"] * MIN_WORD_COUNT)
        html = (
            f"<html><head><title>Fallback Title</title></head>"
            f"<body><p>{body_text}</p></body></html>"
        )

        with (
            patch(f"{_P}.fetch_html", return_value=html),
            patch(
                f"{_P}.trafilatura.extract",
                return_value=None,
            ),
            patch(
                f"{_P}.trafilatura.extract_metadata",
                return_value=None,
            ),
        ):
            result = await fetch_content(
                "https://example.com/article"
            )

        assert result.extraction_method == "beautifulsoup"
        assert result.title == "Fallback Title"
        assert result.word_count >= MIN_WORD_COUNT

    @pytest.mark.asyncio
    async def test_invalid_url(self):
        with pytest.raises(FetchError, match="URL_INVALID_FORMAT"):
            await fetch_content("not-a-url")

    @pytest.mark.asyncio
    async def test_extraction_failed(self):
        with (
            patch(f"{_P}.fetch_html", return_value="<html></html>"),
            patch(
                f"{_P}.trafilatura.extract",
                return_value=None,
            ),
            patch(
                f"{_P}.trafilatura.extract_metadata",
                return_value=None,
            ),
        ):
            with pytest.raises(FetchError, match="EXTRACTION_FAILED"):
                await fetch_content("https://example.com/empty")

    @pytest.mark.asyncio
    async def test_content_too_short(self):
        short_text = "only three words"

        with (
            patch(
                f"{_P}.fetch_html",
                return_value="<html>...</html>",
            ),
            patch(
                f"{_P}.trafilatura.extract",
                return_value=short_text,
            ),
            patch(
                f"{_P}.trafilatura.extract_metadata",
                return_value=None,
            ),
        ):
            with pytest.raises(FetchError, match="CONTENT_TOO_SHORT"):
                await fetch_content("https://example.com/short")

    @pytest.mark.asyncio
    async def test_fetch_error_propagates(self):
        with patch(
            f"{_P}.fetch_html",
            side_effect=FetchError("FETCH_TIMEOUT"),
        ):
            with pytest.raises(FetchError, match="FETCH_TIMEOUT"):
                await fetch_content("https://example.com/slow")

    @pytest.mark.asyncio
    async def test_trafilatura_title_preserved_on_fallback(self):
        """When trafilatura returns no text but has metadata,
        title/date should be preserved on BS4 fallback."""
        body_text = " ".join(["word"] * MIN_WORD_COUNT)
        html = f"<html><body><p>{body_text}</p></body></html>"

        mock_metadata = MagicMock()
        mock_metadata.title = "Trafilatura Title"
        mock_metadata.date = "2024-01-01"

        with (
            patch(f"{_P}.fetch_html", return_value=html),
            patch(
                f"{_P}.trafilatura.extract",
                return_value=None,
            ),
            patch(
                f"{_P}.trafilatura.extract_metadata",
                return_value=mock_metadata,
            ),
        ):
            result = await fetch_content(
                "https://example.com/article"
            )

        assert result.extraction_method == "beautifulsoup"
        assert result.title == "Trafilatura Title"
        assert result.date == "2024-01-01"
