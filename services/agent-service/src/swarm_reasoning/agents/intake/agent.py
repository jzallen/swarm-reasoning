"""Intake agent -- ReAct agent for claim validation, domain classification,
and entity extraction.

Uses LangGraph's create_agent with LLM-driven tool selection.
The agent orchestrates three tools guided by a system prompt that encodes
the intake workflow.

Pipeline integration (PipelineState translation, observation publishing)
is handled by the pipeline node wrapper in ``pipeline/nodes/``, not here.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.prebuilt import create_agent

from swarm_reasoning.agents.intake.models import IntakeOutput
from swarm_reasoning.agents.intake.tools.claim_intake import (
    ValidationError,
    normalize_date,
    validate_claim_text,
    validate_source_url,
)
from swarm_reasoning.agents.intake.tools.domain_classification import (
    DOMAIN_VOCABULARY,
    build_prompt,
)
from swarm_reasoning.agents.intake.tools.entity_extractor import (
    EntityExtractionResult,
    _SYSTEM_PROMPT as _ENTITY_SYSTEM_PROMPT,
)
from swarm_reasoning.agents.intake.tools.fetch_content import (
    FetchError,
)
from swarm_reasoning.agents.intake.tools.fetch_content import (
    fetch_content as _fetch_content,
)
from swarm_reasoning.temporal.errors import MissingApiKeyError

logger = logging.getLogger(__name__)

AGENT_NAME = "intake"
CLASSIFY_MODEL = "claude-sonnet-4-6"

_CLASSIFY_SYSTEM_PROMPT = (
    "You are a domain classifier for a fact-checking system. "
    "Your task is to categorize the given claim into exactly one of the following domains:\n\n"
    "HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER\n\n"
    "Respond with exactly one word -- the domain code. "
    "Do not include punctuation, explanation, or any other text."
)

# ---------------------------------------------------------------------------
# Model constants
# ---------------------------------------------------------------------------

AGENT_MODEL = "claude-sonnet-4-6"
DECOMPOSE_MODEL = "claude-sonnet-4-6"
CLASSIFY_MODEL = "claude-sonnet-4-6"
ENTITY_MODEL = "claude-haiku-4-5"

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

2. **Fetch source content** using the fetch_source_content tool if a source URL \
was provided. Pass the URL to retrieve the article text, title, and publication \
date. If fetching fails, note the error but continue -- source content is optional.

3. **Classify the domain** using the classify_domain tool. This determines \
which domain the claim falls under (HEALTHCARE, ECONOMICS, POLICY, etc.).

4. **Extract entities** using the extract_entities tool. Pass the claim text.

After completing all steps, report your findings."""


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


# classify_domain is defined inside build_intake_agent() as a closure
# over the ChatAnthropic model instance (see below).


@tool
async def fetch_source_content(url: str) -> dict[str, Any]:
    """Fetch and extract content from a source URL.

    Downloads the web page, extracts the main article text using trafilatura
    (with BeautifulSoup fallback), and returns the title, publication date,
    extracted text, and word count.

    Args:
        url: The source URL to fetch content from.
    """
    writer = get_stream_writer()
    writer({"type": "progress", "message": "Fetching article content..."})
    try:
        result = await _fetch_content(url)
        writer(
            {
                "type": "progress",
                "message": f"Content extracted: {result.word_count} words",
            }
        )
        return {
            "success": True,
            "url": result.url,
            "title": result.title,
            "date": result.date,
            "text": result.text,
            "word_count": result.word_count,
            "extraction_method": result.extraction_method,
        }
    except FetchError as fe:
        writer({"type": "progress", "message": f"Fetch error: {fe.reason}"})
        return {"success": False, "url": url, "error": fe.reason}


# extract_entities is defined inside build_intake_agent() as a closure
# over the ChatAnthropic model instance (see below).


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------


def build_intake_agent(model=None):
    """Build the intake ReAct agent graph.

    Tools that require LLM sub-calls (``classify_domain``, ``extract_entities``)
    receive their ``ChatAnthropic`` instance via closure and accept
    ``RunnableConfig`` for tracing propagation.

    Args:
        model: Optional ChatAnthropic instance for the orchestrator. If None,
            one is created from the ANTHROPIC_API_KEY environment variable.

    Returns:
        A compiled LangGraph CompiledStateGraph that processes claims through
        the intake pipeline via LLM-driven tool selection. Invoke with::

            result = await agent.ainvoke({
                "messages": [("user", "Process this claim: ...")]
            })

        The result dict contains ``structured_response`` (an IntakeOutput)
        and ``messages`` (the full conversation trace).
    """
    classify_model = ChatAnthropic(
        model=CLASSIFY_MODEL,
        max_tokens=10,
        temperature=0,
    )

    entity_model = ChatAnthropic(
        model=ENTITY_MODEL,
        max_tokens=512,
        temperature=0,
    )

    @tool
    async def classify_domain(claim_text: str, config: RunnableConfig) -> dict[str, str]:
        """Classify a claim into a domain category using LLM analysis.

        Returns one of: HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER.

        Args:
            claim_text: The claim text to classify.
        """
        domain: str | None = None

        for attempt in range(2):
            try:
                prompt = build_prompt(claim_text, retry=(attempt > 0))
                messages = [
                    SystemMessage(content=_CLASSIFY_SYSTEM_PROMPT),
                    HumanMessage(content=prompt[0]["content"]),
                ]
                response = await classify_model.ainvoke(messages, config=config)
                result = response.content.strip().upper()
            except Exception:
                logger.warning(
                    "Domain classification error (attempt %d)",
                    attempt + 1,
                    exc_info=True,
                )
                continue

            if result in DOMAIN_VOCABULARY:
                domain = result
                break

        domain = domain or "OTHER"

        writer = get_stream_writer()
        writer({"type": "progress", "message": f"Domain classified: {domain}"})

        return {"domain": domain}

    @tool
    async def extract_entities(claim_text: str, config: RunnableConfig) -> dict[str, list[str]]:
        """Extract named entities from claim text using LLM-powered NER.

        Extracts persons, organizations, dates, locations, and statistics.
        Only call this tool if the claim passed the check-worthiness gate.

        Args:
            claim_text: The normalized claim text to extract entities from.
        """
        empty = EntityExtractionResult(
            persons=[], organizations=[], dates=[], locations=[], statistics=[]
        )

        messages = [
            SystemMessage(content=_ENTITY_SYSTEM_PROMPT),
            HumanMessage(content=f"Claim: {claim_text}"),
        ]
        try:
            response = await entity_model.ainvoke(messages, config=config)
            raw_text = response.content.strip()
        except Exception:
            logger.warning("Entity extraction LLM error", exc_info=True)
            raw_text = None

        result = empty
        if raw_text:
            try:
                data = json.loads(raw_text)
                result = EntityExtractionResult.model_validate(data)
            except (json.JSONDecodeError, Exception):
                logger.warning(
                    "Entity extraction response parse error: %s", raw_text[:200]
                )

        entities = {
            "persons": result.persons,
            "organizations": result.organizations,
            "dates": result.dates,
            "locations": result.locations,
            "statistics": result.statistics,
        }

        writer = get_stream_writer()
        entity_count = sum(len(v) for v in entities.values())
        writer(
            {"type": "progress", "message": f"Entities extracted: {entity_count} found"}
        )

        return entities

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

    tools = [validate_claim, fetch_source_content, classify_domain, extract_entities]

    return create_agent(
        model=model,
        tools=tools,
        prompt=SYSTEM_PROMPT,
        response_format=IntakeOutput,
        name=AGENT_NAME,
    )
