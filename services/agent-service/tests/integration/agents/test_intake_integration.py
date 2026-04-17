"""Integration tests for the intake agent's URL-based claim extraction.

These tests exercise the compiled intake ReAct agent end-to-end with
FakeListChatModel orchestrators and an httpx MockTransport, verifying that
a valid news URL flows through ``fetch_content`` and ``decompose_claims``
into a structured ``IntakeOutput`` with the expected claim shape.

S9/9.4: Valid news URL produces 1-5 claims with claim_text, quote, citation.
S9/9.5: After claim selection, agent produces domain classification and
        entity extraction.
S9/9.6: Full flow state contains fetched article text, extracted claims,
        selected claim, domain, and entities together.
S9/9.7: Progress events are emitted via ``stream_mode="custom"`` at each
        tool boundary (fetch, decompose, classify, extract).
S9/9.8: Invalid URL format -> agent returns ``URL_INVALID_FORMAT`` error
        with no HTTP request and no sub-LLM tool calls.
S9/9.9: Unreachable URL (HTTP 404/500/timeout) -> agent returns ``URL_UNREACHABLE``
        error; HTTP request is attempted and fails, no sub-LLM tool calls run.
S9/9.10: Non-HTML content type (e.g. application/pdf) -> agent returns
        ``URL_NOT_HTML`` error; HTTP request succeeds but fetch_content rejects
        the body at the content-type gate, no sub-LLM tool calls run.
S9/9.11: Page with fewer than 50 words of extractable content -> agent returns
        ``CONTENT_TOO_SHORT`` error; HTTP request succeeds and extraction runs
        but the word-count gate fires before any sub-LLM tool call.
S9/9.12: Opinion article with no factual claims -> agent returns
        ``NO_FACTUAL_CLAIMS`` error; fetch_content succeeds and decompose_claims
        runs but the LLM returns an empty claims list, short-circuiting Phase B.
S9/9.17: Every extracted claim's ``quote`` field is a verbatim substring of
        the article text returned by ``fetch_content`` -- locks the
        design.md §7 invariant that a quote is a single sentence drawn from
        the article, not a paraphrase or fabrication.
S9/9.18: HTTP fetch uses a 10-second request timeout, and a mock transport
        raising ``httpx.TimeoutException`` is caught at the fetch layer and
        surfaced as ``error='FETCH_TIMEOUT'`` in the ``fetch_content``
        ToolMessage payload (no uncaught exception reaches the agent).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.callbacks import BaseCallbackHandler

from swarm_reasoning.agents.intake.tools.domain_classification import (
    DOMAIN_VOCABULARY,
)
from tests.integration.agents.conftest import (
    build_fake_intake_agent,
    build_tool_call_orchestrator,
)

NEWS_URL = "https://example.com/news-article"

_CANNED_CLAIMS: list[dict] = [
    {
        "index": 1,
        "claim_text": "The U.S. economy grew 3.2 percent in Q4 2024.",
        "quote": (
            "The U.S. economy grew at an annualized rate of 3.2 percent in the "
            "fourth quarter of 2024, the Bureau of Economic Analysis reported "
            "on Wednesday."
        ),
        "citation": {
            "author": "Bureau of Economic Analysis",
            "publisher": "Example News",
            "date": "20250115",
        },
    },
    {
        "index": 2,
        "claim_text": "Consumer spending increased 3.7 percent.",
        "quote": (
            "Consumer spending, which accounts for roughly two-thirds of "
            "economic activity, increased 3.7 percent."
        ),
        "citation": {
            "author": None,
            "publisher": "Example News",
            "date": "20250115",
        },
    },
    {
        "index": 3,
        "claim_text": "The unemployment rate was 4.1 percent in December.",
        "quote": "The unemployment rate held steady at 4.1 percent in December.",
        "citation": {
            "author": None,
            "publisher": "Example News",
            "date": "20250115",
        },
    },
]


def _scripted_intake_agent(claims: list[dict]):
    """Build a fake intake agent whose orchestrator drives fetch → decompose
    → terminal → structured_response with the provided claims list.
    """
    decompose_json = json.dumps({"claims": claims})

    orchestrator = build_tool_call_orchestrator(
        [
            {"tool": "fetch_content", "args": {"url": NEWS_URL}},
            {
                "tool": "decompose_claims",
                "args": {
                    "article_text": "scripted article text",
                    "article_title": "scripted title",
                },
            },
            "Extracted claims ready for user selection.",
            {
                "tool": "IntakeOutput",
                "args": {
                    "article_text": "scripted article text",
                    "article_title": "Economy Grows 3.2% in Q4",
                    "article_date": "20250115",
                    "extracted_claims": claims,
                },
            },
        ]
    )
    return build_fake_intake_agent(
        orchestrator_model=orchestrator,
        decompose_responses=[decompose_json],
    )


class TestValidNewsUrlProducesClaims:
    """S9/9.4: valid news URL produces 1-5 claims with claim_text, quote, citation."""

    @pytest.mark.asyncio
    async def test_structured_response_has_extracted_claims(self, patched_fetch_httpx):
        """IntakeOutput.extracted_claims is populated with 1-5 claims."""
        agent = _scripted_intake_agent(_CANNED_CLAIMS)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        intake_output = result["structured_response"]
        assert "extracted_claims" in intake_output
        claims = intake_output["extracted_claims"]
        assert 1 <= len(claims) <= 5

    @pytest.mark.asyncio
    async def test_each_claim_has_required_fields(self, patched_fetch_httpx):
        """Every extracted claim has claim_text, quote, and citation."""
        agent = _scripted_intake_agent(_CANNED_CLAIMS)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        claims = result["structured_response"]["extracted_claims"]
        for claim in claims:
            assert claim["claim_text"], "claim_text must be non-empty"
            assert claim["quote"], "quote must be non-empty"
            assert "citation" in claim

    @pytest.mark.asyncio
    async def test_each_citation_has_publisher(self, patched_fetch_httpx):
        """Citation carries a publisher field; author and date may be null."""
        agent = _scripted_intake_agent(_CANNED_CLAIMS)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        claims = result["structured_response"]["extracted_claims"]
        for claim in claims:
            citation = claim["citation"]
            assert citation["publisher"], "citation.publisher must be non-empty"
            assert "author" in citation
            assert "date" in citation

    @pytest.mark.asyncio
    async def test_single_claim_article_within_bounds(self, patched_fetch_httpx):
        """Lower bound: an article yielding exactly one claim still produces
        1-5 claims with the required shape."""
        single = [_CANNED_CLAIMS[0]]
        agent = _scripted_intake_agent(single)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        claims = result["structured_response"]["extracted_claims"]
        assert len(claims) == 1
        assert 1 <= len(claims) <= 5
        assert claims[0]["claim_text"]
        assert claims[0]["quote"]
        assert claims[0]["citation"]["publisher"]

    @pytest.mark.asyncio
    async def test_five_claims_is_upper_bound(self, patched_fetch_httpx):
        """Upper bound: five claims is the maximum — confirms 1-5 window."""
        five = [{**_CANNED_CLAIMS[i % len(_CANNED_CLAIMS)], "index": i + 1} for i in range(5)]
        agent = _scripted_intake_agent(five)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        claims = result["structured_response"]["extracted_claims"]
        assert len(claims) == 5
        assert 1 <= len(claims) <= 5

    @pytest.mark.asyncio
    async def test_decompose_claims_tool_message_carries_claims(self, patched_fetch_httpx):
        """The decompose_claims ToolMessage payload matches the canned claims,
        proving the tool actually ran (not just the structured_response path)."""
        agent = _scripted_intake_agent(_CANNED_CLAIMS)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        tool_messages = [
            m
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "decompose_claims"
        ]
        assert len(tool_messages) == 1

        payload = json.loads(tool_messages[0].content)
        assert payload["claim_count"] == len(_CANNED_CLAIMS)
        assert 1 <= payload["claim_count"] <= 5
        for claim in payload["claims"]:
            assert claim["claim_text"]
            assert claim["quote"]
            assert claim["citation"]["publisher"]

    @pytest.mark.asyncio
    async def test_fetch_content_tool_runs_through_mock_transport(self, patched_fetch_httpx):
        """The fetch_content tool executes the real fetch pipeline against the
        mock transport and returns the extracted article metadata."""
        agent = _scripted_intake_agent(_CANNED_CLAIMS)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        fetch_messages = [
            m
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "fetch_content"
        ]
        assert len(fetch_messages) == 1

        payload = json.loads(fetch_messages[0].content)
        assert payload["success"] is True
        assert payload["url"] == NEWS_URL
        assert payload["word_count"] >= 50
        assert "Economy Grows" in payload["title"]


# ---------------------------------------------------------------------------
# S9/9.5: After claim selection, agent produces domain + entity extraction
# ---------------------------------------------------------------------------

_SELECTED_CLAIM = _CANNED_CLAIMS[0]

_ENTITY_JSON = json.dumps(
    {
        "persons": [],
        "organizations": ["Bureau of Economic Analysis"],
        "dates": ["20241001-20241231"],
        "locations": ["United States"],
        "statistics": ["3.2 percent"],
    }
)


def _scripted_intake_agent_phase_b(
    claims: list[dict],
    selected_claim: dict,
    *,
    classify_responses: list[str] | None = None,
    entity_responses: list[str] | None = None,
    domain: str = "ECONOMICS",
    entities: dict[str, list[str]] | None = None,
):
    """Build a fake intake agent that drives both phases end-to-end.

    Orchestrator script: fetch → decompose → terminal → classify_domain →
    extract_entities → terminal → IntakeOutput. This mirrors the full
    two-phase workflow a real orchestrator would run once the user has
    selected a claim from Phase A's extracted list.
    """
    decompose_json = json.dumps({"claims": claims})
    entities = entities or {
        "persons": [],
        "organizations": ["Bureau of Economic Analysis"],
        "dates": ["20241001-20241231"],
        "locations": ["United States"],
        "statistics": ["3.2 percent"],
    }

    orchestrator = build_tool_call_orchestrator(
        [
            {"tool": "fetch_content", "args": {"url": NEWS_URL}},
            {
                "tool": "decompose_claims",
                "args": {
                    "article_text": "scripted article text",
                    "article_title": "scripted title",
                },
            },
            {
                "tool": "classify_domain",
                "args": {"claim_text": selected_claim["claim_text"]},
            },
            {
                "tool": "extract_entities",
                "args": {"claim_text": selected_claim["claim_text"]},
            },
            "Analysis complete.",
            {
                "tool": "IntakeOutput",
                "args": {
                    "article_text": "scripted article text",
                    "article_title": "Economy Grows 3.2% in Q4",
                    "article_date": "20250115",
                    "extracted_claims": claims,
                    "selected_claim": selected_claim,
                    "domain": domain,
                    "entities": entities,
                },
            },
        ]
    )
    return build_fake_intake_agent(
        orchestrator_model=orchestrator,
        decompose_responses=[decompose_json],
        classify_responses=classify_responses or [domain],
        entity_responses=entity_responses or [_ENTITY_JSON],
    )


class TestSelectedClaimProducesDomainAndEntities:
    """S9/9.5: after claim selection, agent produces domain classification
    from DOMAIN_VOCABULARY and entity extraction result."""

    @pytest.mark.asyncio
    async def test_structured_response_has_domain(self, patched_fetch_httpx):
        """IntakeOutput.domain is populated with a DOMAIN_VOCABULARY value."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        intake_output = result["structured_response"]
        assert "domain" in intake_output
        assert intake_output["domain"] in DOMAIN_VOCABULARY

    @pytest.mark.asyncio
    async def test_structured_response_has_entities(self, patched_fetch_httpx):
        """IntakeOutput.entities carries all five NER entity buckets."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        intake_output = result["structured_response"]
        assert "entities" in intake_output
        entities = intake_output["entities"]
        for bucket in ("persons", "organizations", "dates", "locations", "statistics"):
            assert bucket in entities, f"missing entity bucket: {bucket}"
            assert isinstance(entities[bucket], list)

    @pytest.mark.asyncio
    async def test_structured_response_has_selected_claim(self, patched_fetch_httpx):
        """IntakeOutput carries the selected_claim alongside domain/entities."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        intake_output = result["structured_response"]
        assert intake_output["selected_claim"]["claim_text"] == _SELECTED_CLAIM["claim_text"]

    @pytest.mark.asyncio
    async def test_classify_domain_tool_runs_on_selected_claim(self, patched_fetch_httpx):
        """classify_domain runs exactly once against the selected claim_text
        and its ToolMessage carries a DOMAIN_VOCABULARY value."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        classify_messages = [
            m
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "classify_domain"
        ]
        assert len(classify_messages) == 1

        payload = json.loads(classify_messages[0].content)
        assert payload["domain"] in DOMAIN_VOCABULARY

    @pytest.mark.asyncio
    async def test_extract_entities_tool_runs_on_selected_claim(self, patched_fetch_httpx):
        """extract_entities runs exactly once and its ToolMessage payload
        carries the five NER buckets."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        entity_messages = [
            m
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "extract_entities"
        ]
        assert len(entity_messages) == 1

        payload = json.loads(entity_messages[0].content)
        for bucket in ("persons", "organizations", "dates", "locations", "statistics"):
            assert bucket in payload
            assert isinstance(payload[bucket], list)

    @pytest.mark.asyncio
    async def test_phase_b_runs_after_phase_a(self, patched_fetch_httpx):
        """Tool-call order is fetch → decompose → classify → extract, so
        Phase B (classify + extract) only runs after Phase A (fetch +
        decompose) completes."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        tool_names = [
            getattr(m, "name", None)
            for m in result["messages"]
            if getattr(m, "type", None) == "tool"
        ]
        ordering_tools = [
            name
            for name in tool_names
            if name in {"fetch_content", "decompose_claims", "classify_domain", "extract_entities"}
        ]
        assert ordering_tools == [
            "fetch_content",
            "decompose_claims",
            "classify_domain",
            "extract_entities",
        ]

    @pytest.mark.asyncio
    async def test_classify_domain_llm_response_propagates(self, patched_fetch_httpx):
        """The fake classify LLM's response drives the domain value in the
        ToolMessage payload, proving the sub-call actually ran (not just the
        scripted IntakeOutput path)."""
        agent = _scripted_intake_agent_phase_b(
            _CANNED_CLAIMS,
            _SELECTED_CLAIM,
            classify_responses=["HEALTHCARE"],
            domain="HEALTHCARE",
        )

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        classify_messages = [
            m
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "classify_domain"
        ]
        payload = json.loads(classify_messages[0].content)
        assert payload["domain"] == "HEALTHCARE"


# ---------------------------------------------------------------------------
# S9/9.6: Full flow state contains all five required fields
# ---------------------------------------------------------------------------


class TestFullFlowStateContainsAllRequiredFields:
    """S9/9.6: the final agent state produced by the full two-phase flow
    contains fetched article text, extracted claims, selected claim, domain,
    and entities -- all present together in a single coherent snapshot.

    Unlike S9/9.5 which checks individual Phase B fields, these tests assert
    the *combined* structured_response -- the state a downstream pipeline
    node would read after the intake agent completes both phases.
    """

    @pytest.mark.asyncio
    async def test_full_flow_state_contains_all_five_fields(self, patched_fetch_httpx):
        """Final structured_response carries all five Phase A+B fields together."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        state = result["structured_response"]
        for field in ("article_text", "extracted_claims", "selected_claim", "domain", "entities"):
            assert field in state, f"final state missing field: {field}"

    @pytest.mark.asyncio
    async def test_full_flow_state_fields_are_non_empty(self, patched_fetch_httpx):
        """Each of the five required fields is populated (non-empty / truthy)."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        state = result["structured_response"]
        assert state["article_text"], "article_text must be non-empty"
        assert state["extracted_claims"], "extracted_claims must be non-empty"
        assert state["selected_claim"], "selected_claim must be populated"
        assert state["domain"], "domain must be non-empty"
        assert state["entities"], "entities must be populated"

    @pytest.mark.asyncio
    async def test_full_flow_state_has_no_error_field(self, patched_fetch_httpx):
        """Happy-path final state does not carry an ``error`` field --
        rejection-path fields are mutually exclusive with success fields."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        state = result["structured_response"]
        assert "error" not in state or not state.get("error")

    @pytest.mark.asyncio
    async def test_full_flow_state_article_text_is_string(self, patched_fetch_httpx):
        """The fetched article text in final state is a non-empty string."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        state = result["structured_response"]
        assert isinstance(state["article_text"], str)
        assert len(state["article_text"]) > 0

    @pytest.mark.asyncio
    async def test_full_flow_state_extracted_claims_shape(self, patched_fetch_httpx):
        """Final state's extracted_claims list preserves 1-5 claims with
        the required claim_text / quote / citation shape."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        claims = result["structured_response"]["extracted_claims"]
        assert 1 <= len(claims) <= 5
        for claim in claims:
            assert claim["claim_text"]
            assert claim["quote"]
            assert claim["citation"]["publisher"]

    @pytest.mark.asyncio
    async def test_full_flow_state_selected_claim_matches_an_extracted(self, patched_fetch_httpx):
        """The selected_claim in final state is one of the extracted_claims
        (selection is a choice from the Phase A list, not a fresh claim)."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        state = result["structured_response"]
        extracted_texts = {c["claim_text"] for c in state["extracted_claims"]}
        assert state["selected_claim"]["claim_text"] in extracted_texts

    @pytest.mark.asyncio
    async def test_full_flow_state_domain_and_entities_shape(self, patched_fetch_httpx):
        """Final state's domain is a DOMAIN_VOCABULARY value and entities
        carries all five NER buckets as lists."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        state = result["structured_response"]
        assert state["domain"] in DOMAIN_VOCABULARY
        for bucket in ("persons", "organizations", "dates", "locations", "statistics"):
            assert bucket in state["entities"], f"missing entity bucket: {bucket}"
            assert isinstance(state["entities"][bucket], list)

    @pytest.mark.asyncio
    async def test_full_flow_state_coherent_with_tool_messages(self, patched_fetch_httpx):
        """State fields are coherent with the tool-call record: fetch ran,
        decompose produced the same claim count, classify produced the same
        domain, and extract produced the same entity buckets. Proves the
        final state is a faithful reflection of the tool-call history, not
        a side-channel fabrication."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        state = result["structured_response"]
        tool_messages = {
            m.name: json.loads(m.content)
            for m in result["messages"]
            if getattr(m, "type", None) == "tool"
            and getattr(m, "name", None)
            in {"fetch_content", "decompose_claims", "classify_domain", "extract_entities"}
        }

        # fetch_content ran and succeeded against the mocked URL
        assert tool_messages["fetch_content"]["success"] is True
        assert tool_messages["fetch_content"]["url"] == NEWS_URL

        # decompose_claims produced the same number of claims present in state
        assert tool_messages["decompose_claims"]["claim_count"] == len(state["extracted_claims"])

        # classify_domain's tool output domain matches state.domain
        assert tool_messages["classify_domain"]["domain"] == state["domain"]

        # extract_entities buckets are structurally present in state.entities
        for bucket in ("persons", "organizations", "dates", "locations", "statistics"):
            assert bucket in tool_messages["extract_entities"]
            assert bucket in state["entities"]


# ---------------------------------------------------------------------------
# S9/9.7: Progress events emitted via stream_mode="custom" at each tool boundary
# ---------------------------------------------------------------------------


async def _collect_custom_stream(agent, user_message: str) -> list[dict]:
    """Drive the agent via ``astream(stream_mode="custom")`` and collect the
    writer-emitted payloads.

    Tools call ``get_stream_writer()`` to publish ``{"type": "progress",
    "message": ...}`` dicts. With ``stream_mode="custom"`` these surface as
    astream events — SSE/Redis relay consumes them verbatim.
    """
    events: list[dict] = []
    async for event in agent.astream(
        {"messages": [("user", user_message)]},
        stream_mode="custom",
    ):
        events.append(event)
    return events


def _progress_messages(events: list[dict]) -> list[str]:
    """Extract ``message`` strings from progress-typed events."""
    return [e["message"] for e in events if e.get("type") == "progress"]


class TestToolBoundaryProgressEvents:
    """S9/9.7: each tool boundary emits a progress event via the langgraph
    stream writer; ``astream(stream_mode="custom")`` yields those events to
    the caller for relay to the SSE/Redis progress channel.

    Tools under test (one event-emitting boundary each):
      - fetch_content     → "Fetching article content..." + "Content extracted: N words"
      - decompose_claims  → "Analyzing article for factual claims..." + "Found N claims for review"
      - classify_domain   → "Domain classified: DOMAIN"
      - extract_entities  → "Entities extracted: N found"
    """

    @pytest.mark.asyncio
    async def test_stream_yields_progress_events(self, patched_fetch_httpx):
        """``astream(stream_mode="custom")`` yields at least one progress
        event — the writer channel is wired through to the caller."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        events = await _collect_custom_stream(agent, f"Process this URL: {NEWS_URL}")

        assert events, "stream_mode='custom' yielded no events"
        assert any(e.get("type") == "progress" for e in events)

    @pytest.mark.asyncio
    async def test_every_event_is_progress_dict(self, patched_fetch_httpx):
        """Every event on the custom stream is a progress-typed dict with a
        non-empty string message — the SSE relay contract."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        events = await _collect_custom_stream(agent, f"Process this URL: {NEWS_URL}")

        assert events
        for event in events:
            assert isinstance(event, dict)
            assert event.get("type") == "progress"
            assert isinstance(event.get("message"), str)
            assert event["message"], "progress message must be non-empty"

    @pytest.mark.asyncio
    async def test_fetch_content_boundary_emits_progress(self, patched_fetch_httpx):
        """fetch_content emits start and completion progress events."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        messages = _progress_messages(
            await _collect_custom_stream(agent, f"Process this URL: {NEWS_URL}")
        )

        assert any("Fetching article content" in m for m in messages), messages
        assert any("Content extracted" in m and "words" in m for m in messages), messages

    @pytest.mark.asyncio
    async def test_decompose_claims_boundary_emits_progress(self, patched_fetch_httpx):
        """decompose_claims emits analyzing + found-N-claims progress events."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        messages = _progress_messages(
            await _collect_custom_stream(agent, f"Process this URL: {NEWS_URL}")
        )

        assert any("Analyzing article for factual claims" in m for m in messages), messages
        assert any("Found" in m and "claims for review" in m for m in messages), messages

    @pytest.mark.asyncio
    async def test_classify_domain_boundary_emits_progress(self, patched_fetch_httpx):
        """classify_domain emits a ``Domain classified: DOMAIN`` event carrying
        the classified value."""
        agent = _scripted_intake_agent_phase_b(
            _CANNED_CLAIMS,
            _SELECTED_CLAIM,
            classify_responses=["ECONOMICS"],
            domain="ECONOMICS",
        )

        messages = _progress_messages(
            await _collect_custom_stream(agent, f"Process this URL: {NEWS_URL}")
        )

        assert any(m == "Domain classified: ECONOMICS" for m in messages), messages

    @pytest.mark.asyncio
    async def test_extract_entities_boundary_emits_progress(self, patched_fetch_httpx):
        """extract_entities emits an ``Entities extracted: N found`` event
        whose count matches the returned buckets."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        messages = _progress_messages(
            await _collect_custom_stream(agent, f"Process this URL: {NEWS_URL}")
        )

        # Default canned entities: 1 org + 1 date + 1 location + 1 statistic = 4 entities.
        expected_count = sum(
            len(v)
            for v in {
                "persons": [],
                "organizations": ["Bureau of Economic Analysis"],
                "dates": ["20241001-20241231"],
                "locations": ["United States"],
                "statistics": ["3.2 percent"],
            }.values()
        )
        assert any(m == f"Entities extracted: {expected_count} found" for m in messages), messages

    @pytest.mark.asyncio
    async def test_all_four_tool_boundaries_emit_in_order(self, patched_fetch_httpx):
        """All four tool boundaries (fetch → decompose → classify → extract)
        emit progress events, and their first occurrences arrive in that
        order — the SSE timeline matches the tool-call timeline."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        messages = _progress_messages(
            await _collect_custom_stream(agent, f"Process this URL: {NEWS_URL}")
        )

        def first_index(predicate) -> int:
            for i, m in enumerate(messages):
                if predicate(m):
                    return i
            return -1

        fetch_idx = first_index(lambda m: "Fetching article content" in m)
        decompose_idx = first_index(lambda m: "Analyzing article for factual claims" in m)
        classify_idx = first_index(lambda m: m.startswith("Domain classified:"))
        extract_idx = first_index(lambda m: m.startswith("Entities extracted:"))

        for label, idx in (
            ("fetch", fetch_idx),
            ("decompose", decompose_idx),
            ("classify", classify_idx),
            ("extract", extract_idx),
        ):
            assert idx >= 0, f"no progress event from {label} boundary: {messages}"

        assert fetch_idx < decompose_idx < classify_idx < extract_idx, messages

    @pytest.mark.asyncio
    async def test_fetch_error_path_emits_error_progress(self, patched_fetch_httpx):
        """On fetch failure, fetch_content still emits a progress event —
        the error boundary is also observable on the custom stream."""
        bad_url = "https://example.com/not-found"
        orchestrator = build_tool_call_orchestrator(
            [
                {"tool": "fetch_content", "args": {"url": bad_url}},
                "Fetch failed.",
                {
                    "tool": "IntakeOutput",
                    "args": {
                        "article_text": "",
                        "article_title": "",
                        "article_date": "",
                        "extracted_claims": [],
                        "error": "URL_UNREACHABLE",
                    },
                },
            ]
        )
        agent = build_fake_intake_agent(orchestrator_model=orchestrator)

        messages = _progress_messages(
            await _collect_custom_stream(agent, f"Process this URL: {bad_url}")
        )

        assert any("Fetching article content" in m for m in messages), messages
        assert any(m.startswith("Fetch error:") for m in messages), messages

    @pytest.mark.asyncio
    async def test_custom_stream_does_not_leak_message_chunks(self, patched_fetch_httpx):
        """``stream_mode="custom"`` yields only writer payloads — not
        LangGraph message/state updates. This keeps the SSE relay free of
        non-progress chatter."""
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        events = await _collect_custom_stream(agent, f"Process this URL: {NEWS_URL}")

        # Every event is a writer-emitted progress dict; no AIMessage/ToolMessage
        # objects, no (node, state) update tuples should leak through.
        for event in events:
            assert isinstance(event, dict)
            assert set(event.keys()) == {"type", "message"}, event
            assert event["type"] == "progress"


# ---------------------------------------------------------------------------
# S9/9.8: Invalid URL format -> agent returns error, no HTTP or LLM calls
# ---------------------------------------------------------------------------


_INVALID_URLS = [
    "not-a-url",
    "ftp://example.com/article",
    "example.com/article",
    "https://example",
    "",
]


def _invalid_url_agent(bad_url: str):
    """Scripted orchestrator for the rejection path.

    Real orchestrators reading ``fetch_content``'s error dict are told by
    the system prompt to stop; the script replays that trajectory:
    fetch (with the bad URL) -> terminal -> IntakeOutput carrying only
    ``error="URL_INVALID_FORMAT"``.
    """
    orchestrator = build_tool_call_orchestrator(
        [
            {"tool": "fetch_content", "args": {"url": bad_url}},
            "URL format invalid, stopping intake.",
            {
                "tool": "IntakeOutput",
                "args": {
                    "article_text": "",
                    "article_title": "",
                    "article_date": "",
                    "extracted_claims": [],
                    "error": "URL_INVALID_FORMAT",
                },
            },
        ]
    )
    return build_fake_intake_agent(orchestrator_model=orchestrator)


class TestInvalidUrlFormatReturnsError:
    """S9/9.8: malformed URLs are rejected by ``validate_url`` inside the
    fetch_content tool before any network or sub-LLM work happens.

    Guarantees:
      - structured_response carries ``error="URL_INVALID_FORMAT"``.
      - ``httpx.AsyncClient`` is never constructed (patched_fetch_httpx
        records zero calls).
      - Phase A/B sub-tools (decompose_claims, classify_domain,
        extract_entities) never run, so their LLM sub-calls are
        transitively never made.
    """

    @pytest.mark.parametrize("bad_url", _INVALID_URLS)
    @pytest.mark.asyncio
    async def test_structured_response_has_url_invalid_format_error(
        self, patched_fetch_httpx, bad_url
    ):
        """Each malformed URL pattern yields the same rejection code."""
        agent = _invalid_url_agent(bad_url)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {bad_url}")]})

        state = result["structured_response"]
        assert state.get("error") == "URL_INVALID_FORMAT"

    @pytest.mark.asyncio
    async def test_no_http_request_is_made(self, patched_fetch_httpx):
        """``validate_url`` raises before ``fetch_html`` runs, so the
        patched ``httpx.AsyncClient`` constructor is never called."""
        agent = _invalid_url_agent("not-a-url")

        await agent.ainvoke({"messages": [("user", "Process this URL: not-a-url")]})

        assert patched_fetch_httpx.call_count == 0, (
            "httpx.AsyncClient must not be constructed on the invalid-URL "
            f"rejection path; got {patched_fetch_httpx.call_count} calls"
        )

    @pytest.mark.asyncio
    async def test_no_sub_llm_tools_run(self, patched_fetch_httpx):
        """decompose_claims / classify_domain / extract_entities never run
        on the rejection path -- their LLM sub-calls are never made."""
        agent = _invalid_url_agent("not-a-url")

        result = await agent.ainvoke({"messages": [("user", "Process this URL: not-a-url")]})

        sub_tool_names = {"decompose_claims", "classify_domain", "extract_entities"}
        ran = [
            getattr(m, "name", None)
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) in sub_tool_names
        ]
        assert ran == [], f"expected no sub-tool messages on rejection, got {ran}"

    @pytest.mark.asyncio
    async def test_fetch_content_tool_message_records_rejection(self, patched_fetch_httpx):
        """fetch_content ran exactly once; its ToolMessage records the
        failed validation with the URL_INVALID_FORMAT reason -- proving
        the tool actually executed, not just the scripted IntakeOutput."""
        agent = _invalid_url_agent("not-a-url")

        result = await agent.ainvoke({"messages": [("user", "Process this URL: not-a-url")]})

        fetch_messages = [
            m
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "fetch_content"
        ]
        assert len(fetch_messages) == 1

        payload = json.loads(fetch_messages[0].content)
        assert payload["success"] is False
        assert payload["error"] == "URL_INVALID_FORMAT"
        assert payload["url"] == "not-a-url"

    @pytest.mark.asyncio
    async def test_rejection_state_has_no_success_fields(self, patched_fetch_httpx):
        """Rejection payload is minimal: no article text, no claims, no
        domain/entities populated -- success-path fields stay absent."""
        agent = _invalid_url_agent("not-a-url")

        result = await agent.ainvoke({"messages": [("user", "Process this URL: not-a-url")]})

        state = result["structured_response"]
        assert state.get("error") == "URL_INVALID_FORMAT"
        assert not state.get("article_text")
        assert not state.get("extracted_claims")
        assert not state.get("selected_claim")
        assert not state.get("domain")
        assert not state.get("entities")


# ---------------------------------------------------------------------------
# S9/9.9: Unreachable URL (HTTP 404/500/timeout) -> error with URL_UNREACHABLE
# ---------------------------------------------------------------------------


# (url_suffix, expected fetch_content error code for that failure mode)
# The real fetch_content tool maps each network condition to its own reason
# string; the orchestrator's job is to collapse these into the canonical
# user-facing ``URL_UNREACHABLE`` code in the final IntakeOutput.
_UNREACHABLE_CASES = [
    ("https://example.com/not-found", "HTTP_404"),
    ("https://example.com/server-error", "HTTP_500"),
    ("https://example.com/timeout", "FETCH_TIMEOUT"),
]


def _unreachable_url_agent(bad_url: str):
    """Scripted orchestrator for the unreachable-URL rejection path.

    Replays the trajectory a real orchestrator would take after observing
    ``fetch_content`` return ``success=False``: no further tool calls, and
    an IntakeOutput carrying only ``error="URL_UNREACHABLE"`` (the canonical
    user-facing code that collapses HTTP_4xx / HTTP_5xx / FETCH_TIMEOUT).
    """
    orchestrator = build_tool_call_orchestrator(
        [
            {"tool": "fetch_content", "args": {"url": bad_url}},
            "URL unreachable, stopping intake.",
            {
                "tool": "IntakeOutput",
                "args": {
                    "article_text": "",
                    "article_title": "",
                    "article_date": "",
                    "extracted_claims": [],
                    "error": "URL_UNREACHABLE",
                },
            },
        ]
    )
    return build_fake_intake_agent(orchestrator_model=orchestrator)


class TestUnreachableUrlReturnsError:
    """S9/9.9: URLs that validate syntactically but fail the HTTP round-trip
    (404, 500, or timeout) short-circuit the intake pipeline with
    ``URL_UNREACHABLE``.

    Guarantees:
      - structured_response carries ``error="URL_UNREACHABLE"`` regardless
        of which underlying network failure occurred.
      - ``httpx.AsyncClient`` IS constructed (the URL passes format
        validation, so fetch_html runs and the failure surfaces from the
        HTTP layer — unlike S9/9.8 where construction is skipped entirely).
      - ``fetch_content``'s ToolMessage records the concrete failure reason
        (HTTP_404 / HTTP_500 / FETCH_TIMEOUT) — proving the real tool ran
        against the mock transport, not just the scripted IntakeOutput.
      - Phase A/B sub-tools (decompose_claims, classify_domain,
        extract_entities) never run, so their LLM sub-calls are
        transitively never made.
    """

    @pytest.mark.parametrize(("bad_url", "expected_fetch_error"), _UNREACHABLE_CASES)
    @pytest.mark.asyncio
    async def test_structured_response_has_url_unreachable_error(
        self, patched_fetch_httpx, bad_url, expected_fetch_error
    ):
        """Each unreachable-URL failure mode yields the same rejection code."""
        agent = _unreachable_url_agent(bad_url)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {bad_url}")]})

        state = result["structured_response"]
        assert state.get("error") == "URL_UNREACHABLE"

    @pytest.mark.parametrize(("bad_url", "expected_fetch_error"), _UNREACHABLE_CASES)
    @pytest.mark.asyncio
    async def test_http_request_is_attempted(
        self, patched_fetch_httpx, bad_url, expected_fetch_error
    ):
        """Format-valid URLs reach the HTTP layer -- ``httpx.AsyncClient``
        is constructed so the transport can surface the failure. This is
        what distinguishes 9.9 from 9.8 (which rejects before HTTP)."""
        agent = _unreachable_url_agent(bad_url)

        await agent.ainvoke({"messages": [("user", f"Process this URL: {bad_url}")]})

        assert patched_fetch_httpx.call_count >= 1, (
            "httpx.AsyncClient must be constructed on the unreachable-URL "
            f"path; got {patched_fetch_httpx.call_count} calls"
        )

    @pytest.mark.parametrize(("bad_url", "expected_fetch_error"), _UNREACHABLE_CASES)
    @pytest.mark.asyncio
    async def test_fetch_content_tool_records_network_failure(
        self, patched_fetch_httpx, bad_url, expected_fetch_error
    ):
        """fetch_content ran exactly once; its ToolMessage records the
        specific network failure reason that the orchestrator would then
        collapse into URL_UNREACHABLE."""
        agent = _unreachable_url_agent(bad_url)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {bad_url}")]})

        fetch_messages = [
            m
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "fetch_content"
        ]
        assert len(fetch_messages) == 1

        payload = json.loads(fetch_messages[0].content)
        assert payload["success"] is False
        assert payload["error"] == expected_fetch_error
        assert payload["url"] == bad_url

    @pytest.mark.parametrize(("bad_url", "expected_fetch_error"), _UNREACHABLE_CASES)
    @pytest.mark.asyncio
    async def test_no_sub_llm_tools_run(self, patched_fetch_httpx, bad_url, expected_fetch_error):
        """decompose_claims / classify_domain / extract_entities never run
        on the unreachable-URL rejection path -- their LLM sub-calls are
        never made."""
        agent = _unreachable_url_agent(bad_url)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {bad_url}")]})

        sub_tool_names = {"decompose_claims", "classify_domain", "extract_entities"}
        ran = [
            getattr(m, "name", None)
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) in sub_tool_names
        ]
        assert ran == [], f"expected no sub-tool messages on rejection, got {ran}"

    @pytest.mark.parametrize(("bad_url", "expected_fetch_error"), _UNREACHABLE_CASES)
    @pytest.mark.asyncio
    async def test_rejection_state_has_no_success_fields(
        self, patched_fetch_httpx, bad_url, expected_fetch_error
    ):
        """Rejection payload is minimal: no article text, no claims, no
        domain/entities populated -- success-path fields stay absent."""
        agent = _unreachable_url_agent(bad_url)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {bad_url}")]})

        state = result["structured_response"]
        assert state.get("error") == "URL_UNREACHABLE"
        assert not state.get("article_text")
        assert not state.get("extracted_claims")
        assert not state.get("selected_claim")
        assert not state.get("domain")
        assert not state.get("entities")

    @pytest.mark.asyncio
    async def test_fetch_error_progress_event_is_emitted(self, patched_fetch_httpx):
        """On network failure, ``fetch_content`` still emits a
        ``Fetch error: ...`` progress event via the custom stream --
        the SSE relay sees the failure boundary."""
        bad_url = "https://example.com/not-found"
        agent = _unreachable_url_agent(bad_url)

        messages = _progress_messages(
            await _collect_custom_stream(agent, f"Process this URL: {bad_url}")
        )

        assert any("Fetching article content" in m for m in messages), messages
        assert any(m.startswith("Fetch error:") for m in messages), messages

    @pytest.mark.asyncio
    async def test_different_failure_modes_collapse_to_same_user_code(self, patched_fetch_httpx):
        """404, 500, and timeout all produce distinct fetch_content error
        reasons, but they collapse into the same user-facing
        ``URL_UNREACHABLE`` code in the final IntakeOutput. This is the
        core contract 9.9 enforces."""
        fetch_errors: set[str] = set()
        user_errors: set[str] = set()

        for bad_url, _expected in _UNREACHABLE_CASES:
            agent = _unreachable_url_agent(bad_url)
            result = await agent.ainvoke({"messages": [("user", f"Process this URL: {bad_url}")]})

            fetch_messages = [
                m
                for m in result["messages"]
                if getattr(m, "type", None) == "tool"
                and getattr(m, "name", None) == "fetch_content"
            ]
            payload = json.loads(fetch_messages[0].content)
            fetch_errors.add(payload["error"])
            user_errors.add(result["structured_response"].get("error"))

        assert fetch_errors == {"HTTP_404", "HTTP_500", "FETCH_TIMEOUT"}
        assert user_errors == {"URL_UNREACHABLE"}


# ---------------------------------------------------------------------------
# S9/9.10: Non-HTML content type -> error with URL_NOT_HTML
# ---------------------------------------------------------------------------


NON_HTML_URL = "https://example.com/non-html"


def _non_html_url_agent(bad_url: str):
    """Scripted orchestrator for the non-HTML-content rejection path.

    Replays the trajectory a real orchestrator would take after observing
    ``fetch_content`` return ``success=False`` with ``error="URL_NOT_HTML"``:
    no further tool calls, and an IntakeOutput carrying only
    ``error="URL_NOT_HTML"``.
    """
    orchestrator = build_tool_call_orchestrator(
        [
            {"tool": "fetch_content", "args": {"url": bad_url}},
            "URL is not HTML, stopping intake.",
            {
                "tool": "IntakeOutput",
                "args": {
                    "article_text": "",
                    "article_title": "",
                    "article_date": "",
                    "extracted_claims": [],
                    "error": "URL_NOT_HTML",
                },
            },
        ]
    )
    return build_fake_intake_agent(orchestrator_model=orchestrator)


class TestNonHtmlContentTypeReturnsError:
    """S9/9.10: URLs that validate syntactically and return a 2xx response
    but carry a non-HTML ``Content-Type`` (e.g. ``application/pdf``) are
    rejected by ``fetch_content`` at the content-type gate, before any
    extraction work happens.

    Guarantees:
      - structured_response carries ``error="URL_NOT_HTML"``.
      - ``httpx.AsyncClient`` IS constructed (the URL passes format
        validation and the HTTP round-trip succeeds — the failure surfaces
        after headers are inspected, not from the network layer).
      - ``fetch_content``'s ToolMessage records ``error="URL_NOT_HTML"`` --
        proving the real tool ran against the mock transport and reached
        the content-type gate, not just the scripted IntakeOutput.
      - Extraction (trafilatura/BeautifulSoup) never runs -- the gate
        short-circuits before text processing.
      - Phase A/B sub-tools (decompose_claims, classify_domain,
        extract_entities) never run, so their LLM sub-calls are
        transitively never made.
    """

    @pytest.mark.asyncio
    async def test_structured_response_has_url_not_html_error(self, patched_fetch_httpx):
        """The canonical non-HTML rejection surfaces as URL_NOT_HTML."""
        agent = _non_html_url_agent(NON_HTML_URL)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NON_HTML_URL}")]})

        state = result["structured_response"]
        assert state.get("error") == "URL_NOT_HTML"

    @pytest.mark.asyncio
    async def test_http_request_is_attempted(self, patched_fetch_httpx):
        """Format-valid URLs reach the HTTP layer even when the response is
        non-HTML -- the content-type gate runs *after* the round-trip
        completes, so ``httpx.AsyncClient`` is constructed. This is what
        distinguishes 9.10 from 9.8 (which rejects before HTTP)."""
        agent = _non_html_url_agent(NON_HTML_URL)

        await agent.ainvoke({"messages": [("user", f"Process this URL: {NON_HTML_URL}")]})

        assert patched_fetch_httpx.call_count >= 1, (
            "httpx.AsyncClient must be constructed on the non-HTML "
            f"rejection path; got {patched_fetch_httpx.call_count} calls"
        )

    @pytest.mark.asyncio
    async def test_fetch_content_tool_records_url_not_html(self, patched_fetch_httpx):
        """fetch_content ran exactly once; its ToolMessage records
        ``URL_NOT_HTML`` directly -- proving the content-type gate fired
        against the mock transport's ``application/pdf`` response, not
        some other error (EXTRACTION_FAILED / CONTENT_TOO_SHORT) that
        would indicate the gate leaked and extraction ran on PDF bytes."""
        agent = _non_html_url_agent(NON_HTML_URL)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NON_HTML_URL}")]})

        fetch_messages = [
            m
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "fetch_content"
        ]
        assert len(fetch_messages) == 1

        payload = json.loads(fetch_messages[0].content)
        assert payload["success"] is False
        assert payload["error"] == "URL_NOT_HTML"
        assert payload["url"] == NON_HTML_URL

    @pytest.mark.asyncio
    async def test_no_sub_llm_tools_run(self, patched_fetch_httpx):
        """decompose_claims / classify_domain / extract_entities never run
        on the non-HTML rejection path -- their LLM sub-calls are never
        made."""
        agent = _non_html_url_agent(NON_HTML_URL)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NON_HTML_URL}")]})

        sub_tool_names = {"decompose_claims", "classify_domain", "extract_entities"}
        ran = [
            getattr(m, "name", None)
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) in sub_tool_names
        ]
        assert ran == [], f"expected no sub-tool messages on rejection, got {ran}"

    @pytest.mark.asyncio
    async def test_rejection_state_has_no_success_fields(self, patched_fetch_httpx):
        """Rejection payload is minimal: no article text, no claims, no
        domain/entities populated -- success-path fields stay absent."""
        agent = _non_html_url_agent(NON_HTML_URL)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NON_HTML_URL}")]})

        state = result["structured_response"]
        assert state.get("error") == "URL_NOT_HTML"
        assert not state.get("article_text")
        assert not state.get("extracted_claims")
        assert not state.get("selected_claim")
        assert not state.get("domain")
        assert not state.get("entities")

    @pytest.mark.asyncio
    async def test_fetch_error_progress_event_is_emitted(self, patched_fetch_httpx):
        """On non-HTML content, ``fetch_content`` still emits a
        ``Fetch error: URL_NOT_HTML`` progress event via the custom stream
        -- the SSE relay sees the failure boundary."""
        agent = _non_html_url_agent(NON_HTML_URL)

        messages = _progress_messages(
            await _collect_custom_stream(agent, f"Process this URL: {NON_HTML_URL}")
        )

        assert any("Fetching article content" in m for m in messages), messages
        assert any(m == "Fetch error: URL_NOT_HTML" for m in messages), messages


# ---------------------------------------------------------------------------
# S9/9.11: Page with < 50 words of content -> error with CONTENT_TOO_SHORT
# ---------------------------------------------------------------------------


SHORT_CONTENT_URL = "https://example.com/short-content"


def _short_content_url_agent(bad_url: str):
    """Scripted orchestrator for the short-content rejection path.

    Replays the trajectory a real orchestrator would take after observing
    ``fetch_content`` return ``success=False`` with an error reason starting
    ``CONTENT_TOO_SHORT``: no further tool calls, and an IntakeOutput carrying
    only ``error="CONTENT_TOO_SHORT"`` (the canonical user-facing code; the
    fetch-level reason carries the actual word count suffix, e.g.
    ``CONTENT_TOO_SHORT:6``).
    """
    orchestrator = build_tool_call_orchestrator(
        [
            {"tool": "fetch_content", "args": {"url": bad_url}},
            "Extracted content too short, stopping intake.",
            {
                "tool": "IntakeOutput",
                "args": {
                    "article_text": "",
                    "article_title": "",
                    "article_date": "",
                    "extracted_claims": [],
                    "error": "CONTENT_TOO_SHORT",
                },
            },
        ]
    )
    return build_fake_intake_agent(orchestrator_model=orchestrator)


class TestShortContentReturnsError:
    """S9/9.11: URLs that validate syntactically, return a 2xx HTML response,
    and pass the content-type gate but yield fewer than 50 words of
    extractable text are rejected by ``fetch_content`` at the word-count gate,
    before any claim decomposition happens.

    Guarantees:
      - structured_response carries ``error="CONTENT_TOO_SHORT"``.
      - ``httpx.AsyncClient`` IS constructed (the URL passes format
        validation, the HTTP round-trip succeeds, and the content-type gate
        passes — the failure surfaces only after extraction runs and the
        word count is measured).
      - ``fetch_content``'s ToolMessage records an error starting with
        ``CONTENT_TOO_SHORT`` (the fetch-level reason includes the measured
        word count, e.g. ``CONTENT_TOO_SHORT:6``) -- proving the real
        extraction pipeline ran against the mock transport and reached the
        word-count gate, not just the scripted IntakeOutput.
      - Phase A/B sub-tools (decompose_claims, classify_domain,
        extract_entities) never run, so their LLM sub-calls are
        transitively never made.
    """

    @pytest.mark.asyncio
    async def test_structured_response_has_content_too_short_error(self, patched_fetch_httpx):
        """The canonical short-content rejection surfaces as CONTENT_TOO_SHORT."""
        agent = _short_content_url_agent(SHORT_CONTENT_URL)

        result = await agent.ainvoke(
            {"messages": [("user", f"Process this URL: {SHORT_CONTENT_URL}")]}
        )

        state = result["structured_response"]
        assert state.get("error") == "CONTENT_TOO_SHORT"

    @pytest.mark.asyncio
    async def test_http_request_is_attempted(self, patched_fetch_httpx):
        """Format-valid URLs reach the HTTP layer -- ``httpx.AsyncClient``
        is constructed so the transport can serve the short HTML response.
        The content-type gate also passes, so this failure surfaces strictly
        later than 9.8 (pre-HTTP) and 9.10 (pre-extraction)."""
        agent = _short_content_url_agent(SHORT_CONTENT_URL)

        await agent.ainvoke({"messages": [("user", f"Process this URL: {SHORT_CONTENT_URL}")]})

        assert patched_fetch_httpx.call_count >= 1, (
            "httpx.AsyncClient must be constructed on the short-content "
            f"rejection path; got {patched_fetch_httpx.call_count} calls"
        )

    @pytest.mark.asyncio
    async def test_fetch_content_tool_records_content_too_short(self, patched_fetch_httpx):
        """fetch_content ran exactly once; its ToolMessage records an error
        starting with ``CONTENT_TOO_SHORT`` -- proving extraction ran and the
        word-count gate fired, not some upstream gate (URL_NOT_HTML,
        EXTRACTION_FAILED) that would indicate a different failure mode.

        The fetch-level error reason carries the measured word count as a
        suffix (e.g. ``CONTENT_TOO_SHORT:6``); the orchestrator collapses it
        into the bare ``CONTENT_TOO_SHORT`` user-facing code."""
        agent = _short_content_url_agent(SHORT_CONTENT_URL)

        result = await agent.ainvoke(
            {"messages": [("user", f"Process this URL: {SHORT_CONTENT_URL}")]}
        )

        fetch_messages = [
            m
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "fetch_content"
        ]
        assert len(fetch_messages) == 1

        payload = json.loads(fetch_messages[0].content)
        assert payload["success"] is False
        assert payload["url"] == SHORT_CONTENT_URL
        assert payload["error"].startswith("CONTENT_TOO_SHORT"), payload["error"]

    @pytest.mark.asyncio
    async def test_fetch_content_word_count_is_below_threshold(self, patched_fetch_httpx):
        """The fetch-level error reason encodes the measured word count as a
        ``CONTENT_TOO_SHORT:N`` suffix, and that N is strictly below the
        50-word minimum. This pins the gate's behavior to its stated
        threshold, not just the presence of the error string."""
        agent = _short_content_url_agent(SHORT_CONTENT_URL)

        result = await agent.ainvoke(
            {"messages": [("user", f"Process this URL: {SHORT_CONTENT_URL}")]}
        )

        fetch_messages = [
            m
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "fetch_content"
        ]
        payload = json.loads(fetch_messages[0].content)

        reason = payload["error"]
        assert ":" in reason, f"expected CONTENT_TOO_SHORT:<count>, got {reason!r}"
        _, _, count_str = reason.partition(":")
        word_count = int(count_str)
        assert word_count < 50, f"measured word count must be < 50, got {word_count}"

    @pytest.mark.asyncio
    async def test_no_sub_llm_tools_run(self, patched_fetch_httpx):
        """decompose_claims / classify_domain / extract_entities never run
        on the short-content rejection path -- their LLM sub-calls are
        never made."""
        agent = _short_content_url_agent(SHORT_CONTENT_URL)

        result = await agent.ainvoke(
            {"messages": [("user", f"Process this URL: {SHORT_CONTENT_URL}")]}
        )

        sub_tool_names = {"decompose_claims", "classify_domain", "extract_entities"}
        ran = [
            getattr(m, "name", None)
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) in sub_tool_names
        ]
        assert ran == [], f"expected no sub-tool messages on rejection, got {ran}"

    @pytest.mark.asyncio
    async def test_rejection_state_has_no_success_fields(self, patched_fetch_httpx):
        """Rejection payload is minimal: no article text, no claims, no
        domain/entities populated -- success-path fields stay absent."""
        agent = _short_content_url_agent(SHORT_CONTENT_URL)

        result = await agent.ainvoke(
            {"messages": [("user", f"Process this URL: {SHORT_CONTENT_URL}")]}
        )

        state = result["structured_response"]
        assert state.get("error") == "CONTENT_TOO_SHORT"
        assert not state.get("article_text")
        assert not state.get("extracted_claims")
        assert not state.get("selected_claim")
        assert not state.get("domain")
        assert not state.get("entities")

    @pytest.mark.asyncio
    async def test_fetch_error_progress_event_is_emitted(self, patched_fetch_httpx):
        """On short content, ``fetch_content`` still emits a
        ``Fetch error: CONTENT_TOO_SHORT:N`` progress event via the custom
        stream -- the SSE relay sees the failure boundary, carrying the
        measured word count."""
        agent = _short_content_url_agent(SHORT_CONTENT_URL)

        messages = _progress_messages(
            await _collect_custom_stream(agent, f"Process this URL: {SHORT_CONTENT_URL}")
        )

        assert any("Fetching article content" in m for m in messages), messages
        assert any(m.startswith("Fetch error: CONTENT_TOO_SHORT") for m in messages), messages


# ---------------------------------------------------------------------------
# S9/9.12: Opinion article with no factual claims -> error with NO_FACTUAL_CLAIMS
# ---------------------------------------------------------------------------


OPINION_URL = "https://example.com/opinion-article"


def _opinion_article_agent(url: str = OPINION_URL):
    """Scripted orchestrator for the no-factual-claims rejection path.

    The URL validates, the HTTP round-trip succeeds, the response is HTML,
    and extraction yields >=50 words — every fetch-level gate passes. The
    failure surfaces *inside* ``decompose_claims``: the LLM returns
    ``{"claims": []}`` because the article is pure opinion. The tool
    converts that empty list into ``error="NO_FACTUAL_CLAIMS"`` in its
    ToolMessage payload, and the orchestrator — seeing that error — stops
    Phase A and emits an IntakeOutput carrying only
    ``error="NO_FACTUAL_CLAIMS"``.
    """
    orchestrator = build_tool_call_orchestrator(
        [
            {"tool": "fetch_content", "args": {"url": url}},
            {
                "tool": "decompose_claims",
                "args": {
                    "article_text": "scripted opinion article text",
                    "article_title": "Opinion: Why We Should Rethink Our Priorities",
                },
            },
            "No factual claims found, stopping intake.",
            {
                "tool": "IntakeOutput",
                "args": {
                    "article_text": "",
                    "article_title": "",
                    "article_date": "",
                    "extracted_claims": [],
                    "error": "NO_FACTUAL_CLAIMS",
                },
            },
        ]
    )
    return build_fake_intake_agent(
        orchestrator_model=orchestrator,
        decompose_responses=['{"claims": []}'],
    )


class TestOpinionArticleReturnsNoFactualClaims:
    """S9/9.12: articles that pass every fetch-level gate (format, HTTP,
    content-type, word-count) but contain no verifiable factual claims are
    rejected by ``decompose_claims`` after the LLM returns an empty claims
    list. This is the first rejection code that originates from a *semantic*
    gate rather than a structural one.

    Guarantees:
      - structured_response carries ``error="NO_FACTUAL_CLAIMS"``.
      - ``httpx.AsyncClient`` IS constructed (the URL is valid and the HTTP
        round-trip completes; all fetch-level gates pass).
      - ``fetch_content``'s ToolMessage records ``success=True`` — proving
        the failure originates downstream of fetch, not at any fetch gate
        (distinguishes 9.12 from 9.8/9.9/9.10/9.11).
      - ``decompose_claims`` ran exactly once; its ToolMessage records
        ``claim_count=0`` and ``error="NO_FACTUAL_CLAIMS"``.
      - Phase B sub-tools (classify_domain, extract_entities) never run —
        the orchestrator correctly reads the decompose error and stops.
      - Rejection state carries no success fields (no selected_claim,
        domain, or entities).
    """

    @pytest.mark.asyncio
    async def test_structured_response_has_no_factual_claims_error(self, patched_fetch_httpx):
        """The canonical no-claims rejection surfaces as NO_FACTUAL_CLAIMS."""
        agent = _opinion_article_agent()

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {OPINION_URL}")]})

        state = result["structured_response"]
        assert state.get("error") == "NO_FACTUAL_CLAIMS"

    @pytest.mark.asyncio
    async def test_http_request_is_attempted(self, patched_fetch_httpx):
        """Every fetch-level gate passes, so ``httpx.AsyncClient`` is
        constructed and the HTTP round-trip completes. This distinguishes
        9.12 from the pre-fetch rejection paths (9.8 skips HTTP entirely)
        and from the fetch-level failure paths (9.9/9.10/9.11 surface
        errors from fetch_content itself)."""
        agent = _opinion_article_agent()

        await agent.ainvoke({"messages": [("user", f"Process this URL: {OPINION_URL}")]})

        assert patched_fetch_httpx.call_count >= 1, (
            "httpx.AsyncClient must be constructed on the no-claims "
            f"rejection path; got {patched_fetch_httpx.call_count} calls"
        )

    @pytest.mark.asyncio
    async def test_fetch_content_succeeded(self, patched_fetch_httpx):
        """fetch_content ran exactly once and succeeded — proving the
        failure originates downstream of the fetch pipeline, not at any
        fetch-level gate. Word count must also be >=50 (the OPINION_ARTICLE
        fixture is a real paragraph-length article, not a stub)."""
        agent = _opinion_article_agent()

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {OPINION_URL}")]})

        fetch_messages = [
            m
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "fetch_content"
        ]
        assert len(fetch_messages) == 1

        payload = json.loads(fetch_messages[0].content)
        assert payload["success"] is True
        assert payload["url"] == OPINION_URL
        assert payload["word_count"] >= 50
        assert "error" not in payload or not payload.get("error")

    @pytest.mark.asyncio
    async def test_decompose_claims_tool_records_no_factual_claims(self, patched_fetch_httpx):
        """decompose_claims ran exactly once; its ToolMessage records
        ``claim_count=0`` and ``error="NO_FACTUAL_CLAIMS"`` — proving the
        semantic gate fired inside the tool against the empty LLM response,
        not that the orchestrator fabricated the error code."""
        agent = _opinion_article_agent()

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {OPINION_URL}")]})

        decompose_messages = [
            m
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "decompose_claims"
        ]
        assert len(decompose_messages) == 1

        payload = json.loads(decompose_messages[0].content)
        assert payload["claim_count"] == 0
        assert payload["claims"] == []
        assert payload.get("error") == "NO_FACTUAL_CLAIMS"

    @pytest.mark.asyncio
    async def test_phase_b_sub_tools_never_run(self, patched_fetch_httpx):
        """classify_domain and extract_entities never run on the no-claims
        rejection path — the orchestrator reads decompose_claims's error
        and stops Phase A before any Phase B sub-LLM call is made."""
        agent = _opinion_article_agent()

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {OPINION_URL}")]})

        phase_b_tools = {"classify_domain", "extract_entities"}
        ran = [
            getattr(m, "name", None)
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) in phase_b_tools
        ]
        assert ran == [], f"expected no Phase B tool messages on rejection, got {ran}"

    @pytest.mark.asyncio
    async def test_rejection_state_has_no_success_fields(self, patched_fetch_httpx):
        """Rejection payload is minimal: no extracted claims, no selected
        claim, no domain or entities populated — success-path fields stay
        absent. (article_text/article_title are scripted empty here; the
        orchestrator's IntakeOutput mirrors what a real orchestrator would
        emit when no claim is selectable.)"""
        agent = _opinion_article_agent()

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {OPINION_URL}")]})

        state = result["structured_response"]
        assert state.get("error") == "NO_FACTUAL_CLAIMS"
        assert not state.get("extracted_claims")
        assert not state.get("selected_claim")
        assert not state.get("domain")
        assert not state.get("entities")

    @pytest.mark.asyncio
    async def test_tool_call_order_is_fetch_then_decompose_only(self, patched_fetch_httpx):
        """Tool-call timeline is exactly fetch_content → decompose_claims,
        with no classify_domain or extract_entities after. Pins the
        rejection-path trajectory: Phase A runs to completion; Phase B
        never starts."""
        agent = _opinion_article_agent()

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {OPINION_URL}")]})

        tool_names = [
            getattr(m, "name", None)
            for m in result["messages"]
            if getattr(m, "type", None) == "tool"
            and getattr(m, "name", None)
            in {"fetch_content", "decompose_claims", "classify_domain", "extract_entities"}
        ]
        assert tool_names == ["fetch_content", "decompose_claims"], tool_names

    @pytest.mark.asyncio
    async def test_progress_events_reach_found_zero_claims(self, patched_fetch_httpx):
        """The custom stream emits the decompose boundary's progress
        events even when the LLM returns zero claims: the "Analyzing..."
        pre-call event and the "Found 0 claims for review" post-parse
        event are both observable by the SSE relay."""
        agent = _opinion_article_agent()

        messages = _progress_messages(
            await _collect_custom_stream(agent, f"Process this URL: {OPINION_URL}")
        )

        assert any("Fetching article content" in m for m in messages), messages
        assert any("Analyzing article for factual claims" in m for m in messages), messages
        assert any(m == "Found 0 claims for review" for m in messages), messages
        # Phase B progress events must never appear on the rejection path.
        assert not any(m.startswith("Domain classified:") for m in messages), messages
        assert not any(m.startswith("Entities extracted:") for m in messages), messages


# ---------------------------------------------------------------------------
# S9/9.14: All LLM sub-calls receive RunnableConfig
# ---------------------------------------------------------------------------


class _ChatModelStartTracker(BaseCallbackHandler):
    """Records ``on_chat_model_start`` events from every LLM invocation.

    A single instance is registered once via the top-level
    ``agent.ainvoke(..., config={"callbacks": [tracker], "tags": [...]})``.
    Each sub-tool that forwards its injected ``RunnableConfig`` to
    ``model.ainvoke(..., config=config)`` will propagate this tracker into
    its chat-model callback tree; each sub-tool that fails to forward
    config would break the propagation chain for that sub-call and its
    callback would never fire.
    """

    def __init__(self) -> None:
        self.invocations: list[dict[str, Any]] = []

    def on_chat_model_start(  # type: ignore[override]
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        **kwargs: Any,
    ) -> None:
        first_system = ""
        if messages and messages[0]:
            head = messages[0][0]
            content = getattr(head, "content", "")
            if isinstance(content, str):
                first_system = content
        self.invocations.append(
            {
                "system": first_system,
                "tags": list(kwargs.get("tags") or []),
            }
        )


_DECOMPOSE_SYSTEM_PREFIX = "You are a claim extraction system"
_CLASSIFY_SYSTEM_PREFIX = "You are a domain classifier"
_ENTITY_SYSTEM_PREFIX = "You are a named entity recognition"

_SUB_LLM_PREFIXES = (
    _DECOMPOSE_SYSTEM_PREFIX,
    _CLASSIFY_SYSTEM_PREFIX,
    _ENTITY_SYSTEM_PREFIX,
)

_CONFIG_PROPAGATION_TAG = "test-intake-runnable-config-propagation"


def _sub_llm_invocations(tracker: _ChatModelStartTracker) -> list[dict[str, Any]]:
    """Filter tracker invocations down to the three intake sub-LLM calls.

    The orchestrator's own chat-model starts are discarded: it is driven by a
    ``FakeMessagesListChatModel`` that receives the react agent's working
    conversation (HumanMessage + ToolMessages + the main intake SYSTEM_PROMPT),
    not one of the three sub-tool system prompts. Filtering by the unique
    system-message prefix of each sub-tool isolates the decompose_claims,
    classify_domain, and extract_entities LLM calls.
    """
    return [
        inv
        for inv in tracker.invocations
        if any(inv["system"].startswith(prefix) for prefix in _SUB_LLM_PREFIXES)
    ]


class TestAllLlmSubCallsReceiveRunnableConfig:
    """S9/9.14: every LLM sub-call (decompose_claims, classify_domain,
    extract_entities) receives the caller's ``RunnableConfig``.

    Verified by registering a ``BaseCallbackHandler`` on the top-level
    ``agent.ainvoke`` config. ``FakeListChatModel.ainvoke`` fires
    ``on_chat_model_start`` whenever a sub-tool invokes it with a config
    whose callback tree includes this handler; a tool that fails to forward
    its injected ``RunnableConfig`` would break propagation for that
    sub-call and its callback would be absent from the tracker. We also
    propagate a unique tag from the top-level config and assert it is
    visible on each sub-call's callback invocation -- this confirms the
    RunnableConfig itself flows, not merely the callback manager.
    """

    @pytest.mark.asyncio
    async def test_each_sub_llm_invokes_top_level_callback(self, patched_fetch_httpx):
        """All three sub-LLM invocations fire ``on_chat_model_start`` on the
        handler registered via the top-level RunnableConfig, proving their
        tools forwarded config through to ``model.ainvoke``."""
        tracker = _ChatModelStartTracker()
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        await agent.ainvoke(
            {"messages": [("user", f"Process this URL: {NEWS_URL}")]},
            config={"callbacks": [tracker]},
        )

        sub_calls = _sub_llm_invocations(tracker)
        systems = [inv["system"] for inv in sub_calls]

        decompose = [s for s in systems if s.startswith(_DECOMPOSE_SYSTEM_PREFIX)]
        classify = [s for s in systems if s.startswith(_CLASSIFY_SYSTEM_PREFIX)]
        entity = [s for s in systems if s.startswith(_ENTITY_SYSTEM_PREFIX)]

        assert len(decompose) == 1, (
            "decompose_claims LLM sub-call did not fire the top-level callback "
            f"(saw {len(decompose)}); config was not forwarded to model.ainvoke"
        )
        assert len(classify) == 1, (
            "classify_domain LLM sub-call did not fire the top-level callback "
            f"(saw {len(classify)}); config was not forwarded to model.ainvoke"
        )
        assert len(entity) == 1, (
            "extract_entities LLM sub-call did not fire the top-level callback "
            f"(saw {len(entity)}); config was not forwarded to model.ainvoke"
        )

    @pytest.mark.asyncio
    async def test_top_level_tag_propagates_to_every_sub_llm(self, patched_fetch_httpx):
        """A unique ``tags`` value on the top-level RunnableConfig appears in
        every sub-LLM callback invocation -- confirming the RunnableConfig
        itself (not just the callback manager) flows into each sub-call.

        If a tool called ``model.ainvoke(messages)`` without its injected
        config, the child run would start from an empty config and this tag
        would be missing from the corresponding sub-call's tags.
        """
        tracker = _ChatModelStartTracker()
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        await agent.ainvoke(
            {"messages": [("user", f"Process this URL: {NEWS_URL}")]},
            config={"callbacks": [tracker], "tags": [_CONFIG_PROPAGATION_TAG]},
        )

        sub_calls = _sub_llm_invocations(tracker)
        assert len(sub_calls) == 3, (
            "expected exactly 3 sub-LLM invocations (decompose, classify, "
            f"extract); got {len(sub_calls)}: "
            f"{[inv['system'][:40] for inv in sub_calls]}"
        )

        for inv in sub_calls:
            assert _CONFIG_PROPAGATION_TAG in inv["tags"], (
                f"top-level tag {_CONFIG_PROPAGATION_TAG!r} missing from "
                f"sub-call tags {inv['tags']!r} (system prefix "
                f"{inv['system'][:40]!r}); RunnableConfig did not propagate"
            )

    @pytest.mark.asyncio
    async def test_sub_llm_callbacks_observed_in_tool_call_order(self, patched_fetch_httpx):
        """Sub-LLM callback invocations arrive in the pipeline's
        canonical order: decompose -> classify -> extract. This is a
        stronger check than mere presence -- it verifies the tracker was
        not merely re-invoked by retries, caching, or some unrelated path,
        but observed each sub-call exactly once in the expected sequence.
        """
        tracker = _ChatModelStartTracker()
        agent = _scripted_intake_agent_phase_b(_CANNED_CLAIMS, _SELECTED_CLAIM)

        await agent.ainvoke(
            {"messages": [("user", f"Process this URL: {NEWS_URL}")]},
            config={"callbacks": [tracker]},
        )

        sub_calls = _sub_llm_invocations(tracker)

        def _label(inv: dict[str, Any]) -> str:
            system = inv["system"]
            if system.startswith(_DECOMPOSE_SYSTEM_PREFIX):
                return "decompose"
            if system.startswith(_CLASSIFY_SYSTEM_PREFIX):
                return "classify"
            if system.startswith(_ENTITY_SYSTEM_PREFIX):
                return "extract"
            return "other"

        assert [_label(inv) for inv in sub_calls] == [
            "decompose",
            "classify",
            "extract",
        ]


# ---------------------------------------------------------------------------
# S9/9.17: Every claim's `quote` is a substring of the fetched article text
# ---------------------------------------------------------------------------


def _fetch_content_payload(result: dict) -> dict:
    """Return the decoded JSON payload from the single ``fetch_content`` ToolMessage."""
    fetch_messages = [
        m
        for m in result["messages"]
        if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "fetch_content"
    ]
    assert len(fetch_messages) == 1, "expected exactly one fetch_content ToolMessage"
    return json.loads(fetch_messages[0].content)


def _decompose_claims_payload(result: dict) -> dict:
    """Return the decoded JSON payload from the single ``decompose_claims`` ToolMessage."""
    decompose_messages = [
        m
        for m in result["messages"]
        if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "decompose_claims"
    ]
    assert len(decompose_messages) == 1, "expected exactly one decompose_claims ToolMessage"
    return json.loads(decompose_messages[0].content)


class TestQuoteIsSubstringOfArticleText:
    """S9/9.17: every extracted claim's ``quote`` field is a verbatim
    substring of the article text returned by ``fetch_content``.

    The ``quote`` is defined (design.md §7) as the "single best sentence
    from the article" supporting the claim. A non-substring quote means
    the LLM fabricated or paraphrased the source text, which breaks the
    downstream promise that every claim can be traced back to article
    prose. These tests lock that invariant against the canned
    ``_CANNED_CLAIMS`` fixtures whose quotes are drawn verbatim from
    ``NEWS_ARTICLE_HTML``; trafilatura collapses paragraph-internal
    newlines to spaces, so a byte-for-byte ``in`` check is the correct
    assertion -- any regression that alters the extraction pipeline or
    pollutes the quote text will fail this test before downstream
    consumers see the bad data.
    """

    @pytest.mark.asyncio
    async def test_every_structured_response_quote_is_in_article_text(self, patched_fetch_httpx):
        """Every ``extracted_claims[i].quote`` in the final IntakeOutput is
        a substring of the text returned by ``fetch_content``."""
        agent = _scripted_intake_agent(_CANNED_CLAIMS)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        article_text = _fetch_content_payload(result)["text"]
        assert article_text, "fetch_content must return non-empty article text"

        claims = result["structured_response"]["extracted_claims"]
        assert claims, "structured_response must carry extracted claims"

        for claim in claims:
            quote = claim["quote"]
            assert quote in article_text, (
                f"quote is not a verbatim substring of article text: "
                f"quote={quote!r} article_text={article_text!r}"
            )

    @pytest.mark.asyncio
    async def test_every_decompose_tool_message_quote_is_in_article_text(self, patched_fetch_httpx):
        """Every ``claims[i].quote`` in the ``decompose_claims`` ToolMessage
        payload is a substring of the text returned by ``fetch_content``.

        Checking at the tool-message layer (not just the structured_response)
        catches regressions where the decompose tool itself emits bad quotes
        that a later terminal step would otherwise silently relay."""
        agent = _scripted_intake_agent(_CANNED_CLAIMS)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        article_text = _fetch_content_payload(result)["text"]
        decompose_payload = _decompose_claims_payload(result)

        assert decompose_payload["claim_count"] == len(_CANNED_CLAIMS)
        for claim in decompose_payload["claims"]:
            quote = claim["quote"]
            assert quote in article_text, (
                f"decompose_claims emitted a quote not present in article text: "
                f"quote={quote!r} article_text={article_text!r}"
            )

    @pytest.mark.asyncio
    async def test_quote_substring_holds_for_single_claim(self, patched_fetch_httpx):
        """Lower bound: a single-claim article still satisfies the substring
        invariant end-to-end."""
        single = [_CANNED_CLAIMS[0]]
        agent = _scripted_intake_agent(single)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        article_text = _fetch_content_payload(result)["text"]
        claims = result["structured_response"]["extracted_claims"]
        assert len(claims) == 1
        assert claims[0]["quote"] in article_text

    @pytest.mark.asyncio
    async def test_quote_substring_holds_for_five_claims(self, patched_fetch_httpx):
        """Upper bound: the 1-5 claim window's maximum case still satisfies
        the substring invariant for every emitted claim. Indices are
        rewritten so duplicated fixtures remain well-formed."""
        five = [{**_CANNED_CLAIMS[i % len(_CANNED_CLAIMS)], "index": i + 1} for i in range(5)]
        agent = _scripted_intake_agent(five)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        article_text = _fetch_content_payload(result)["text"]
        claims = result["structured_response"]["extracted_claims"]
        assert len(claims) == 5
        for claim in claims:
            assert claim["quote"] in article_text

    @pytest.mark.asyncio
    async def test_structured_response_and_tool_message_agree_on_quotes(self, patched_fetch_httpx):
        """The ``quote`` field carried through the decompose ToolMessage
        matches the quote surfaced in the final IntakeOutput, so the
        substring invariant proven on one layer also applies to the other.

        This guards against a regression where either layer rewrites quote
        text in a way that drifts from the article."""
        agent = _scripted_intake_agent(_CANNED_CLAIMS)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        structured_quotes = [c["quote"] for c in result["structured_response"]["extracted_claims"]]
        tool_quotes = [c["quote"] for c in _decompose_claims_payload(result)["claims"]]

        assert structured_quotes == tool_quotes

    @pytest.mark.asyncio
    async def test_fabricated_quote_is_not_a_substring(self, patched_fetch_httpx):
        """Sanity control: a quote fabricated to not appear in the article
        text must fail the substring check. This proves the invariant
        asserted above is non-vacuous -- if the ``in`` operator were
        trivially true (e.g. empty-string handling), the positive tests
        above would pass even on a broken pipeline."""
        fabricated = [
            {
                **_CANNED_CLAIMS[0],
                "quote": "This sentence does not appear anywhere in the article.",
            }
        ]
        agent = _scripted_intake_agent(fabricated)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {NEWS_URL}")]})

        article_text = _fetch_content_payload(result)["text"]
        claims = result["structured_response"]["extracted_claims"]
        assert len(claims) == 1
        assert claims[0]["quote"] not in article_text, (
            "fabricated sentinel quote unexpectedly appeared in the extracted "
            "article text -- the NEWS_ARTICLE_HTML fixture or the sentinel "
            "string needs to be updated so this negative control is meaningful"
        )


# ---------------------------------------------------------------------------
# S9/9.18: HTTP fetch uses 10s timeout — mock transport verifies
#          TimeoutException caught
# ---------------------------------------------------------------------------


TIMEOUT_URL = "https://example.com/timeout"


def _timeout_url_agent(bad_url: str):
    """Scripted orchestrator for the timeout rejection path.

    Replays the trajectory a real orchestrator would take after observing
    ``fetch_content`` return ``success=False`` with ``error="FETCH_TIMEOUT"``:
    no further tool calls, and an IntakeOutput carrying only the canonical
    user-facing ``URL_UNREACHABLE`` code (which collapses FETCH_TIMEOUT).
    """
    orchestrator = build_tool_call_orchestrator(
        [
            {"tool": "fetch_content", "args": {"url": bad_url}},
            "URL timed out, stopping intake.",
            {
                "tool": "IntakeOutput",
                "args": {
                    "article_text": "",
                    "article_title": "",
                    "article_date": "",
                    "extracted_claims": [],
                    "error": "URL_UNREACHABLE",
                },
            },
        ]
    )
    return build_fake_intake_agent(orchestrator_model=orchestrator)


class TestHttpFetchUses10SecondTimeout:
    """S9/9.18: The intake agent's HTTP fetch uses a 10-second request
    timeout, and ``httpx.TimeoutException`` raised by the transport is
    caught at the fetch layer and surfaced as ``FETCH_TIMEOUT`` in the
    ``fetch_content`` ToolMessage payload -- no uncaught exception
    escapes to the orchestrator.

    Guarantees:
      - ``fetch_content``'s request timeout constant is exactly 10.0s
        (spec S4/4.4 / intake-redesign).
      - Every ``httpx.AsyncClient`` constructed by the fetch tool passes
        ``timeout=10.0``; the constant propagates end-to-end.
      - A mock transport raising ``httpx.TimeoutException`` is translated
        into a ``fetch_content`` payload with ``success=False,
        error='FETCH_TIMEOUT'``; the exception never leaks to the agent.
    """

    def test_request_timeout_constant_is_10_seconds(self):
        """The module-level ``_REQUEST_TIMEOUT`` is 10.0s per the
        intake-redesign spec. Guarding the constant itself defends against
        silent regressions during future refactors of ``fetch_content``."""
        from swarm_reasoning.agents.intake.tools.fetch_content import (
            _REQUEST_TIMEOUT,
        )

        assert _REQUEST_TIMEOUT == 10.0, (
            "fetch_content HTTP timeout must be 10.0s per intake-redesign "
            f"spec S4/4.4; got {_REQUEST_TIMEOUT}"
        )

    @pytest.mark.asyncio
    async def test_httpx_async_client_constructed_with_10s_timeout(self, patched_fetch_httpx):
        """End-to-end check: invoking the intake agent constructs
        ``httpx.AsyncClient`` with ``timeout=10.0`` on the fetch path.
        This proves the spec constant propagates through ``fetch_html``
        into the live client construction, not just the module source."""
        agent = _timeout_url_agent(TIMEOUT_URL)

        await agent.ainvoke({"messages": [("user", f"Process this URL: {TIMEOUT_URL}")]})

        assert patched_fetch_httpx.call_count >= 1, (
            "httpx.AsyncClient must be constructed on the fetch path; "
            f"got {patched_fetch_httpx.call_count} calls"
        )
        timeouts = [call.kwargs.get("timeout") for call in patched_fetch_httpx.call_args_list]
        assert all(t == 10.0 for t in timeouts), (
            f"httpx.AsyncClient called with timeouts={timeouts}; expected 10.0"
        )

    @pytest.mark.asyncio
    async def test_mock_timeout_exception_is_caught_as_fetch_timeout(self, patched_fetch_httpx):
        """The mock transport raises ``httpx.TimeoutException`` for any
        URL ending ``/timeout``. ``fetch_html`` must catch it and raise
        ``FetchError('FETCH_TIMEOUT')``, which the ``fetch_content`` tool
        surfaces as ``success=False, error='FETCH_TIMEOUT'`` in its
        ToolMessage payload. No uncaught ``httpx.TimeoutException``
        escapes the tool."""
        agent = _timeout_url_agent(TIMEOUT_URL)

        result = await agent.ainvoke({"messages": [("user", f"Process this URL: {TIMEOUT_URL}")]})

        fetch_messages = [
            m
            for m in result["messages"]
            if getattr(m, "type", None) == "tool" and getattr(m, "name", None) == "fetch_content"
        ]
        assert len(fetch_messages) == 1, (
            f"fetch_content must run exactly once; got {len(fetch_messages)}"
        )

        payload = json.loads(fetch_messages[0].content)
        assert payload["success"] is False
        assert payload["error"] == "FETCH_TIMEOUT"
        assert payload["url"] == TIMEOUT_URL
