"""Intake agent -- ReAct agent for claim validation, domain classification,
normalization, check-worthiness scoring, and entity extraction.

Uses LangGraph's create_react_agent with LLM-driven tool selection.
The agent orchestrates five tools guided by a system prompt that encodes
the intake workflow. The LLM decides tool order and handles branching
(e.g. skipping entity extraction when a claim is not check-worthy).

Pipeline integration (PipelineState translation, observation publishing)
is handled by the pipeline node wrapper in ``pipeline/nodes/``, not here.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from swarm_reasoning.agents.intake.models import IntakeOutput
from swarm_reasoning.agents.intake.tools.claim_intake import (
    ValidationError,
    normalize_date,
    validate_claim_text,
    validate_source_url,
)
from swarm_reasoning.agents.intake.tools.domain_cls import (
    DOMAIN_VOCABULARY,
    build_prompt,
    call_claude,
)
from swarm_reasoning.agents.intake.tools.entity_extractor import extract_entities_llm
from swarm_reasoning.agents.intake.tools.normalizer import normalize_claim_text
from swarm_reasoning.agents.intake.tools.scorer import score_claim_text
from swarm_reasoning.temporal.errors import MissingApiKeyError

logger = logging.getLogger(__name__)

AGENT_NAME = "intake"

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the intake agent in a multi-agent fact-checking system. Your job is to \
process a claim submission through a structured validation and analysis pipeline.

Follow this workflow IN ORDER:

1. **Validate the claim** using the validate_claim tool. Pass the claim text, \
and optionally the source URL and submission date if provided. If validation \
fails, stop immediately -- the claim is rejected.

2. **Classify the domain** using the classify_domain tool. This determines \
which domain the claim falls under (HEALTHCARE, ECONOMICS, POLICY, etc.).

3. **Normalize the claim** using the normalize_claim tool. This cleans up the \
text by removing hedging language, resolving pronouns, and standardizing formatting.

4. **Score check-worthiness** using the score_check_worthiness tool. Pass the \
NORMALIZED claim text from step 3. If the claim is NOT check-worthy (the tool \
will indicate this), skip entity extraction entirely.

5. **Extract entities** using the extract_entities tool, but ONLY if the claim \
passed the check-worthiness gate in step 4. Pass the normalized claim text.

After completing all applicable steps, report your findings."""


# ---------------------------------------------------------------------------
# Anthropic client factory (shared by LLM-powered tools)
# ---------------------------------------------------------------------------


def _get_anthropic_client():
    """Create an AsyncAnthropic client from the environment."""
    from anthropic import AsyncAnthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise MissingApiKeyError("ANTHROPIC_API_KEY is required for intake agent")
    return AsyncAnthropic(api_key=api_key)


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


@tool
async def validate_claim(
    claim_text: str,
    source_url: str = "",
    submission_date: str = "",
) -> dict[str, Any]:
    """Validate a claim submission for structural correctness.

    Checks claim text length (5-2000 chars), URL format if provided,
    and date parseability if provided.

    Args:
        claim_text: The raw claim text to validate.
        source_url: Optional source URL for the claim. Pass empty string
            if none.
        submission_date: Optional submission date in any parseable format.
            Pass empty string if none.
    """
    try:
        validate_claim_text(claim_text)
        if source_url:
            validate_source_url(source_url)
        normalized_date = None
        if submission_date:
            normalized_date = normalize_date(submission_date)
        return {
            "valid": True,
            "claim_text": claim_text.strip(),
            "source_url": source_url or None,
            "normalized_date": normalized_date,
        }
    except ValidationError as ve:
        return {"valid": False, "error": ve.reason}


@tool
async def classify_domain(claim_text: str) -> dict[str, str]:
    """Classify a claim into a domain category using LLM analysis.

    Returns one of: HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER.

    Args:
        claim_text: The claim text to classify.
    """
    import anthropic as anthropic_lib

    client = _get_anthropic_client()
    domain: str | None = None

    for attempt in range(2):
        try:
            prompt = build_prompt(claim_text, retry=(attempt > 0))
            result = await call_claude(client, prompt)
        except (
            anthropic_lib.AuthenticationError,
            anthropic_lib.APIConnectionError,
            anthropic_lib.RateLimitError,
        ):
            continue

        if result in DOMAIN_VOCABULARY:
            domain = result
            break

    return {"domain": domain or "OTHER"}


@tool
async def normalize_claim(claim_text: str) -> dict[str, Any]:
    """Normalize claim text by removing hedging language, resolving pronouns,
    and standardizing formatting.

    Args:
        claim_text: The raw claim text to normalize.
    """
    result = normalize_claim_text(claim_text)
    return {
        "normalized": result.normalized,
        "hedges_removed": result.hedges_removed,
        "pronouns_resolved": result.pronouns_resolved,
    }


@tool
async def score_check_worthiness(normalized_claim: str) -> dict[str, Any]:
    """Score a normalized claim for check-worthiness using a two-pass LLM protocol.

    Claims scoring >= 0.4 are considered check-worthy and should proceed to
    entity extraction. Claims below this threshold are NOT check-worthy.

    Args:
        normalized_claim: The normalized claim text (output of normalize_claim).
    """
    client = _get_anthropic_client()
    result = await score_claim_text(normalized_claim, client)
    return {
        "score": result.score,
        "rationale": result.rationale,
        "is_check_worthy": result.proceed,
    }


@tool
async def extract_entities(claim_text: str) -> dict[str, list[str]]:
    """Extract named entities from claim text using LLM-powered NER.

    Extracts persons, organizations, dates, locations, and statistics.
    Only call this tool if the claim passed the check-worthiness gate.

    Args:
        claim_text: The normalized claim text to extract entities from.
    """
    client = _get_anthropic_client()
    result = await extract_entities_llm(claim_text, client)
    return {
        "persons": result.persons,
        "organizations": result.organizations,
        "dates": result.dates,
        "locations": result.locations,
        "statistics": result.statistics,
    }


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------

TOOLS = [
    validate_claim,
    classify_domain,
    normalize_claim,
    score_check_worthiness,
    extract_entities,
]


def build_intake_agent(model=None):
    """Build the intake ReAct agent graph.

    Args:
        model: Optional ChatAnthropic instance. If None, one is created from
            the ANTHROPIC_API_KEY environment variable.

    Returns:
        A compiled LangGraph CompiledStateGraph that processes claims through
        the intake pipeline via LLM-driven tool selection. Invoke with::

            result = await agent.ainvoke({
                "messages": [("user", "Process this claim: ...")]
            })

        The result dict contains ``structured_response`` (an IntakeOutput)
        and ``messages`` (the full conversation trace).
    """
    if model is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise MissingApiKeyError("ANTHROPIC_API_KEY is required for intake agent")
        model = ChatAnthropic(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            temperature=0,
            api_key=api_key,
        )

    return create_react_agent(
        model=model,
        tools=TOOLS,
        prompt=SYSTEM_PROMPT,
        response_format=IntakeOutput,
        name=AGENT_NAME,
    )
