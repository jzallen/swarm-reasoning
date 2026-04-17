"""URL content fetcher for claim verification (ADR-004).

Fetches web page content from a URL using async HTTP, extracts main text
using trafilatura with BeautifulSoup fallback, and returns structured
metadata (title, publication date, word count, extracted text).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import NamedTuple

import httpx
import trafilatura
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)


class FetchError(Exception):
    """Raised when content fetching or extraction fails."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class FetchResult:
    """Structured result from fetching and extracting URL content."""

    url: str
    title: str | None
    date: str | None
    text: str
    word_count: int
    extraction_method: str  # "trafilatura" or "beautifulsoup"


class _ExtractedContent(NamedTuple):
    """Intermediate extraction result, before validation and normalization."""

    text: str | None
    title: str | None
    date: str | None


def _validate_url(url: str) -> None:
    """Validate URL format. Raises FetchError if malformed."""
    url_pattern = re.compile(r"^https?://[^\s]+\.[^\s]{2,}$")
    if not url_pattern.match(url):
        raise FetchError("URL_INVALID_FORMAT")


async def _fetch_html(url: str) -> str:
    """Fetch HTML content from *url* via async HTTP GET.

    Follows redirects. Raises :class:`FetchError` on timeout, HTTP error,
    connection failure, non-HTML content type, or oversized response.
    """
    request_timeout = 10.0
    max_content_bytes = 5 * 1024 * 1024
    user_agent = "SwarmReasoning/1.0 (fact-checking bot)"

    async with httpx.AsyncClient(
        timeout=request_timeout,
        follow_redirects=True,
        headers={"User-Agent": user_agent},
    ) as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except httpx.TimeoutException:
            raise FetchError("FETCH_TIMEOUT")
        except httpx.HTTPStatusError as exc:
            raise FetchError(f"HTTP_{exc.response.status_code}")
        except httpx.RequestError:
            raise FetchError("FETCH_CONNECTION_ERROR")

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type.lower():
        raise FetchError("URL_NOT_HTML")

    if len(response.content) > max_content_bytes:
        raise FetchError("CONTENT_TOO_LARGE")

    return response.text


def _extract_with_trafilatura(html: str, url: str) -> _ExtractedContent:
    """Extract main text, title, and date using trafilatura.

    Returns an empty :class:`_ExtractedContent` if trafilatura raises
    internally, so the caller can fall back to BeautifulSoup.
    """
    try:
        text = trafilatura.extract(html, url=url, include_comments=False, include_tables=False)
        metadata = trafilatura.extract_metadata(html, default_url=url)
    except Exception:
        logger.exception("Trafilatura extraction raised; falling back to BeautifulSoup")
        return _ExtractedContent(None, None, None)
    title = metadata.title if metadata else None
    date = metadata.date if metadata else None
    return _ExtractedContent(text=text, title=title, date=date)


def _extract_title_tag(html: str) -> str | None:
    """Extract page title from the HTML ``<title>`` element."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("title")
    if tag:
        return tag.get_text(strip=True) or None
    return None


def _extract_with_beautifulsoup(html: str) -> _ExtractedContent:
    """Fallback extraction using BeautifulSoup."""
    soup = BeautifulSoup(html, "html.parser")

    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()

    text = soup.get_text(separator=" ", strip=True) or None

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) or None if title_tag else None

    date = None
    for meta in soup.find_all("meta"):
        prop = meta.get("property", "") or meta.get("name", "")
        if any(d in prop.lower() for d in ("published", "date", "pubdate")):
            date = meta.get("content")
            if date:
                break

    return _ExtractedContent(text=text, title=title, date=date)


def _extract_content(html: str, url: str) -> tuple[_ExtractedContent, str]:
    """Run the extraction fallback chain; return content and the method name used.

    Future: if trafilatura + BeautifulSoup both fail on a page, a third strategy
    could hand the URL (or a Chromium-rendered PDF of it) to an LLM for
    interpretation. Not worth building until we see real pages where both
    HTML parsers come up empty.
    """
    trafilatura_content = _extract_with_trafilatura(html, url)
    if trafilatura_content.text:
        if not trafilatura_content.title:
            trafilatura_content = trafilatura_content._replace(title=_extract_title_tag(html))
        return trafilatura_content, "trafilatura"

    logger.info("Trafilatura extraction empty for %s, trying BeautifulSoup", url)
    bs_content = _extract_with_beautifulsoup(html)
    merged = _ExtractedContent(
        text=bs_content.text,
        title=trafilatura_content.title or bs_content.title,
        date=trafilatura_content.date or bs_content.date,
    )
    return merged, "beautifulsoup"


def _normalize_date(date_str: str | None) -> str | None:
    """Normalize a date string to YYYYMMDD format; ``None`` if falsy or unparseable."""
    if not date_str:
        return None
    try:
        dt = dateutil_parser.parse(date_str)
    except (ValueError, OverflowError):
        logger.debug("Could not parse date: %s", date_str)
        return None
    return dt.strftime("%Y%m%d")


async def fetch_content(url: str) -> FetchResult:
    """Fetch a URL, extract its main content, and return structured metadata.

    Raises :class:`FetchError` on validation failure, network error,
    extraction failure, or insufficient content.
    """
    min_word_count = 50

    _validate_url(url)

    logger.info("Fetching content from %s", url)
    html = await _fetch_html(url)
    logger.info("Fetched %d bytes from %s", len(html), url)

    content, method = _extract_content(html, url)

    if not content.text:
        raise FetchError("EXTRACTION_FAILED")

    word_count = len(content.text.split())
    if word_count < min_word_count:
        raise FetchError(f"CONTENT_TOO_SHORT:{word_count}")

    logger.info("Extracted %d words from %s via %s", word_count, url, method)

    return FetchResult(
        url=url,
        title=content.title,
        date=_normalize_date(content.date),
        text=content.text,
        word_count=word_count,
        extraction_method=method,
    )
