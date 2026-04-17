"""Domain classification for the intake agent.

Encapsulates the full classify step: structured LLM call constrained to the
controlled vocabulary, with fallback to ``OTHER`` on any error.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

if TYPE_CHECKING:
    from langchain_anthropic import ChatAnthropic
    from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a domain classifier for a fact-checking system. Your task is to categorize the given \
claim into exactly one of the following domains:

HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER

Respond with exactly one word -- the domain code."""

_FALLBACK_DOMAIN = "OTHER"

Domain = Literal[
    "HEALTHCARE", "ECONOMICS", "POLICY", "SCIENCE", "ELECTION", "CRIME", "OTHER"
]


class _DomainResult(BaseModel):
    domain: Domain


async def classify(
    claim_text: str,
    model: ChatAnthropic,
    config: RunnableConfig,
) -> str:
    """Classify ``claim_text`` into one of the controlled domains.

    Uses the model's structured-output mode to constrain the response to the
    ``Domain`` literal; returns ``"OTHER"`` on any LLM or validation failure.
    """
    structured = model.with_structured_output(_DomainResult)
    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=f"Claim: {claim_text}"),
    ]
    try:
        result = await structured.ainvoke(messages, config=config)
    except Exception:
        logger.warning("Domain classification failed, using fallback", exc_info=True)
        return _FALLBACK_DOMAIN
    return result.domain
