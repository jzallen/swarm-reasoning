"""Unit tests for swarm_reasoning.agents.web."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from swarm_reasoning.agents.web import (
    BeautifulSoupStrategy,
    ExtractionFailed,
    FetchCache,
    FetchErr,
    FetchOk,
    RawTextStrategy,
    TrafilaturaStrategy,
    WebContentDocument,
    WebContentExtractor,
    hostname_fallback,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_factory(handler):
    """Return a patched httpx.AsyncClient that uses MockTransport with *handler*."""
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    return factory


@pytest.fixture
def patch_httpx(monkeypatch):
    def _patch(handler):
        monkeypatch.setattr(
            "swarm_reasoning.agents.web.extractor.httpx.AsyncClient",
            _client_factory(handler),
        )

    return _patch


@pytest.fixture
def isolated_cache_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FETCH_CACHE_PATH", str(tmp_path / "cache.db"))
    monkeypatch.delenv("FETCH_CACHE", raising=False)
    return tmp_path


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def test_trafilatura_strategy_extracts_title_and_text():
    body = "The quick brown fox jumped. " * 30
    html = (
        f"<html><head><title>Hello</title></head>"
        f"<body><article><p>{body}</p></article></body></html>"
    )
    doc = TrafilaturaStrategy().extract(html, "https://example.com/a")
    assert doc.text
    assert doc.title == "Hello"


def test_trafilatura_strategy_raises_on_empty_html():
    with pytest.raises(ExtractionFailed):
        TrafilaturaStrategy().extract("<html></html>", "https://example.com/a")


def test_beautifulsoup_strategy_extracts_metadata():
    html = """
    <html>
      <head>
        <title>Article Title</title>
        <meta name="author" content="Jane Doe">
        <meta property="og:site_name" content="ExamplePub">
        <meta property="article:published_time" content="2024-01-02T03:04:05Z">
      </head>
      <body><p>Hello world. This is body text with enough words to survive.</p></body>
    </html>
    """
    doc = BeautifulSoupStrategy().extract(html, "https://example.com/a")
    assert "Hello world" in doc.text
    assert doc.title == "Article Title"
    assert doc.author == "Jane Doe"
    assert doc.publisher == "ExamplePub"
    assert doc.published_at is not None


def test_beautifulsoup_strategy_raises_on_empty_html():
    with pytest.raises(ExtractionFailed):
        BeautifulSoupStrategy().extract("<html><body></body></html>", "https://example.com/a")


def test_raw_text_strategy_truncates_and_never_raises():
    html = "<html><body>" + "x" * 5000 + "</body></html>"
    doc = RawTextStrategy(max_chars=100).extract(html, "https://example.com/a")
    assert len(doc.text) == 100

    doc_empty = RawTextStrategy().extract("<html></html>", "https://example.com/a")
    assert doc_empty.text == ""


# ---------------------------------------------------------------------------
# WebContentExtractor control flow
# ---------------------------------------------------------------------------


async def test_invalid_url_returns_err():
    extractor = WebContentExtractor(strategies=[RawTextStrategy()])
    result = await extractor.fetch("not-a-url")
    assert isinstance(result, FetchErr)
    assert result.reason == "URL_INVALID_FORMAT"


async def test_timeout_returns_err(patch_httpx):
    def handler(request):
        raise httpx.TimeoutException("slow")

    patch_httpx(handler)
    extractor = WebContentExtractor(strategies=[RawTextStrategy()])
    result = await extractor.fetch("https://example.com/a")
    assert isinstance(result, FetchErr)
    assert result.reason == "FETCH_TIMEOUT"


async def test_http_error_returns_coded_err(patch_httpx):
    def handler(request):
        return httpx.Response(404, content=b"nope", headers={"content-type": "text/html"})

    patch_httpx(handler)
    extractor = WebContentExtractor(strategies=[RawTextStrategy()])
    result = await extractor.fetch("https://example.com/a")
    assert isinstance(result, FetchErr)
    assert result.reason == "HTTP_404"


async def test_connection_error_returns_err(patch_httpx):
    def handler(request):
        raise httpx.ConnectError("boom")

    patch_httpx(handler)
    extractor = WebContentExtractor(strategies=[RawTextStrategy()])
    result = await extractor.fetch("https://example.com/a")
    assert isinstance(result, FetchErr)
    assert result.reason == "FETCH_CONNECTION_ERROR"


async def test_non_html_rejected(patch_httpx):
    def handler(request):
        return httpx.Response(200, content=b"{}", headers={"content-type": "application/json"})

    patch_httpx(handler)
    extractor = WebContentExtractor(strategies=[RawTextStrategy()])
    result = await extractor.fetch("https://example.com/a")
    assert isinstance(result, FetchErr)
    assert result.reason == "URL_NOT_HTML"


async def test_size_cap_rejected(patch_httpx):
    def handler(request):
        return httpx.Response(
            200,
            content=b"<html><body>" + b"x" * 200 + b"</body></html>",
            headers={"content-type": "text/html"},
        )

    patch_httpx(handler)
    extractor = WebContentExtractor(
        strategies=[RawTextStrategy()],
        max_content_bytes=50,
    )
    result = await extractor.fetch("https://example.com/a")
    assert isinstance(result, FetchErr)
    assert result.reason == "CONTENT_TOO_LARGE"


async def test_strategy_chain_skips_failing_strategy(patch_httpx):
    def handler(request):
        return httpx.Response(
            200,
            content=b"<html><body><p>Some content</p></body></html>",
            headers={"content-type": "text/html"},
        )

    patch_httpx(handler)

    class AlwaysFail:
        name = "fail"

        def extract(self, html, url):
            raise ExtractionFailed("nope")

    extractor = WebContentExtractor(
        strategies=[AlwaysFail(), RawTextStrategy()],
    )
    result = await extractor.fetch("https://example.com/a")
    assert isinstance(result, FetchOk)
    assert result.document.extraction_method == "raw_text"


async def test_strategy_chain_all_fail_returns_extraction_failed(patch_httpx):
    def handler(request):
        return httpx.Response(
            200,
            content=b"<html></html>",
            headers={"content-type": "text/html"},
        )

    patch_httpx(handler)

    class AlwaysFail:
        name = "fail"

        def extract(self, html, url):
            raise ExtractionFailed("nope")

    extractor = WebContentExtractor(strategies=[AlwaysFail(), AlwaysFail()])
    result = await extractor.fetch("https://example.com/a")
    assert isinstance(result, FetchErr)
    assert result.reason == "EXTRACTION_FAILED"


async def test_successful_extraction_stamps_method_and_accessed_at(patch_httpx):
    def handler(request):
        return httpx.Response(
            200,
            content=b"<html><body><p>Hello world content</p></body></html>",
            headers={"content-type": "text/html"},
        )

    patch_httpx(handler)
    extractor = WebContentExtractor(strategies=[RawTextStrategy()])
    result = await extractor.fetch("https://example.com/a")
    assert isinstance(result, FetchOk)
    assert result.document.extraction_method == "raw_text"
    assert result.document.accessed_at


# ---------------------------------------------------------------------------
# FetchCache
# ---------------------------------------------------------------------------


async def test_cache_hit_short_circuits(patch_httpx, isolated_cache_env):
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        return httpx.Response(
            200,
            content=b"<html><body><p>Hello cached world</p></body></html>",
            headers={"content-type": "text/html"},
        )

    patch_httpx(handler)
    cache = FetchCache()
    extractor = WebContentExtractor(strategies=[RawTextStrategy()], cache=cache)

    first = await extractor.fetch("https://example.com/a")
    second = await extractor.fetch("https://example.com/a")

    assert isinstance(first, FetchOk)
    assert isinstance(second, FetchOk)
    assert calls["count"] == 1


def test_cache_bypass_noop(monkeypatch, tmp_path):
    monkeypatch.setenv("FETCH_CACHE", "bypass")
    monkeypatch.setenv("FETCH_CACHE_PATH", str(tmp_path / "c.db"))
    cache = FetchCache()
    doc = WebContentDocument(url="https://a", text="hi", accessed_at="now")
    cache.put(doc)
    assert cache.get("https://a") is None
    assert not Path(tmp_path / "c.db").exists()


# ---------------------------------------------------------------------------
# hostname_fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.example.com/path", "example.com"),
        ("https://example.com/path", "example.com"),
        ("not-a-url", None),
    ],
)
def test_hostname_fallback(url, expected):
    assert hostname_fallback(url) == expected


# ---------------------------------------------------------------------------
# Result monad basics
# ---------------------------------------------------------------------------


def test_fetch_ok_and_then_and_unwrap():
    doc = WebContentDocument(url="u", text="t", accessed_at="a")
    ok = FetchOk(doc)
    assert ok.unwrap_or(WebContentDocument(url="x", text="", accessed_at="")) is doc
    result = ok.and_then(lambda d: FetchErr("boom"))
    assert isinstance(result, FetchErr)
    assert result.reason == "boom"


def test_fetch_err_ignores_map_and_then():
    err = FetchErr("NOPE")
    assert err.map(lambda d: d) is err
    assert err.and_then(lambda d: FetchOk(d)) is err
    default = WebContentDocument(url="x", text="", accessed_at="")
    assert err.unwrap_or(default) is default
