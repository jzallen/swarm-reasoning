"""Intake agent -- URL-based content extraction, claim decomposition,
domain classification, and entity extraction.

Uses LangChain's create_agent with LLM-driven tool selection. The LLM
orchestrates which tools to call; it does NOT marshal the final
IntakeOutput. Tool outputs are captured into a per-invocation
accumulator and IntakeOutput is assembled deterministically after the
agent completes. This avoids truncation when the LLM would otherwise
echo all fields back as JSON within ``max_tokens``.

Pipeline integration (PipelineState translation, observation publishing)
is handled by the pipeline node wrapper in ``pipeline/nodes/``, not here.
"""

from __future__ import annotations

import logging
import os
from typing import Any, AsyncIterator

from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from swarm_reasoning.agents.intake.models import IntakeOutput
from swarm_reasoning.agents.messaging import share_progress
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
# Deterministic IntakeOutput assembly
# ---------------------------------------------------------------------------


def _assemble_output(acc: dict[str, Any]) -> IntakeOutput:
    """Build an IntakeOutput from captured tool outputs.

    Only fields that have a captured value are populated (TypedDict
    ``total=False``). On error capture, returns an output containing only
    the error code (matching the prior rejection contract).
    """
    if "error" in acc:
        return {"error": acc["error"]}  # type: ignore[typeddict-item]

    out: IntakeOutput = {}
    fetch = acc.get("fetch")
    if fetch is not None:
        out["article_text"] = fetch["text"]
        if fetch.get("title") is not None:
            out["article_title"] = fetch["title"]
        out["article_author"] = fetch.get("author")
        if fetch.get("publisher") is not None:
            out["article_publisher"] = fetch["publisher"]
        out["article_published_at"] = fetch.get("published_at")
        out["article_accessed_at"] = fetch["accessed_at"]
    if "extracted_claims" in acc:
        out["extracted_claims"] = acc["extracted_claims"]
    if "domain" in acc:
        out["domain"] = acc["domain"]
    if "entities" in acc:
        out["entities"] = acc["entities"]
    return out


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------


