"""Shared fixtures for intake agent integration tests.

Provides a compiled intake agent graph using FakeListChatModel for
deterministic, offline testing without real LLM API calls.
"""

from __future__ import annotations

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.prebuilt import create_react_agent

from swarm_reasoning.agents.intake.agent import (
    AGENT_NAME,
    SYSTEM_PROMPT,
    fetch_content,
)
from swarm_reasoning.agents.intake.models import IntakeOutput


def build_fake_intake_agent(
    orchestrator_responses: list[str] | None = None,
    decompose_responses: list[str] | None = None,
    classify_responses: list[str] | None = None,
    entity_responses: list[str] | None = None,
):
    """Build an intake agent graph with FakeListChatModel instances.

    Each model parameter accepts a list of canned string responses that
    the fake model returns in order. If None, a single empty response is
    used as default.

    Returns the compiled LangGraph CompiledStateGraph.
    """
    import json
    from typing import Any

    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_core.runnables import RunnableConfig
    from langchain_core.tools import tool
    from langgraph.config import get_stream_writer

    from swarm_reasoning.agents.intake.tools.decompose_claims import (
        decompose_and_parse,
    )
    from swarm_reasoning.agents.intake.tools.domain_classification import (
        DOMAIN_VOCABULARY,
        build_prompt,
    )
    from swarm_reasoning.agents.intake.tools.entity_extractor import (
        _SYSTEM_PROMPT as _ENTITY_SYSTEM_PROMPT,
    )
    from swarm_reasoning.agents.intake.tools.entity_extractor import (
        EntityExtractionResult,
    )

    orchestrator_model = FakeListChatModel(responses=orchestrator_responses or [""])
    decompose_model = FakeListChatModel(responses=decompose_responses or ['{"claims": []}'])
    classify_model = FakeListChatModel(responses=classify_responses or ["OTHER"])
    entity_model = FakeListChatModel(
        responses=entity_responses
        or ['{"persons": [], "organizations": [], "dates": [], "locations": [], "statistics": []}']
    )

    _CLASSIFY_SYSTEM_PROMPT = (
        "You are a domain classifier for a fact-checking system. "
        "Your task is to categorize the given claim into exactly one of the following domains:\n\n"
        "HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER\n\n"
        "Respond with exactly one word -- the domain code. "
        "Do not include punctuation, explanation, or any other text."
    )

    @tool
    async def decompose_claims(
        article_text: str, article_title: str, config: RunnableConfig
    ) -> dict[str, Any]:
        """Extract up to 5 factual claims from article text.

        Args:
            article_text: The extracted article body text.
            article_title: The article title for context.
        """
        writer = get_stream_writer()
        claims = await decompose_and_parse(
            article_text=article_text,
            article_title=article_title,
            model=decompose_model,
            config=config,
            writer=writer,
        )

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
        """Classify a claim into a domain category.

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
        """Extract named entities from claim text.

        Args:
            claim_text: The claim text to extract entities from.
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
            raw_text = None

        result = empty
        if raw_text:
            try:
                data = json.loads(raw_text)
                result = EntityExtractionResult.model_validate(data)
            except (json.JSONDecodeError, Exception):
                pass

        entities = {
            "persons": result.persons,
            "organizations": result.organizations,
            "dates": result.dates,
            "locations": result.locations,
            "statistics": result.statistics,
        }

        writer = get_stream_writer()
        entity_count = sum(len(v) for v in entities.values())
        writer({"type": "progress", "message": f"Entities extracted: {entity_count} found"})

        return entities

    tools = [
        fetch_content,
        decompose_claims,
        classify_domain,
        extract_entities,
    ]

    return create_react_agent(
        model=orchestrator_model,
        tools=tools,
        prompt=SYSTEM_PROMPT,
        response_format=IntakeOutput,
        name=AGENT_NAME,
    )


@pytest.fixture(scope="module")
def intake_agent():
    """Compiled intake agent graph with default FakeListChatModel responses.

    Override canned responses by calling ``build_fake_intake_agent()``
    directly with custom response lists for each model.
    """
    return build_fake_intake_agent()
