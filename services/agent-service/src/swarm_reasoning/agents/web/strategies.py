"""Extractor strategies for :class:`WebContentExtractor`.

A strategy converts raw HTML into a :class:`WebContentDocument`. If it
cannot produce one it raises :class:`ExtractionFailed` so the extractor
can try the next strategy in its chain. Other exceptions propagate --
they signal programming bugs, not extraction failures.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

import trafilatura
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

from swarm_reasoning.agents.web.extractor import WebContentDocument

logger = logging.getLogger(__name__)


class ExtractionFailed(Exception):
    """Strategy could not extract from the given HTML; try the next strategy."""


class ExtractorStrategy(Protocol):
    name: str

    def extract(self, html: str, url: str) -> WebContentDocument:
        """Return a populated :class:`WebContentDocument` or raise :class:`ExtractionFailed`."""
        ...


def _normalize_to_iso(date_str: str | None) -> str | None:
    if not date_str:
        return None
    try:
        parsed = dateutil_parser.parse(date_str)
    except (ValueError, OverflowError):
        logger.debug("Could not parse date: %s", date_str)
        return None
    return parsed.isoformat()


class TrafilaturaStrategy:
    """Extract via the trafilatura library."""

    name = "trafilatura"

    def extract(self, html: str, url: str) -> WebContentDocument:
        try:
            text = trafilatura.extract(
                html, url=url, include_comments=False, include_tables=False
            )
            metadata = trafilatura.extract_metadata(html, default_url=url)
        except Exception as exc:
            logger.info("Trafilatura raised for %s: %s", url, exc)
            raise ExtractionFailed("trafilatura raised") from exc

        if not text:
            raise ExtractionFailed("trafilatura returned no text")

        title = metadata.title if metadata else None
        if not title:
            soup = BeautifulSoup(html, "html.parser")
            tag = soup.find("title")
            if tag:
                title = tag.get_text(strip=True) or None

        return WebContentDocument(
            url=url,
            text=text,
            accessed_at="",
            title=title,
            author=metadata.author if metadata else None,
            publisher=metadata.sitename if metadata else None,
            published_at=_normalize_to_iso(metadata.date if metadata else None),
        )


def _jsonld_blocks(soup: BeautifulSoup) -> list[dict | list]:
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


class BeautifulSoupStrategy:
    """Extract via BeautifulSoup, with JSON-LD / meta-tag enrichment."""

    name = "beautifulsoup"

    def extract(self, html: str, url: str) -> WebContentDocument:
        soup = BeautifulSoup(html, "html.parser")
        for element in soup(["script", "style", "nav", "footer", "header"]):
            element.decompose()

        text = soup.get_text(separator=" ", strip=True) or None
        if not text:
            raise ExtractionFailed("beautifulsoup extracted no text")

        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) or None if title_tag else None

        meta_soup = BeautifulSoup(html, "html.parser")

        date = None
        for meta in meta_soup.find_all("meta"):
            prop = meta.get("property", "") or meta.get("name", "")
            if any(d in prop.lower() for d in ("published", "date", "pubdate")):
                date = meta.get("content")
                if date:
                    break

        author = None
        for selector in ({"name": "author"}, {"property": "article:author"}):
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

        return WebContentDocument(
            url=url,
            text=text,
            accessed_at="",
            title=title,
            author=author,
            publisher=publisher,
            published_at=_normalize_to_iso(date),
        )


class RawTextStrategy:
    """Always-available fallback: strip tags and truncate.

    Never raises :class:`ExtractionFailed`; returns whatever text can be
    pulled out (possibly an empty string on truly empty HTML).
    """

    name = "raw_text"

    def __init__(self, max_chars: int = 2000) -> None:
        self._max_chars = max_chars

    def extract(self, html: str, url: str) -> WebContentDocument:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(strip=True)[: self._max_chars]
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) or None if title_tag else None
        return WebContentDocument(
            url=url,
            text=text,
            accessed_at="",
            title=title,
        )


__all__ = [
    "BeautifulSoupStrategy",
    "ExtractionFailed",
    "ExtractorStrategy",
    "RawTextStrategy",
    "TrafilaturaStrategy",
]
