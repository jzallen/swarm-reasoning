"""Shared URL fetch + strategy-chain extraction.

Intake and evidence both use :class:`WebContentExtractor`. Callers pass
a list of :class:`ExtractorStrategy` instances; the extractor handles
URL validation, HTTP transport, cache access, and strategy control flow,
then returns a :data:`FetchResult` (``FetchOk`` | ``FetchErr``) so
callers handle success and failure explicitly without ``try/except``.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Callable
from urllib.parse import urlparse

import httpx

if TYPE_CHECKING:
    from swarm_reasoning.agents.web.cache import FetchCache
    from swarm_reasoning.agents.web.strategies import ExtractorStrategy

logger = logging.getLogger(__name__)

_URL_PATTERN = re.compile(r"^https?://[^\s]+\.[^\s]{2,}$")


@dataclass(frozen=True)
class WebContentDocument:
    """Structured representation of an extracted web document."""

    url: str
    text: str
    accessed_at: str
    title: str | None = None
    author: str | None = None
    publisher: str | None = None
    published_at: str | None = None
    extraction_method: str = "unknown"
    raw_html: str | None = None


@dataclass(frozen=True)
class FetchOk:
    document: WebContentDocument

    def map(self, f: Callable[[WebContentDocument], WebContentDocument]) -> "FetchResult":
        return FetchOk(f(self.document))

    def and_then(self, f: Callable[[WebContentDocument], "FetchResult"]) -> "FetchResult":
        return f(self.document)

    def unwrap_or(self, default: WebContentDocument) -> WebContentDocument:
        return self.document


@dataclass(frozen=True)
class FetchErr:
    reason: str
    detail: str | None = None

    def map(self, f: Callable[[WebContentDocument], WebContentDocument]) -> "FetchResult":
        return self

    def and_then(self, f: Callable[[WebContentDocument], "FetchResult"]) -> "FetchResult":
        return self

    def unwrap_or(self, default: WebContentDocument) -> WebContentDocument:
        return default


FetchResult = FetchOk | FetchErr


def hostname_fallback(url: str) -> str | None:
    """Return the URL's hostname, stripping a leading ``www.``."""
    host = urlparse(url).hostname
    if not host:
        return None
    return host[4:] if host.startswith("www.") else host


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class WebContentExtractor:
    """Fetch a URL and extract a :class:`WebContentDocument` via a strategy chain."""

    def __init__(
        self,
        strategies: list[ExtractorStrategy],
        cache: FetchCache | None = None,
        timeout_seconds: float = 10.0,
        max_content_bytes: int = 5 * 1024 * 1024,
        user_agent: str = "SwarmReasoning/1.0 (fact-checking bot)",
    ) -> None:
        if not strategies:
            raise ValueError("WebContentExtractor requires at least one strategy")
        self._strategies = list(strategies)
        self._cache = cache
        self._timeout = timeout_seconds
        self._max_content_bytes = max_content_bytes
        self._user_agent = user_agent

    async def fetch(self, url: str) -> FetchResult:
        """Fetch *url* and return ``FetchOk`` on success or ``FetchErr`` on any failure."""
        from swarm_reasoning.agents.web.strategies import ExtractionFailed

        if not _URL_PATTERN.match(url):
            return FetchErr("URL_INVALID_FORMAT")

        if self._cache is not None:
            cached = self._cache.get(url)
            if cached is not None:
                logger.info("Fetch cache hit for %s", url)
                return FetchOk(cached)

        html_result = await self._fetch_html(url)
        if isinstance(html_result, FetchErr):
            return html_result
        html = html_result

        for strategy in self._strategies:
            try:
                document = strategy.extract(html, url)
            except ExtractionFailed:
                logger.info(
                    "Strategy %s failed for %s, trying next", strategy.name, url
                )
                continue
            document = replace(
                document,
                accessed_at=_now_iso(),
                extraction_method=strategy.name,
            )
            if self._cache is not None:
                self._cache.put(document)
            return FetchOk(document)

        return FetchErr("EXTRACTION_FAILED")

    async def _fetch_html(self, url: str) -> str | FetchErr:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            headers={"User-Agent": self._user_agent},
        ) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.TimeoutException:
                return FetchErr("FETCH_TIMEOUT")
            except httpx.HTTPStatusError as exc:
                return FetchErr(f"HTTP_{exc.response.status_code}")
            except httpx.RequestError:
                return FetchErr("FETCH_CONNECTION_ERROR")

        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type.lower():
            return FetchErr("URL_NOT_HTML")
        if len(response.content) > self._max_content_bytes:
            return FetchErr("CONTENT_TOO_LARGE")
        return response.text


__all__ = [
    "FetchErr",
    "FetchOk",
    "FetchResult",
    "WebContentDocument",
    "WebContentExtractor",
    "hostname_fallback",
]