class _IntakeAgent:
    """Wrapper exposing ``ainvoke``/``astream`` over a per-invocation agent.

    Each invocation builds a fresh ``create_agent`` graph whose tools write
    into a local accumulator. After the underlying agent completes, the
    accumulator is assembled into an ``IntakeOutput`` and injected into the
    final state as ``structured_response`` -- matching the prior contract
    expected by the CLI and pipeline node consumers.
    """

    def __init__(
        self,
        orchestrator_model: ChatAnthropic,
        decompose_model: ChatAnthropic,
        classify_model: ChatAnthropic,
        entity_model: ChatAnthropic,
    ) -> None:
        self._orchestrator_model = orchestrator_model
        self._decompose_model = decompose_model
        self._classify_model = classify_model
        self._entity_model = entity_model

    def _build_tools(self, acc: dict[str, Any]) -> list[Any]:
        decompose_model = self._decompose_model
        classify_model = self._classify_model
        entity_model = self._entity_model

        @tool
        async def fetch_content(url: str) -> dict[str, Any]:
            """Fetch and extract content from a source URL.

            Downloads the web page, extracts the main article text using
            trafilatura (with BeautifulSoup fallback), and returns the
            article text, title, author, publisher, publication timestamp
            (ISO-8601), access timestamp (ISO-8601 UTC), and word count.

            Args:
                url: The source URL to fetch content from.
            """
            from swarm_reasoning.agents.intake.tools import fetch_content as fetch_mod
            from swarm_reasoning.agents.intake.tools.fetch_content import FetchError

            share_progress("Fetching article content...")
            try:
                result = await fetch_mod.fetch_content(url)
            except FetchError as fe:
                share_progress(f"Fetch error: {fe.reason}")
                acc["error"] = fe.reason
                return {"success": False, "url": url, "error": fe.reason}

            share_progress(f"Content extracted: {result.word_count} words")
            acc["fetch"] = {
                "url": result.url,
                "title": result.title,
                "text": result.text,
                "author": result.author,
                "publisher": result.publisher,
                "published_at": result.published_at,
                "accessed_at": result.accessed_at,
            }
            return {
                "success": True,
                "url": result.url,
                "title": result.title,
                "text": result.text,
                "word_count": result.word_count,
                "extraction_method": result.extraction_method,
                "article_author": result.author,
                "article_publisher": result.publisher,
                "article_published_at": result.published_at,
                "article_accessed_at": result.accessed_at,
            }

        @tool
        async def decompose_claims(
            article_text: str, article_title: str, config: RunnableConfig
        ) -> dict[str, Any]:
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
                config=config,
            )
            share_progress(f"Found {len(claims)} claims for review")

            claim_dicts = [claim.model_dump() for claim in claims]
            if not claims:
                acc["error"] = "NO_FACTUAL_CLAIMS"
            else:
                acc["extracted_claims"] = claim_dicts

            result: dict[str, Any] = {
                "claims": claim_dicts,
                "claim_count": len(claims),
            }
            if not claims:
                result["error"] = "NO_FACTUAL_CLAIMS"
            return result

        @tool
        async def classify_domain(claim_text: str, config: RunnableConfig) -> dict[str, str]:
            """Classify a claim into a domain category using LLM analysis.

            Returns one of: HEALTHCARE, ECONOMICS, POLICY, SCIENCE,
            ELECTION, CRIME, OTHER.

            Args:
                claim_text: The claim text to classify.
            """
            from swarm_reasoning.agents.intake.tools import domain_classification

            domain = await domain_classification.classify(claim_text, classify_model, config)
            share_progress(f"Domain classified: {domain}")
            acc["domain"] = domain
            return {"domain": domain}

        @tool
        async def extract_entities(claim_text: str, config: RunnableConfig) -> dict[str, list[str]]:
            """Extract named entities from claim text using LLM-powered NER.

            Extracts persons, organizations, dates, locations, and
            statistics. Only call this tool if the claim passed the
            check-worthiness gate.

            Args:
                claim_text: The normalized claim text to extract entities from.
            """
            from swarm_reasoning.agents.intake.tools import entity_extractor

            result = await entity_extractor.extract(claim_text, entity_model, config)
            share_progress(f"Entities extracted: {len(result)} found")
            entities = result.to_dict()
            acc["entities"] = entities
            return entities

        return [fetch_content, decompose_claims, classify_domain, extract_entities]

    def _compile(self, acc: dict[str, Any]) -> Any:
        tools = self._build_tools(acc)
        return create_agent(
            model=self._orchestrator_model,
            tools=tools,
            system_prompt=SYSTEM_PROMPT,
            name=AGENT_NAME,
        )

    async def ainvoke(
        self, inputs: dict[str, Any], config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        acc: dict[str, Any] = {}
        agent = self._compile(acc)
        result = await agent.ainvoke(inputs, config=config)
        result["structured_response"] = _assemble_output(acc)
        return result

    async def astream(
        self,
        inputs: dict[str, Any],
        stream_mode: str | list[str] | None = None,
        config: RunnableConfig | None = None,
    ) -> AsyncIterator[Any]:
        acc: dict[str, Any] = {}
        agent = self._compile(acc)

        multi_mode = isinstance(stream_mode, list)
        last_values: dict[str, Any] | None = None

        async for item in agent.astream(inputs, stream_mode=stream_mode, config=config):
            if multi_mode and isinstance(item, tuple) and item[0] == "values":
                last_values = item[1]
            elif not multi_mode and stream_mode == "values":
                last_values = item
            yield item

        structured = _assemble_output(acc)
        if last_values is None:
            # Underlying agent produced no "values" payload (unusual); emit a
            # minimal synthetic final payload so consumers still see the result.
            final = {"structured_response": structured}
        else:
            final = dict(last_values)
            final["structured_response"] = structured
        yield ("values", final) if multi_mode else final


def build_intake_agent(model: ChatAnthropic | None = None) -> _IntakeAgent:
    """Build the intake agent.

    Tools that require LLM sub-calls (``decompose_claims``,
    ``classify_domain``, ``extract_entities``) receive their
    ``ChatAnthropic`` instance via closure and accept ``RunnableConfig``
    for tracing propagation.

    Args:
        model: Optional ChatAnthropic instance for the orchestrator. If None,
            one is created from the ANTHROPIC_API_KEY environment variable.

    Returns:
        An ``_IntakeAgent`` wrapper exposing ``ainvoke`` and ``astream``. Each
        call runs a fresh underlying ``create_agent`` graph and injects a
        deterministically-assembled ``IntakeOutput`` into the final state as
        ``structured_response``. Invoke with::

            result = await agent.ainvoke({
                "messages": [("user", "Process this URL: ...")]
            })

        The result dict contains ``structured_response`` (an ``IntakeOutput``)
        and ``messages`` (the full conversation trace).
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

    return _IntakeAgent(
        orchestrator_model=model,
        decompose_model=decompose_model,
        classify_model=classify_model,
        entity_model=entity_model,
    )
