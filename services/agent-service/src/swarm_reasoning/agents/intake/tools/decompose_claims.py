"""LLM-powered claim decomposition from article text.

Extracts up to 5 core factual claims from article content, each with
a standalone claim sentence, supporting quote, and source citation.
"""

from __future__ import annotations

from pydantic import BaseModel

_SYSTEM_PROMPT = (
    "You are a claim extraction system for a fact-checking pipeline. "
    "Given an article's text and metadata, identify up to 5 core factual claims "
    "that are suitable for fact-checking.\n\n"
    "For each claim, provide three pieces of information:\n\n"
    "1. **claim_text**: A specific, verifiable factual assertion rewritten as a "
    "standalone sentence. This is what the system will attempt to validate.\n"
    "2. **quote**: The single best sentence from the article that makes or supports "
    "the claim. Choose one sentence even if multiple examples exist. This must be an "
    "exact quote from the source text.\n"
    "3. **citation**: Attribution for the claim \u2014 who said it, where it was published, "
    "and when.\n"
    "   - author: The person or organization the claim is attributed to "
    "(null if the article makes the claim without attribution)\n"
    "   - publisher: The name of the publication (provided in article metadata)\n"
    "   - date: The publication date (provided in article metadata, YYYYMMDD format)\n\n"
    "Prioritize claims that are:\n"
    "- Specific and measurable (contains numbers, dates, named entities)\n"
    "- Attributed to a named source (person, organization, study)\n"
    "- Consequential (affects public understanding or policy)\n\n"
    "Do NOT include:\n"
    "- Opinions, predictions, or normative statements\n"
    "- Claims that are trivially true or common knowledge\n"
    "- Duplicate or overlapping claims\n\n"
    'Return a JSON object with a "claims" array. Each claim has: '
    "index (1-5), claim_text, quote, citation.\n"
    'If the article contains no verifiable factual claims, return {"claims": []}.\n'
    "Respond with only the JSON object."
)


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
