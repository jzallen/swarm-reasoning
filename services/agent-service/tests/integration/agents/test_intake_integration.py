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
