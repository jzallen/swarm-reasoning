"""URL content fetcher for claim verification (ADR-004).

Fetches web page content from a URL using async HTTP, extracts main text
using trafilatura with BeautifulSoup fallback, and returns structured
metadata (title, publication date, word count, extracted text).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx
import trafilatura
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)

_URL_PATTERN = re.compile(r"^https?://[^\s]+\.[^\s]{2,}$")

MIN_WORD_COUNT = 50
"""Minimum word count for content to be considered substantive."""

MAX_CONTENT_BYTES = 5 * 1024 * 1024
"""Maximum response body size (5 MB)."""

_REQUEST_TIMEOUT = 30.0
"""HTTP request timeout in seconds."""

_USER_AGENT = "SwarmReasoning/1.0 (fact-checking bot)"


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


def _normalize_date(date_str: str | None) -> str | None:
    """Normalize a date string to YYYYMMDD format.

    Returns ``None`` if *date_str* is falsy or cannot be parsed.
    """
    if not date_str:
        return None
    try:
        dt = dateutil_parser.parse(date_str)
    except (ValueError, OverflowError):
        logger.debug("Could not parse date: %s", date_str)
        return None
    return dt.strftime("%Y%m%d")


def validate_url(url: str) -> None:
    """Validate URL format. Raises FetchError if malformed."""
    if not _URL_PATTERN.match(url):
        raise FetchError("URL_INVALID_FORMAT")


async def fetch_html(url: str) -> str:
    """Fetch HTML content from *url* via async HTTP GET.

    Follows redirects. Raises :class:`FetchError` on timeout, HTTP error,
    connection failure, or oversized response.
    """
    async with httpx.AsyncClient(
        timeout=_REQUEST_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _USER_AGENT},
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

    if len(response.content) > MAX_CONTENT_BYTES:
        raise FetchError("CONTENT_TOO_LARGE")

    return response.text


def extract_with_trafilatura(html: str, url: str) -> tuple[str | None, str | None, str | None]:
    """Extract main text, title, and date using trafilatura.

    Returns ``(text, title, date)``; any element may be ``None``. If
    trafilatura raises an exception internally, returns ``(None, None, None)``
    so the caller can fall back to BeautifulSoup rather than surfacing the
    raw parser error.
    """
    try:
        text = trafilatura.extract(html, url=url, include_comments=False, include_tables=False)
        metadata = trafilatura.extract_metadata(html, default_url=url)
    except Exception:
        logger.exception("Trafilatura extraction raised; falling back to BeautifulSoup")
        return None, None, None
    title = metadata.title if metadata else None
    date = metadata.date if metadata else None
    return text, title, date


def extract_title_tag(html: str) -> str | None:
    """Extract page title from the HTML ``<title>`` element.

    Returns the stripped text content, or ``None`` if the tag is missing or empty.
    """
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("title")
    if tag:
        return tag.get_text(strip=True) or None
    return None


def extract_with_beautifulsoup(
    html: str,
) -> tuple[str | None, str | None, str | None]:
    """Fallback extraction using BeautifulSoup.

    Returns ``(text, title, date)``; any element may be ``None``.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Strip non-content elements
    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()

    text = soup.get_text(separator=" ", strip=True) or None

    # Title
    title = None
    title_tag = soup.find("title")
    if title_tag:
        title = title_tag.get_text(strip=True) or None

    # Publication date from meta tags
    date = None
    for meta in soup.find_all("meta"):
        prop = meta.get("property", "") or meta.get("name", "")
        if any(d in prop.lower() for d in ("published", "date", "pubdate")):
            date = meta.get("content")
            if date:
                break

    return text, title, date


def _count_words(text: str) -> int:
    """Count whitespace-delimited words in *text*."""
    return len(text.split())


async def fetch_content(url: str) -> FetchResult:
    """Fetch a URL, extract its main content, and return structured metadata.

    Workflow:
        1. Validate URL format
        2. Async HTTP GET with timeout and size limit
        3. Extract text via trafilatura; fall back to BeautifulSoup
        4. Extract title and publication date
        5. Check word count ≥ :data:`MIN_WORD_COUNT`

    Raises :class:`FetchError` on validation failure, network error,
    extraction failure, or insufficient content.
    """
    validate_url(url)

    logger.info("Fetching content from %s", url)
    html = await fetch_html(url)
    logger.info("Fetched %d bytes from %s", len(html), url)

    # Primary extraction: trafilatura
    text, title, date = extract_with_trafilatura(html, url)
    extraction_method = "trafilatura"

    # Title fallback: if trafilatura extracted text but not title, try <title> tag
    if text and not title:
        title = extract_title_tag(html)

    # Fallback: BeautifulSoup
    if not text:
        logger.info("Trafilatura extraction empty for %s, trying BeautifulSoup", url)
        text, bs_title, bs_date = extract_with_beautifulsoup(html)
        extraction_method = "beautifulsoup"
        title = title or bs_title
        date = date or bs_date

    if not text:
        raise FetchError("EXTRACTION_FAILED")

    word_count = _count_words(text)
    if word_count < MIN_WORD_COUNT:
        raise FetchError(f"CONTENT_TOO_SHORT:{word_count}")

    logger.info("Extracted %d words from %s via %s", word_count, url, extraction_method)

    return FetchResult(
        url=url,
        title=title,
        date=_normalize_date(date),
        text=text,
        word_count=word_count,
        extraction_method=extraction_method,
    )
