"""Intake agent -- URL-based content extraction, claim decomposition,
domain classification, and entity extraction.

Uses LangChain's create_agent with LLM-driven tool selection.
The agent orchestrates four tools guided by a system prompt that encodes
the two-phase intake workflow.

Pipeline integration (PipelineState translation, observation publishing)
is handled by the pipeline node wrapper in ``pipeline/nodes/``, not here.
"""

from __future__ import annotations

import logging
import os
from typing import Any

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
article text, title, and publication date. If fetching fails, stop immediately \
-- the URL is rejected.

2. **Decompose claims** using the decompose_claims tool. Pass the article text \
and title from the fetch result. This extracts up to 5 factual claims suitable \
for fact-checking. If no claims are found, stop -- the article has no verifiable \
factual content.

3. **Return claims** to the user for selection. Report the extracted claims with \
their supporting quotes and citations.

**Phase B: Selected claim analysis**

4. **Classify the domain** using the classify_domain tool. Pass the selected \
claim text. This determines which domain the claim falls under (HEALTHCARE, \
ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER).

5. **Extract entities** using the extract_entities tool. Pass the selected \
claim text to extract persons, organizations, dates, locations, and statistics.

After completing all steps, report your findings."""


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
    decompose_model = ChatAnthropic(
        model=DECOMPOSE_MODEL,
        max_tokens=2048,
        temperature=0,
    )

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
    async def fetch_content(url: str) -> dict[str, Any]:
        """Fetch and extract content from a source URL.

        Downloads the web page, extracts the main article text using trafilatura
        (with BeautifulSoup fallback), and returns the title, publication date,
        extracted text, and word count.

        Args:
            url: The source URL to fetch content from.
        """
        from swarm_reasoning.agents.intake.tools import fetch_content
        from swarm_reasoning.agents.intake.tools.fetch_content import FetchError

        share_progress("Fetching article content...")
        try:
            result = await fetch_content.fetch_content(url)
            share_progress(f"Content extracted: {result.word_count} words")
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
            share_progress(f"Fetch error: {fe.reason}")
            return {"success": False, "url": url, "error": fe.reason}

    @tool
    async def decompose_claims(
        article_text: str, article_title: str, config: RunnableConfig
    ) -> dict[str, Any]:
        """Extract up to 5 factual claims from article text.

        Analyzes the article content using LLM-powered claim extraction.
        Returns structured claims with supporting quotes and citations.

        Args:
            article_text: The extracted article body text.
            article_title: The article title for context.
        """
        from swarm_reasoning.agents.intake.tools import decompose_claims

        share_progress("Analyzing article for factual claims...")
        claims = await decompose_claims.decompose_and_parse(
            article_text=article_text,
            article_title=article_title,
            model=decompose_model,
            config=config,
        )
        share_progress(f"Found {len(claims)} claims for review")

        result: dict[str, Any] = {
            "claims": [claim.model_dump() for claim in claims],
            "article_title": article_title,
            "article_date": None,
            "claim_count": len(claims),
        }

        if not claims:
            result["error"] = "NO_FACTUAL_CLAIMS"

        return result

    @tool
    async def classify_domain(claim_text: str, config: RunnableConfig) -> dict[str, str]:
        """Classify a claim into a domain category using LLM analysis.

        Returns one of: HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER.

        Args:
            claim_text: The claim text to classify.
        """
        from swarm_reasoning.agents.intake.tools import domain_classification

        domain = await domain_classification.classify(claim_text, classify_model, config)
        share_progress(f"Domain classified: {domain}")
        return {"domain": domain}

    @tool
    async def extract_entities(claim_text: str, config: RunnableConfig) -> dict[str, list[str]]:
        """Extract named entities from claim text using LLM-powered NER.

        Extracts persons, organizations, dates, locations, and statistics.
        Only call this tool if the claim passed the check-worthiness gate.

        Args:
            claim_text: The normalized claim text to extract entities from.
        """
        from swarm_reasoning.agents.intake.tools import entity_extractor

        result = await entity_extractor.extract(claim_text, entity_model, config)
        share_progress(f"Entities extracted: {len(result)} found")
        return result.to_dict()

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

    tools = [
        fetch_content,
        decompose_claims,
        classify_domain,
        extract_entities,
    ]

    # Future: create_agent also accepts `store=` (BaseStore-conforming) and
    # `checkpointer=` (BaseCheckpointSaver-conforming). A Redis-backed BaseStore
    # could replace bespoke persistence; a checkpointer would give us resume-on-
    # crash fault tolerance for in-flight runs.
    #   https://reference.langchain.com/python/langchain-core/stores/BaseStore
    #   https://reference.langchain.com/python/langgraph.checkpoint/base/BaseCheckpointSaver
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        response_format=IntakeOutput,
        name=AGENT_NAME,
    )
