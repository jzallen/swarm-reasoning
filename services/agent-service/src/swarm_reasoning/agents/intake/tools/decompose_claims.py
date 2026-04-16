"""LLM-powered claim decomposition from article text.

Extracts up to 5 core factual claims from article content, each with
a standalone claim sentence, supporting quote, and source citation.
"""

from __future__ import annotations

from pydantic import BaseModel


class Citation(BaseModel):
    """Attribution for an extracted claim."""

    author: str | None = None
    """Person or organization the claim is attributed to (None if unattributed)."""

    publisher: str
    """Publication name (e.g. "Reuters", "CDC")."""

    date: str | None = None
    """Publication date in YYYYMMDD format if known."""


class ExtractedClaim(BaseModel):
    """A single factual claim extracted from article text."""

    index: int
    """Claim index (1-5)."""

    claim_text: str
    """Standalone verifiable sentence — what the system will validate."""

    quote: str
    """Single best sentence from the article making or supporting the claim."""

    citation: Citation
    """Who said it, where it was published, and when."""


class DecomposeResult(BaseModel):
    """Structured result from LLM claim decomposition."""

    claims: list[ExtractedClaim]
    """Up to 5 extracted factual claims."""

    article_title: str
    """Title of the source article."""

    article_date: str | None = None
    """Extracted publication date in YYYYMMDD format if found."""
