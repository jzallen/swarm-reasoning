"""LLM-powered claim decomposition from article text.

Extracts up to 5 core factual claims from article content. Each claim
carries a standalone claim sentence, a supporting quote, and (when the
article body attributes the claim to a named external source) a
rhetorical attribution. Article-level metadata (publisher, author,
date) is handled separately by ``fetch_content``, not the LLM.
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
3. **attribution**: ONLY if the article attributes this specific claim to a named external \
source in its body text (e.g. "CNBC noted", "according to Associated Press", "JPMorgan \
estimated"). Return null if the article makes the claim without such in-text attribution.
   - attributed_source: The name of the external source cited (e.g. "CNBC", "JPMorgan", \
"Associated Press").
   - attribution_phrase: The verbatim phrase from the article (e.g. "according to \
Associated Press").

DO NOT put article-level metadata (the publication you are reading, its author, its \
publication date) into the attribution field. Those are captured separately at the article \
level. Attribution is ONLY for external sources the article itself cites.

Prioritize claims that are:
- Specific and measurable (contains numbers, dates, named entities)
- Attributed to a named source (person, organization, study)
- Consequential (affects public understanding or policy)

Do NOT include:
- Opinions, predictions, or normative statements
- Claims that are trivially true or common knowledge
- Duplicate or overlapping claims

If the article contains no verifiable factual claims, return an empty claims list."""


class Attribution(BaseModel):
    """In-text attribution of a claim to a named external source.

    Distinct from article-level metadata. Populate only when the article
    body uses an attribution phrase for the specific claim.
    """

    attributed_source: str | None = None
    """Named external source credited within the article (e.g. 'CNBC')."""

    attribution_phrase: str | None = None
    """Verbatim attribution clause from the article body."""


class ExtractedClaim(BaseModel):
    """A single factual claim extracted from article text."""

    index: int
    """Claim index as produced by the LLM (1-5)."""

    claim_text: str = Field(min_length=1)
    """Standalone verifiable sentence — what the system will validate."""

    quote: str = Field(min_length=1)
    """Single best sentence from the article making or supporting the claim."""

    attribution: Attribution | None = None
    """In-text attribution to an external source, or None when the article
    makes the claim without citing one."""


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
