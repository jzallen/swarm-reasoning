"""URL content fetcher for claim verification (ADR-004).

Fetches web page content from a URL using async HTTP, extracts main text
using trafilatura with BeautifulSoup fallback, and returns structured
metadata (title, publication date, word count, extracted text).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URL-keyed fetch cache (dev-only, ~30 lines)
#
# Bypassed when env var INTAKE_FETCH_CACHE=bypass is set; otherwise reads from
# and writes to a single SQLite file at INTAKE_FETCH_CACHE_PATH (default:
# ~/.cache/fact-checker/fetch.db). One row per URL, value is the JSON-serialized
# FetchResult dict. No TTL, no eviction -- `rm` the file to clear.
# ---------------------------------------------------------------------------

_FETCH_CACHE_ENV = "INTAKE_FETCH_CACHE"
_FETCH_CACHE_PATH_ENV = "INTAKE_FETCH_CACHE_PATH"


def _fetch_cache_path() -> Path:
    override = os.environ.get(_FETCH_CACHE_PATH_ENV)
    if override:
        return Path(override)
    return Path.home() / ".cache" / "fact-checker" / "fetch.db"


def _fetch_cache_bypassed() -> bool:
    return os.environ.get(_FETCH_CACHE_ENV, "").lower() == "bypass"


def _fetch_cache_conn() -> sqlite3.Connection:
    path = _fetch_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE IF NOT EXISTS fetch_cache (url TEXT PRIMARY KEY, payload TEXT)")
    return conn


def _get_cached_fetch(url: str) -> FetchResult | None:
    if _fetch_cache_bypassed():
        return None
    try:
        with _fetch_cache_conn() as conn:
            row = conn.execute("SELECT payload FROM fetch_cache WHERE url = ?", (url,)).fetchone()
    except sqlite3.Error:
        logger.exception("Fetch cache read failed for %s", url)
        return None
    if not row:
        return None
    try:
        return FetchResult(**json.loads(row[0]))
    except (TypeError, ValueError):
        logger.info("Fetch cache schema mismatch for %s; treating as miss", url)
        return None


def _put_cached_fetch(result: FetchResult) -> None:
    if _fetch_cache_bypassed():
        return
    try:
        with _fetch_cache_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO fetch_cache (url, payload) VALUES (?, ?)",
                (result.url, json.dumps(asdict(result))),
            )
    except sqlite3.Error:
        logger.exception("Fetch cache write failed for %s", result.url)


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
    text: str
    word_count: int
    extraction_method: str  # "trafilatura" or "beautifulsoup"
    author: str | None
    publisher: str | None
    published_at: str | None  # ISO-8601 if extractable, else None
    accessed_at: str  # ISO-8601 UTC, stamped at original network fetch time


class _ExtractedContent(NamedTuple):
    """Intermediate extraction result, before validation and normalization."""

    text: str | None
    title: str | None
    date: str | None
    author: str | None
    publisher: str | None


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
    """Extract main text, title, author, publisher, and date using trafilatura.

    Returns an empty :class:`_ExtractedContent` if trafilatura raises
    internally, so the caller can fall back to BeautifulSoup.
    """
    try:
        text = trafilatura.extract(html, url=url, include_comments=False, include_tables=False)
        metadata = trafilatura.extract_metadata(html, default_url=url)
    except Exception:
        logger.exception("Trafilatura extraction raised; falling back to BeautifulSoup")
        return _ExtractedContent(None, None, None, None, None)
    title = metadata.title if metadata else None
    date = metadata.date if metadata else None
    author = metadata.author if metadata else None
    publisher = metadata.sitename if metadata else None
    return _ExtractedContent(text=text, title=title, date=date, author=author, publisher=publisher)


def _extract_title_tag(html: str) -> str | None:
    """Extract page title from the HTML ``<title>`` element."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("title")
    if tag:
        return tag.get_text(strip=True) or None
    return None


def _jsonld_blocks(soup: BeautifulSoup) -> list[dict | list]:
    """Return parsed JSON-LD script contents; tolerant of malformed JSON."""
    blocks: list[dict | list] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        raw = tag.string or tag.get_text() or ""
        if not raw.strip():
            continue
        try:
            blocks.append(json.loads(raw))
        except (ValueError, TypeError):
            continue
    return blocks


