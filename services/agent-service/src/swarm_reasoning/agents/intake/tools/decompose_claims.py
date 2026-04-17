"""LLM-powered claim decomposition from article text.

Extracts up to 5 core factual claims from article content, each with
a standalone claim sentence, supporting quote, and source citation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langchain_anthropic import ChatAnthropic
    from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a claim extraction system for a fact-checking pipeline. Given an article's text and \
metadata, identify up to 5 core factual claims that are suitable for fact-checking.

For each claim, provide three pieces of information:

1. **claim_text**: A specific, verifiable factual assertion rewritten as a standalone \
sentence. This is what the system will attempt to validate.
2. **quote**: The single best sentence from the article that makes or supports the claim. \
Choose one sentence even if multiple examples exist. This must be an exact quote from the \
source text.
3. **citation**: Attribution for the claim \u2014 who said it, where it was published, and when.
   - author: The person or organization the claim is attributed to (null if the article \
makes the claim without attribution)
   - publisher: The name of the publication (provided in article metadata)
   - date: The publication date (provided in article metadata, YYYYMMDD format)

Prioritize claims that are:
- Specific and measurable (contains numbers, dates, named entities)
- Attributed to a named source (person, organization, study)
- Consequential (affects public understanding or policy)

Do NOT include:
- Opinions, predictions, or normative statements
- Claims that are trivially true or common knowledge
- Duplicate or overlapping claims

If the article contains no verifiable factual claims, return an empty claims list."""


class Citation(BaseModel):
    """Attribution for an extracted claim."""

    publisher: str = Field(min_length=1)
    """Publication name (e.g. "Reuters", "CDC")."""

    author: str | None = None
    """Person or organization the claim is attributed to (None if unattributed)."""

    date: str | None = None
    """Publication date in YYYYMMDD format if known."""


class ExtractedClaim(BaseModel):
    """A single factual claim extracted from article text."""

    index: int
    """Claim index as produced by the LLM (1-5)."""

    claim_text: str = Field(min_length=1)
    """Standalone verifiable sentence — what the system will validate."""

    quote: str = Field(min_length=1)
    """Single best sentence from the article making or supporting the claim."""

    citation: Citation
    """Who said it, where it was published, and when."""


class _DecomposeResult(BaseModel):
    claims: list[ExtractedClaim]


async def decompose_and_parse(
    article_text: str,
    article_title: str,
    model: ChatAnthropic,
    config: RunnableConfig,
) -> list[ExtractedClaim]:
    """Extract up to 5 factual claims from article text.

    Uses the model's structured-output mode; returns an empty list on any
    LLM or validation failure.
    """
    max_claims = 5
    structured = model.with_structured_output(_DecomposeResult)
    user_content = f"Article Title: {article_title}\n\nArticle Text:\n{article_text}"
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]
    try:
        result = await structured.ainvoke(messages, config=config)
    except Exception:
        logger.warning("Claim decomposition failed, returning empty list", exc_info=True)
        return []
    return result.claims[:max_claims]
