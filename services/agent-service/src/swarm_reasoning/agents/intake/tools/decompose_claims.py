"""LLM-powered claim decomposition from article text.

Extracts up to 5 core factual claims from article content, each with
a standalone claim sentence, supporting quote, and source citation.
"""

from __future__ import annotations

import json
import logging

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

logger = logging.getLogger(__name__)

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


MAX_CLAIMS = 5
"""Maximum number of claims to return from decomposition."""


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


# Resolve forward references for Pydantic models that reference each other.
ExtractedClaim.model_rebuild()
DecomposeResult.model_rebuild()


async def decompose_claims_llm(
    article_text: str,
    article_title: str,
    model: ChatAnthropic,
    config: RunnableConfig,
) -> str:
    """Call the LLM to extract factual claims from article text.

    Sends the system prompt and article content to the model via
    ``ChatAnthropic.ainvoke``, forwarding *config* for LangSmith tracing.

    Returns the raw response text. Callers are responsible for JSON
    parsing, field validation, and retry logic.

    Raises ``Exception`` on LLM invocation failure (callers should handle).
    """
    user_content = (
        f"Article Title: {article_title}\n\n"
        f"Article Text:\n{article_text}"
    )
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]
    response = await model.ainvoke(messages, config=config)
    return response.content.strip()


def parse_decompose_response(raw_text: str) -> list[ExtractedClaim]:
    """Parse and validate the raw LLM response into a list of ExtractedClaim.

    Performs:
        1. JSON parsing of the raw text
        2. Field validation: each claim must have claim_text, quote, and citation
        3. Citation validation: must have at least publisher; defaults author/date to None
        4. Truncation to :data:`MAX_CLAIMS` if the LLM returned more

    Returns a list of validated :class:`ExtractedClaim` objects.
    Raises :class:`json.JSONDecodeError` if the text is not valid JSON.
    Raises :class:`ValueError` if the JSON lacks a ``claims`` array.
    """
    data = json.loads(raw_text)

    if not isinstance(data, dict) or "claims" not in data:
        raise ValueError("Response JSON must contain a 'claims' array")

    raw_claims = data["claims"]
    if not isinstance(raw_claims, list):
        raise ValueError("'claims' must be a list")

    validated: list[ExtractedClaim] = []
    for i, item in enumerate(raw_claims[:MAX_CLAIMS]):
        if not isinstance(item, dict):
            logger.warning("Skipping non-dict claim at index %d", i)
            continue

        # Required fields
        claim_text = item.get("claim_text")
        quote = item.get("quote")
        citation_raw = item.get("citation")

        if not claim_text or not quote:
            logger.warning(
                "Skipping claim at index %d: missing claim_text or quote", i
            )
            continue

        if not isinstance(citation_raw, dict) or not citation_raw.get("publisher"):
            logger.warning(
                "Skipping claim at index %d: citation missing publisher", i
            )
            continue

        citation = Citation(
            author=citation_raw.get("author"),
            publisher=citation_raw["publisher"],
            date=citation_raw.get("date"),
        )

        validated.append(
            ExtractedClaim(
                index=len(validated) + 1,
                claim_text=claim_text,
                quote=quote,
                citation=citation,
            )
        )

    return validated
