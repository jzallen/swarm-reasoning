"""Evidence agent -- ClaimReview lookup + domain-source evidence gathering.

Mirrors the intake agent pattern: a thin ``_EvidenceAgent`` wrapper that
builds a fresh ``langchain.agents.create_agent`` graph per invocation,
each call binding @tool definitions to a per-invocation accumulator dict.
After the agent completes, ``_assemble_output(acc)`` deterministically
builds the EvidenceOutput so the LLM never echoes structured JSON back.

Pipeline integration (PipelineContext, observation publishing,
PipelineState ↔ EvidenceInput translation) lives in the pipeline node
wrapper, not here. Each @tool def imports its tool submodule locally so
the module top stays free of tool-implementation imports.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncIterator

from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from swarm_reasoning.agents.evidence.models import EvidenceInput, EvidenceOutput
from swarm_reasoning.temporal.errors import MissingApiKeyError

logger = logging.getLogger(__name__)

AGENT_NAME = "evidence"
AGENT_MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = (
    "You are an evidence-gathering agent in a fact-checking pipeline. "
    "Gather evidence for or against the given claim using your tools.\n\n"
    "Workflow:\n"
    "1. Search for existing fact-checks with search_factchecks\n"
    "2. Look up domain-authoritative sources with lookup_domain_sources\n"
    "3. Fetch content from the top source with fetch_source_content\n"
    "4. Score the fetched content with score_evidence\n\n"
    "Always start with the fact-check lookup. Then proceed to domain "
    "sources. Try up to 3 domain source URLs if the first returns an "
    "error. Stop after scoring evidence from one successful source.\n\n"
    "After completing the workflow, reply with a one-line confirmation. "
    "Do NOT attempt to echo tool outputs back as JSON -- the system "
    "captures tool results directly."
)


# ---------------------------------------------------------------------------
# Deterministic EvidenceOutput assembly
# ---------------------------------------------------------------------------


def _assemble_output(acc: dict[str, Any]) -> EvidenceOutput:
    """Build an EvidenceOutput from captured tool outputs."""
    return EvidenceOutput(
        claimreview_matches=list(acc.get("claimreview_matches", []) or []),
        domain_sources=list(acc.get("domain_sources", []) or []),
        evidence_confidence=float(acc.get("best_confidence", 0.0)),
    )


def _format_claim_message(evidence_input: EvidenceInput) -> str:
    """Render the user message that frames the gathering task for the LLM."""
    persons = ", ".join(evidence_input.get("persons", []) or [])
    organizations = ", ".join(evidence_input.get("organizations", []) or [])
    return (
        "Gather evidence for this claim:\n\n"
        f"Claim: {evidence_input.get('claim_text', '')}\n"
        f"Domain: {evidence_input.get('domain', 'OTHER')}\n"
        f"Persons: {persons}\n"
        f"Organizations: {organizations}"
    )


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------


class _EvidenceAgent:
    """Wrapper exposing ``ainvoke``/``astream`` over a per-invocation agent.

    Each invocation builds a fresh ``create_agent`` graph whose tools
    write into a local accumulator. After the underlying agent completes,
    ``_assemble_output(acc)`` builds an EvidenceOutput which is injected
    into the final state as ``structured_response`` -- matching intake's
    contract so pipeline node consumers can read the structured result
    deterministically rather than parsing the LLM's free-text reply.
    """

    def __init__(self, orchestrator_model: ChatAnthropic) -> None:
        self._orchestrator_model = orchestrator_model

    def _build_tools(self, evidence_input: EvidenceInput, acc: dict[str, Any]) -> list[Any]:
        @tool
        async def search_factchecks(reason: str) -> str:
            """Search Google Fact Check Tools API for existing reviews of the claim.

            Args:
                reason: Short rationale for issuing the search; ignored by the tool.
            """
            from swarm_reasoning.agents.evidence.tools import (
                search_factchecks as search_mod,
            )
            from swarm_reasoning.agents.messaging import (
                share_heartbeat,
                share_progress,
            )

            del reason
            share_progress("Searching fact-check databases...")
            share_heartbeat(AGENT_NAME)
            result = await search_mod.search_factchecks(
                claim=evidence_input.get("claim_text", ""),
                persons=evidence_input.get("persons"),
                organizations=evidence_input.get("organizations"),
            )
            share_heartbeat(AGENT_NAME)
            if result.error:
                return f"Error: {result.error}"
            if not result.matched:
                return "No matching fact-checks found."

            match = {
                "source": result.source,
                "rating": result.rating,
                "url": result.url,
                "score": round(result.score, 2),
            }
            acc.setdefault("claimreview_matches", []).append(match)
            return (
                f"Match found (score: {result.score:.2f}):\n"
                f"  Rating: {result.rating}\n"
                f"  Source: {result.source}\n"
                f"  URL: {result.url}"
            )

        @tool
        def lookup_domain_sources(reason: str) -> str:
            """Look up authoritative sources for the claim's domain.

            Returns a JSON list of sources with name and pre-formatted URL.

            Args:
                reason: Short rationale for the lookup; ignored by the tool.
            """
            from swarm_reasoning.agents.evidence.tools import lookup_domain_sources as lookup_mod
            from swarm_reasoning.agents.messaging import share_progress

            del reason
            share_progress("Looking up domain-authoritative sources...")
            domain = evidence_input.get("domain", "OTHER")
            sources = lookup_mod.lookup_domain_sources(domain)
            search_query = lookup_mod.derive_search_query(
                evidence_input.get("claim_text", ""),
                evidence_input.get("persons"),
                evidence_input.get("organizations"),
                evidence_input.get("statistics"),
                evidence_input.get("dates"),
            )
            return json.dumps(
                [
                    {
                        "name": s.name,
                        "url": lookup_mod.format_source_url(s.url_template, search_query),
                    }
                    for s in sources
                ]
            )

        @tool
        async def fetch_source_content(url: str) -> str:
            """Fetch text content from a source URL.

            Args:
                url: The full URL to fetch (use URLs from lookup_domain_sources).
            """
            from swarm_reasoning.agents.evidence.tools import (
                fetch_source_content as fetch_mod,
            )
            from swarm_reasoning.agents.messaging import (
                share_heartbeat,
                share_progress,
            )

            share_progress(f"Fetching source: {url}")
            share_heartbeat(AGENT_NAME)
            result = await fetch_mod.fetch_source_content(url)
            share_heartbeat(AGENT_NAME)
            if result.error:
                return f"Error fetching {url}: {result.error}"
            return result.content

        @tool
        def score_evidence(content: str, source_name: str, source_url: str) -> str:
            """Score how well fetched content aligns with the claim.

            Args:
                content: The fetched source content to evaluate.
                source_name: Name of the source (e.g. CDC, WHO).
                source_url: URL the content was fetched from.
            """
            from swarm_reasoning.agents.evidence.tools import score_evidence as score_mod
            from swarm_reasoning.agents.messaging import share_progress

            share_progress(f"Scoring evidence from {source_name}...")
            alignment_result = score_mod.score_claim_alignment(
                content, evidence_input.get("claim_text", "")
            )
            confidence = score_mod.compute_evidence_confidence(alignment_result.alignment)

            acc.setdefault("domain_sources", []).append(
                {
                    "name": source_name,
                    "url": source_url,
                    "alignment": alignment_result.alignment.value,
                    "confidence": confidence,
                }
            )
            if confidence > acc.get("best_confidence", 0.0):
                acc["best_confidence"] = confidence

            return (
                f"Alignment: {alignment_result.alignment.value} "
                f"({alignment_result.description})\n"
                f"Confidence: {confidence:.2f}"
            )

        return [search_factchecks, lookup_domain_sources, fetch_source_content, score_evidence]

    def _compile(self, evidence_input: EvidenceInput, acc: dict[str, Any]) -> Any:
        return create_agent(
            model=self._orchestrator_model,
            tools=self._build_tools(evidence_input, acc),
            system_prompt=SYSTEM_PROMPT,
            name=AGENT_NAME,
        )

    @staticmethod
    def _new_acc() -> dict[str, Any]:
        return {"claimreview_matches": [], "domain_sources": [], "best_confidence": 0.0}

    async def ainvoke(
        self,
        evidence_input: EvidenceInput,
        config: RunnableConfig | None = None,
    ) -> dict[str, Any]:
        acc = self._new_acc()
        agent = self._compile(evidence_input, acc)
        claim_msg = _format_claim_message(evidence_input)
        result = await agent.ainvoke({"messages": [("user", claim_msg)]}, config=config)
        result["structured_response"] = _assemble_output(acc)
        return result

    async def astream(
        self,
        evidence_input: EvidenceInput,
        stream_mode: str | list[str] | None = None,
        config: RunnableConfig | None = None,
    ) -> AsyncIterator[Any]:
        acc = self._new_acc()
        agent = self._compile(evidence_input, acc)
        claim_msg = _format_claim_message(evidence_input)

        multi_mode = isinstance(stream_mode, list)
        last_values: dict[str, Any] | None = None

        async for item in agent.astream(
            {"messages": [("user", claim_msg)]},
            stream_mode=stream_mode,
            config=config,
        ):
            if multi_mode and isinstance(item, tuple) and item[0] == "values":
                last_values = item[1]
            elif not multi_mode and stream_mode == "values":
                last_values = item
            yield item

        structured = _assemble_output(acc)
        if last_values is None:
            final: dict[str, Any] = {"structured_response": structured}
        else:
            final = dict(last_values)
            final["structured_response"] = structured
        yield ("values", final) if multi_mode else final


def build_evidence_agent(model: ChatAnthropic | None = None) -> _EvidenceAgent:
    """Build the evidence agent.

    Args:
        model: Optional ChatAnthropic instance for the orchestrator. If
            None, one is created from the ANTHROPIC_API_KEY environment
            variable.

    Returns:
        An ``_EvidenceAgent`` wrapper exposing ``ainvoke`` and ``astream``.
        Each call runs a fresh ``create_agent`` graph and injects a
        deterministically-assembled ``EvidenceOutput`` into the final
        state as ``structured_response``.
    """
    if model is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise MissingApiKeyError("ANTHROPIC_API_KEY is required for evidence agent")
        model = ChatAnthropic(
            model=AGENT_MODEL,
            max_tokens=1024,
            temperature=0,
            api_key=api_key,
        )

    return _EvidenceAgent(orchestrator_model=model)
