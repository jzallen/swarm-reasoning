"""Shared fixtures for intake agent integration tests.

Provides a compiled intake agent graph using FakeListChatModel for
deterministic, offline testing without real LLM API calls.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import (
    FakeListChatModel,
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage
from langgraph.prebuilt import create_react_agent

from swarm_reasoning.agents.intake.agent import (
    AGENT_NAME,
    SYSTEM_PROMPT,
    fetch_content,
)
from swarm_reasoning.agents.intake.models import IntakeOutput


def tool_call_message(
    tool_name: str, args: dict[str, Any], call_id: str | None = None
) -> AIMessage:
    """Build an AIMessage with a single tool_call for fake orchestrator scripts."""
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": tool_name,
                "args": args,
                "id": call_id or f"call_{uuid.uuid4().hex[:8]}",
                "type": "tool_call",
            }
        ],
    )


def build_tool_call_orchestrator(
    steps: list[AIMessage | dict[str, Any] | str],
) -> FakeMessagesListChatModel:
    """Build a fake orchestrator model that emits a scripted sequence of AIMessages.

    Each step is coerced into an AIMessage:
      - ``AIMessage`` — used verbatim
      - ``{"tool": name, "args": {...}, "id": str?}`` — AIMessage with one tool_call
      - ``str`` — AIMessage with that content and no tool_calls (terminal response)

    The returned model cycles through the responses in order on each invocation,
    which matches how ``create_react_agent`` drives the orchestrator through a
    fetch → decompose → classify → extract sequence, followed by a final
    terminal message.
    """
    messages: list[AIMessage] = []
    for step in steps:
        if isinstance(step, AIMessage):
            messages.append(step)
        elif isinstance(step, str):
            messages.append(AIMessage(content=step))
        elif isinstance(step, dict) and "tool" in step:
            messages.append(
                tool_call_message(
                    tool_name=step["tool"],
                    args=step.get("args", {}),
                    call_id=step.get("id"),
                )
            )
        else:
            raise ValueError(f"Unrecognized orchestrator step: {step!r}")
    return FakeMessagesListChatModel(responses=messages)


def build_fake_intake_agent(
    orchestrator_responses: list[str] | None = None,
    decompose_responses: list[str] | None = None,
    classify_responses: list[str] | None = None,
    entity_responses: list[str] | None = None,
    orchestrator_model: BaseChatModel | None = None,
):
    """Build an intake agent graph with fake chat models.

    ``decompose_responses``, ``classify_responses``, and ``entity_responses``
    each accept a list of canned string responses returned in order by a
    ``FakeListChatModel`` for the respective sub-tool LLM call.

    The orchestrator (which drives the react loop via tool calls) can be
    supplied in two mutually exclusive ways:

    - ``orchestrator_model``: a pre-built ``BaseChatModel`` — typically the
      result of :func:`build_tool_call_orchestrator` for scripted tool-call
      scenarios. Takes precedence when provided.
    - ``orchestrator_responses``: a list of string responses used to build a
      ``FakeListChatModel``. Suitable only for scenarios that do not require
      the orchestrator to emit tool calls.

    If neither is provided, a no-op orchestrator that returns an empty string
    is used.

    Returns the compiled LangGraph CompiledStateGraph.
    """
    import json

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

    if orchestrator_model is None:
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


# ---------------------------------------------------------------------------
# Canned HTML responses for httpx mock transport
# ---------------------------------------------------------------------------

NEWS_ARTICLE_HTML = """\
<!DOCTYPE html>
<html>
<head><title>Breaking News: Economy Grows 3.2%</title>
<meta property="article:published_time" content="2025-01-15" />
</head>
<body>
<article>
<h1>Economy Grows 3.2% in Q4, Exceeding Expectations</h1>
<p>The U.S. economy grew at an annualized rate of 3.2 percent in the fourth
quarter of 2024, the Bureau of Economic Analysis reported on Wednesday.
The growth rate exceeded economists' expectations of 2.8 percent.</p>
<p>Consumer spending, which accounts for roughly two-thirds of economic
activity, increased 3.7 percent. Business investment rose 5.1 percent,
driven by equipment spending and intellectual property products.</p>
<p>Federal Reserve Chair Jerome Powell said the data supports a cautious
approach to interest rate adjustments. The unemployment rate held steady
at 4.1 percent in December.</p>
<p>"The economy continues to show remarkable resilience," said Treasury
Secretary Janet Yellen in a statement. "These numbers reflect the strength
of American workers and businesses."</p>
<p>Inflation, as measured by the PCE price index, rose 2.4 percent in the
quarter, down from 2.7 percent in Q3. Core PCE, which excludes food and
energy, increased 2.5 percent.</p>
</article>
</body>
</html>
"""

OPINION_ARTICLE_HTML = """\
<!DOCTYPE html>
<html>
<head><title>Opinion: Why We Should Rethink Our Priorities</title></head>
<body>
<article>
<h1>Opinion: Why We Should Rethink Our Priorities</h1>
<p>I believe that our society has lost its way. We spend too much time
focused on material wealth and not enough on what truly matters.</p>
<p>In my view, the future will be shaped by those who dare to dream
differently. We should embrace change and welcome new perspectives.</p>
<p>Perhaps it is time we asked ourselves what kind of world we want to
leave for our children. The answer, I think, lies in compassion and
understanding rather than competition and greed.</p>
</article>
</body>
</html>
"""

NON_HTML_CONTENT = b"%PDF-1.4 fake pdf content bytes that are not HTML"

SHORT_CONTENT_HTML = """\
<!DOCTYPE html>
<html>
<head><title>Brief Note</title></head>
<body><p>This page has very few words.</p></body>
</html>
"""


def _build_mock_handler(
    custom_routes: dict[str, tuple[int, dict[str, str], bytes | str]] | None = None,
):
    """Build an httpx mock transport handler with canned URL routes.

    Default routes:
      - ``*/news-article`` → 200, NEWS_ARTICLE_HTML
      - ``*/opinion-article`` → 200, OPINION_ARTICLE_HTML
      - ``*/not-found`` → 404
      - ``*/non-html`` → 200, application/pdf content
      - ``*/short-content`` → 200, SHORT_CONTENT_HTML
      - ``*/timeout`` → raises TimeoutError (simulates FETCH_TIMEOUT)

    Args:
        custom_routes: Optional dict of path-suffix → (status, headers, body)
            to override or extend default routes.
    """
    routes: dict[str, tuple[int, dict[str, str], bytes]] = {
        "news-article": (
            200,
            {"content-type": "text/html; charset=utf-8"},
            NEWS_ARTICLE_HTML.encode(),
        ),
        "opinion-article": (
            200,
            {"content-type": "text/html; charset=utf-8"},
            OPINION_ARTICLE_HTML.encode(),
        ),
        "not-found": (
            404,
            {"content-type": "text/html"},
            b"<html><body>Not Found</body></html>",
        ),
        "non-html": (
            200,
            {"content-type": "application/pdf"},
            NON_HTML_CONTENT,
        ),
        "short-content": (
            200,
            {"content-type": "text/html; charset=utf-8"},
            SHORT_CONTENT_HTML.encode(),
        ),
    }

    if custom_routes:
        for suffix, (status, headers, body) in custom_routes.items():
            body_bytes = body.encode() if isinstance(body, str) else body
            routes[suffix] = (status, headers, body_bytes)

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)

        if url_str.endswith("timeout"):
            raise httpx.TimeoutException("mock timeout", request=request)

        for suffix, (status, headers, body) in routes.items():
            if url_str.endswith(suffix):
                return httpx.Response(status_code=status, headers=headers, content=body)

        # Default: 200 with news article
        return httpx.Response(
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=NEWS_ARTICLE_HTML.encode(),
        )

    return handler


@pytest.fixture
def mock_httpx_transport():
    """httpx MockTransport with canned HTML responses for common URL patterns.

    Usage in tests::

        async with httpx.AsyncClient(transport=mock_httpx_transport) as client:
            response = await client.get("https://example.com/news-article")
    """
    return httpx.MockTransport(_build_mock_handler())


@pytest.fixture
def mock_httpx_client(mock_httpx_transport):
    """Pre-configured httpx.AsyncClient using the mock transport."""
    return httpx.AsyncClient(transport=mock_httpx_transport)
