"""Intake agent -- URL-based content extraction, claim decomposition,
domain classification, and entity extraction.

Uses LangChain v1's ``state_schema`` + ``Command(update=...)`` pattern.
Tools write typed fields directly into the agent's ``IntakeAgentState``
via ``Command``; the LLM never re-serializes the structured result, so
there is no truncation risk from ``max_tokens`` echoing tool payloads
back as JSON.

Pipeline integration (PipelineState translation, observation publishing)
lives in the pipeline node wrapper in ``pipeline/nodes/``, not here.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from langchain.agents import AgentState, create_agent
from langchain.tools import ToolRuntime
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command
from typing_extensions import NotRequired

from swarm_reasoning.agents.messaging import share_progress
from swarm_reasoning.agents.web import (
    BeautifulSoupStrategy,
    FetchCache,
    FetchErr,
    FetchOk,
    TrafilaturaStrategy,
    WebContentExtractor,
    hostname_fallback,
)
from swarm_reasoning.temporal.errors import MissingApiKeyError

logger = logging.getLogger(__name__)

AGENT_NAME = "intake"

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
process a URL submission through a two-phase pipeline: first extract claims from \
the article, then analyze a user-selected claim.

Follow this workflow IN ORDER:

**Phase A: URL to claims**

1. **Fetch content** using the fetch_content tool. Pass the URL to retrieve the \
article text, title, author, publisher, publication timestamp, and access \
timestamp. If fetching fails, stop immediately -- the URL is rejected.

2. **Decompose claims** using the decompose_claims tool. Pass the article text \
and title from the fetch result. This extracts up to 5 factual claims suitable \
for fact-checking. If no claims are found, stop -- the article has no verifiable \
factual content.

3. **Return claims** to the user for selection. Report the extracted claims with \
their supporting quotes and any in-text attribution.

**Phase B: Selected claim analysis**

4. **Classify the domain** using the classify_domain tool. Pass the selected \
claim text. This determines which domain the claim falls under (HEALTHCARE, \
ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER).

5. **Extract entities** using the extract_entities tool. Pass the selected \
claim text to extract persons, organizations, dates, locations, and statistics.

After completing all steps, reply with a one-line confirmation. Do NOT \
attempt to echo tool outputs back as JSON -- the system captures tool \
results directly."""


# ---------------------------------------------------------------------------
# Agent state schema
# ---------------------------------------------------------------------------


class IntakeAgentState(AgentState):
    """State schema carrying intake tool outputs directly.

    Tools write their structured results into these fields via
    ``Command(update=...)``. The LLM only sees brief confirmation
    ``ToolMessage``s, so structured payloads are never at risk of
    truncation on echo.
    """

    article_text: NotRequired[str]
    article_title: NotRequired[str]
    article_author: NotRequired[str | None]
    article_publisher: NotRequired[str]
    article_published_at: NotRequired[str | None]
    article_accessed_at: NotRequired[str]
    extracted_claims: NotRequired[list[dict]]
    domain: NotRequired[str]
    entities: NotRequired[dict[str, list[str]]]
    error: NotRequired[str]


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------


