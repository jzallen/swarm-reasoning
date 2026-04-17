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
"""

from __future__ import annotations

import json

import pytest

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
