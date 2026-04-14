"""Consolidated evidence handler -- LangGraph ReAct agent (ADR-004, ADR-016).

Combines claimreview-matcher and domain-evidence into a single Phase 2a agent.
Uses search_factchecks for ClaimReview API lookups and domain evidence tools
for authoritative source research. Publishes both CLAIMREVIEW_* and DOMAIN_*
observations from a single agent stream.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool

from swarm_reasoning.agents._utils import register_handler
from swarm_reasoning.agents.domain_evidence.tools import DOMAIN_EVIDENCE_TOOLS
from swarm_reasoning.agents.evidence.tools import search_factchecks
from swarm_reasoning.agents.langgraph_base import LangGraphBase
from swarm_reasoning.agents.observation_tools import publish_observation, publish_progress
from swarm_reasoning.models.observation import ObservationCode

AGENT_NAME = "evidence"


@register_handler("evidence")
class EvidenceHandler(LangGraphBase):
    """Consolidated evidence agent: ClaimReview lookup + domain source research."""

    AGENT_NAME = AGENT_NAME

    def _tools(self) -> list[BaseTool]:
        return [
            search_factchecks,
            *DOMAIN_EVIDENCE_TOOLS,
            publish_observation,
            publish_progress,
        ]

    def _system_prompt(self) -> str:
        return (
            "You are an evidence-gathering agent. Your job is two-fold:\n\n"
            "## Task 1: Fact-Check Lookup\n"
            "Search for existing fact-checks of the claim using the "
            "search_factchecks tool. This publishes CLAIMREVIEW_* observations "
            "automatically.\n\n"
            "## Task 2: Domain Evidence Research\n"
            "Research authoritative domain sources for evidence about the claim:\n"
            "1. Use lookup_domain_sources with the claim's domain to find sources.\n"
            "2. Use derive_search_query to build a search query from the claim.\n"
            "3. Use format_source_url to create URLs from templates.\n"
            "4. Use fetch_source_content to retrieve content.\n"
            "5. Use check_content_relevance to verify the content is relevant.\n"
            "6. Use score_claim_alignment to assess alignment.\n"
            "7. Use compute_evidence_confidence to calculate confidence.\n"
            "8. Use publish_observation to publish these four observations:\n"
            "   - DOMAIN_SOURCE_NAME (ST): the source name\n"
            "   - DOMAIN_SOURCE_URL (ST): the source URL\n"
            "   - DOMAIN_EVIDENCE_ALIGNMENT (CWE): the alignment score\n"
            "   - DOMAIN_CONFIDENCE (NM): the confidence score\n\n"
            "## Execution Order\n"
            "1. Use publish_progress to announce you are gathering evidence.\n"
            "2. Run Task 1 (call search_factchecks once).\n"
            "3. Run Task 2 (domain source research and publish observations).\n"
            "4. Use publish_progress to report the outcome.\n\n"
            "Do not fabricate results. If no sources are found, publish "
            "DOMAIN_SOURCE_NAME='N/A', DOMAIN_SOURCE_URL='N/A', "
            "DOMAIN_EVIDENCE_ALIGNMENT='ABSENT^No Evidence Found^FCK', "
            "DOMAIN_CONFIDENCE='0.00'."
        )

    def _primary_code(self) -> ObservationCode:
        return ObservationCode.DOMAIN_EVIDENCE_ALIGNMENT