def _jsonld_find(blocks: list[dict | list], key: str) -> str | None:
    """Shallow scan JSON-LD blocks for a named field; returns first string hit."""
    for block in blocks:
        items = block if isinstance(block, list) else [block]
        for item in items:
            if not isinstance(item, dict):
                continue
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict):
                name = val.get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()
            if isinstance(val, list) and val:
                first = val[0]
                if isinstance(first, str) and first.strip():
                    return first.strip()
                if isinstance(first, dict):
                    name = first.get("name")
                    if isinstance(name, str) and name.strip():
                        return name.strip()
    return None


def _extract_with_beautifulsoup(html: str) -> _ExtractedContent:
    """Fallback extraction using BeautifulSoup."""
    soup = BeautifulSoup(html, "html.parser")

    for element in soup(["script", "style", "nav", "footer", "header"]):
        element.decompose()

    text = soup.get_text(separator=" ", strip=True) or None

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) or None if title_tag else None

    # Re-parse for meta / JSON-LD since decompose() stripped <script>.
    meta_soup = BeautifulSoup(html, "html.parser")

    date = None
    for meta in meta_soup.find_all("meta"):
        prop = meta.get("property", "") or meta.get("name", "")
        if any(d in prop.lower() for d in ("published", "date", "pubdate")):
            date = meta.get("content")
            if date:
                break

    author = None
    for selector in (
        {"name": "author"},
        {"property": "article:author"},
    ):
        tag = meta_soup.find("meta", attrs=selector)
        if tag and tag.get("content"):
            author = tag["content"].strip() or None
            if author:
                break

    publisher = None
    og_site = meta_soup.find("meta", attrs={"property": "og:site_name"})
    if og_site and og_site.get("content"):
        publisher = og_site["content"].strip() or None

    jsonld = _jsonld_blocks(meta_soup)
    if not author:
        author = _jsonld_find(jsonld, "author")
    if not publisher:
        publisher = _jsonld_find(jsonld, "publisher")

    return _ExtractedContent(text=text, title=title, date=date, author=author, publisher=publisher)


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
        author=trafilatura_content.author or bs_content.author,
        publisher=trafilatura_content.publisher or bs_content.publisher,
    )
    return merged, "beautifulsoup"


def _normalize_to_iso(date_str: str | None) -> str | None:
    """Normalize a date string to ISO-8601; ``None`` if falsy or unparseable.

    Preserves timezone when the source string carries one. Bare date strings
    (no time) round-trip as ``YYYY-MM-DDT00:00:00``, which is still valid
    ISO-8601 and matches what trafilatura typically emits.
    """
    if not date_str:
        return None
    try:
        parsed = dateutil_parser.parse(date_str)
    except (ValueError, OverflowError):
        logger.debug("Could not parse date: %s", date_str)
        return None
    return parsed.isoformat()


def _hostname_fallback(url: str) -> str | None:
    """Return URL hostname stripped of a leading ``www.``."""
    host = urlparse(url).hostname
    if not host:
        return None
    return host[4:] if host.startswith("www.") else host


async def fetch_content(url: str) -> FetchResult:
    """Fetch a URL, extract its main content, and return structured metadata.

    Raises :class:`FetchError` on validation failure, network error,
    extraction failure, or insufficient content.
    """
    min_word_count = 50

    _validate_url(url)

    cached = _get_cached_fetch(url)
    if cached is not None:
        logger.info("Fetch cache hit for %s", url)
        return cached

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

    publisher = content.publisher or _hostname_fallback(url)
    accessed_at = dt.datetime.now(dt.timezone.utc).isoformat()

    result = FetchResult(
        url=url,
        title=content.title,
        text=content.text,
        word_count=word_count,
        extraction_method=method,
        author=content.author,
        publisher=publisher,
        published_at=_normalize_to_iso(content.date),
        accessed_at=accessed_at,
    )
    _put_cached_fetch(result)
    return result
