"""LLM-powered entity extraction using Claude structured output.

Extracts named entities (persons, organizations, dates, locations, statistics)
from claim text using Claude with structured JSON output.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

if TYPE_CHECKING:
    from langchain_anthropic import ChatAnthropic
    from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a named entity recognition (NER) system for a fact-checking pipeline. Extract \
entities from the given claim text and return a JSON object with these fields:

- "persons": list of named persons explicitly mentioned (canonical names)
- "organizations": list of named organizations explicitly mentioned
- "dates": list of dates or date ranges referenced. Use YYYYMMDD format for single dates and \
YYYYMMDD-YYYYMMDD for ranges where possible. If the exact date cannot be determined, return \
the original text.
- "locations": list of geographic locations explicitly mentioned
- "statistics": list of numeric claims or quantities (e.g. "87% of adults", "$1.2 trillion")

Rules:
- Only extract entities explicitly stated in the claim text.
- Return empty lists for entity types not present in the claim.
- Each entity should appear exactly once in its respective list.
"""


class EntityExtractionResult(BaseModel):
    """Structured result from Claude entity extraction."""

    persons: list[str]
    organizations: list[str]
    dates: list[str]
    locations: list[str]
    statistics: list[str]

    def __len__(self) -> int:
        """Total count of entities across all fields."""
        return (
            len(self.persons)
            + len(self.organizations)
            + len(self.dates)
            + len(self.locations)
            + len(self.statistics)
        )

    def to_dict(self) -> dict[str, list[str]]:
        """Serialize to a plain dict for tool-return payloads."""
        return self.model_dump()


def _empty_result() -> EntityExtractionResult:
    return EntityExtractionResult(
        persons=[], organizations=[], dates=[], locations=[], statistics=[]
    )


async def extract(
    claim_text: str,
    model: ChatAnthropic,
    config: RunnableConfig,
) -> EntityExtractionResult:
    """Extract named entities from ``claim_text`` via a structured LLM call.

    Returns an empty :class:`EntityExtractionResult` on any LLM or validation failure.
    """
    structured = model.with_structured_output(EntityExtractionResult)
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=f"Claim: {claim_text}"),
    ]
    try:
        return await structured.ainvoke(messages, config=config)
    except Exception:
        logger.warning("Entity extraction failed, returning empty result", exc_info=True)
        return _empty_result()
