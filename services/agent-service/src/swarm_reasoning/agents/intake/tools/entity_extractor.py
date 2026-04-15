"""LLM-powered entity extraction using Claude structured output.

Extracts named entities (persons, organizations, dates, locations, statistics)
from claim text using Claude with structured JSON output.
"""

from __future__ import annotations

import json
import logging

from anthropic import AsyncAnthropic
from pydantic import BaseModel

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a named entity recognition (NER) system for a fact-checking pipeline. "
    "Extract entities from the given claim text and return a JSON object with these fields:\n\n"
    '- "persons": list of named persons explicitly mentioned (canonical names)\n'
    '- "organizations": list of named organizations explicitly mentioned\n'
    '- "dates": list of dates or date ranges referenced. '
    "Use YYYYMMDD format for single dates and YYYYMMDD-YYYYMMDD for ranges where possible. "
    "If the exact date cannot be determined, return the original text.\n"
    '- "locations": list of geographic locations explicitly mentioned\n'
    '- "statistics": list of numeric claims or quantities '
    '(e.g. "87% of adults", "$1.2 trillion")\n\n'
    "Rules:\n"
    "- Only extract entities explicitly stated in the claim text. Do not infer or hallucinate.\n"
    "- Return empty lists for entity types not present in the claim.\n"
    "- Each entity should appear exactly once in its respective list.\n"
    "- Respond with only the JSON object, no other text.\n"
)


class EntityExtractionResult(BaseModel):
    """Structured result from Claude entity extraction."""

    persons: list[str]
    organizations: list[str]
    dates: list[str]
    locations: list[str]
    statistics: list[str]


class LLMUnavailableError(Exception):
    """Anthropic API call failed (retryable)."""


async def extract_entities_llm(
    claim: str,
    client: AsyncAnthropic,
    model_id: str = "claude-haiku-4-5",
    max_tokens: int = 512,
) -> EntityExtractionResult:
    """Extract named entities from a claim using Claude LLM.

    Returns an EntityExtractionResult with five entity lists.
    Raises LLMUnavailableError on API failures.
    """
    import anthropic as anthropic_lib

    try:
        response = await client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            temperature=0,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Claim: {claim}"}],
        )
    except (anthropic_lib.APIConnectionError, anthropic_lib.RateLimitError) as exc:
        raise LLMUnavailableError(f"Anthropic API error: {exc}") from exc
    except anthropic_lib.AuthenticationError as exc:
        raise LLMUnavailableError(f"Anthropic auth error: {exc}") from exc

    raw_text = response.content[0].text.strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON response: %s", raw_text[:200])
        return EntityExtractionResult(
            persons=[], organizations=[], dates=[], locations=[], statistics=[]
        )

    try:
        return EntityExtractionResult.model_validate(data)
    except Exception:
        logger.warning("LLM response failed validation: %s", raw_text[:200])
        return EntityExtractionResult(
            persons=[], organizations=[], dates=[], locations=[], statistics=[]
        )