def build_intake_agent(model: ChatAnthropic | None = None) -> Any:
    """Build the intake agent as a compiled LangGraph.

    Tools that require LLM sub-calls (``decompose_claims``,
    ``classify_domain``, ``extract_entities``) receive their
    ``ChatAnthropic`` instance via closure; they read their per-call
    ``RunnableConfig`` from the injected ``ToolRuntime``.

    Args:
        model: Optional ChatAnthropic instance for the orchestrator. If
            ``None``, one is created from the ``ANTHROPIC_API_KEY``
            environment variable.

    Returns:
        A compiled LangGraph whose state is ``IntakeAgentState``. Invoke
        with::

            result = await agent.ainvoke({
                "messages": [("user", "Process this URL: ...")]
            })
    """
    decompose_model = ChatAnthropic(
        model=DECOMPOSE_MODEL,
        max_tokens=2048,
        temperature=0,
    )

    classify_model = ChatAnthropic(
        model=CLASSIFY_MODEL,
        max_tokens=256,
        temperature=0,
    )

    entity_model = ChatAnthropic(
        model=ENTITY_MODEL,
        max_tokens=512,
        temperature=0,
    )

    if model is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise MissingApiKeyError("ANTHROPIC_API_KEY is required for intake agent")
        model = ChatAnthropic(
            model=AGENT_MODEL,
            max_tokens=1024,
            temperature=0,
            api_key=api_key,
        )

    extractor = WebContentExtractor(
        strategies=[TrafilaturaStrategy(), BeautifulSoupStrategy()],
        cache=FetchCache(),
    )
    min_word_count = 50

    @tool
    async def fetch_content(url: str, runtime: ToolRuntime) -> Command:
        """Fetch and extract content from a source URL.

        Downloads the web page, extracts the main article text using
        trafilatura (with BeautifulSoup fallback), and returns the
        article text, title, author, publisher, publication timestamp
        (ISO-8601), access timestamp (ISO-8601 UTC), and word count.

        Args:
            url: The source URL to fetch content from.
        """
        share_progress("Fetching article content...")
        result = await extractor.fetch(url)
        match result:
            case FetchErr(reason=code):
                share_progress(f"Fetch error: {code}")
                return Command(
                    update={
                        "error": code,
                        "messages": [
                            ToolMessage(
                                content=f"Fetch failed: {code}",
                                tool_call_id=runtime.tool_call_id,
                            )
                        ],
                    }
                )
            case FetchOk(document=doc):
                word_count = len(doc.text.split())
                if word_count < min_word_count:
                    code = f"CONTENT_TOO_SHORT:{word_count}"
                    share_progress(f"Fetch error: {code}")
                    return Command(
                        update={
                            "error": code,
                            "messages": [
                                ToolMessage(
                                    content=f"Fetch failed: {code}",
                                    tool_call_id=runtime.tool_call_id,
                                )
                            ],
                        }
                    )
                share_progress(f"Content extracted: {word_count} words")
                return Command(
                    update={
                        "article_text": doc.text,
                        "article_title": doc.title or "",
                        "article_author": doc.author,
                        "article_publisher": doc.publisher or hostname_fallback(url) or "",
                        "article_published_at": doc.published_at,
                        "article_accessed_at": doc.accessed_at,
                        "messages": [
                            ToolMessage(
                                content=(
                                    f"Fetched {word_count} words from "
                                    f"{doc.url} (title: {doc.title!r})."
                                ),
                                tool_call_id=runtime.tool_call_id,
                            )
                        ],
                    }
                )

    @tool
    async def decompose_claims(
        article_text: str, article_title: str, runtime: ToolRuntime
    ) -> Command:
        """Extract up to 5 factual claims from article text.

        Analyzes the article content using LLM-powered claim
        extraction. Returns structured claims with supporting quotes
        and optional in-text attribution (when the article body
        credits a named external source).

        Args:
            article_text: The extracted article body text.
            article_title: The article title for context.
        """
        from swarm_reasoning.agents.intake.tools import decompose_claims as decompose_mod

        share_progress("Analyzing article for factual claims...")
        claims = await decompose_mod.decompose_and_parse(
            article_text=article_text,
            article_title=article_title,
            model=decompose_model,
            config=runtime.config,
        )
        share_progress(f"Found {len(claims)} claims for review")

        if not claims:
            return Command(
                update={
                    "error": "NO_FACTUAL_CLAIMS",
                    "messages": [
                        ToolMessage(
                            content="No factual claims found in article.",
                            tool_call_id=runtime.tool_call_id,
                        )
                    ],
                }
            )

        claim_dicts = [claim.model_dump() for claim in claims]
        return Command(
            update={
                "extracted_claims": claim_dicts,
                "messages": [
                    ToolMessage(
                        content=f"Extracted {len(claim_dicts)} claim(s).",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    @tool
    async def classify_domain(claim_text: str, runtime: ToolRuntime) -> Command:
        """Classify a claim into a domain category using LLM analysis.

        Returns one of: HEALTHCARE, ECONOMICS, POLICY, SCIENCE,
        ELECTION, CRIME, OTHER.

        Args:
            claim_text: The claim text to classify.
        """
        from swarm_reasoning.agents.intake.tools import domain_classification

        domain = await domain_classification.classify(claim_text, classify_model, runtime.config)
        share_progress(f"Domain classified: {domain}")
        return Command(
            update={
                "domain": domain,
                "messages": [
                    ToolMessage(
                        content=f"Domain: {domain}",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    @tool
    async def extract_entities(claim_text: str, runtime: ToolRuntime) -> Command:
        """Extract named entities from claim text using LLM-powered NER.

        Extracts persons, organizations, dates, locations, and
        statistics. Only call this tool if the claim passed the
        check-worthiness gate.

        Args:
            claim_text: The normalized claim text to extract entities from.
        """
        from swarm_reasoning.agents.intake.tools import entity_extractor

        result = await entity_extractor.extract(claim_text, entity_model, runtime.config)
        share_progress(f"Entities extracted: {len(result)} found")
        entities = result.to_dict()
        return Command(
            update={
                "entities": entities,
                "messages": [
                    ToolMessage(
                        content=f"Extracted {len(result)} entit(ies).",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    return create_agent(
        model=model,
        tools=[fetch_content, decompose_claims, classify_domain, extract_entities],
        system_prompt=SYSTEM_PROMPT,
        state_schema=IntakeAgentState,
        name=AGENT_NAME,
    )
