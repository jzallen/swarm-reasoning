"""LLM scorer subagent for the evidence agent's ``score_evidence`` task.

Builds a ``create_agent`` subagent that judges alignment of a fetched
source page against a claim. Verdict is recorded by the inline
``record_alignment`` ``@tool`` closure, which delegates to the plain
implementation in :mod:`...tools.record_alignment` and wraps the result
in a ``Command(update=...)`` containing the matching ``ToolMessage``.

Framework coupling (``@tool``, ``ToolRuntime``, ``Command``,
``ToolMessage``) stays at this registration site; the plain impl module
remains framework-free.
"""

from __future__ import annotations

from typing import Any, Literal

from langchain.agents import AgentState, create_agent
from langchain.tools import ToolRuntime
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command
from typing_extensions import NotRequired

from swarm_reasoning.agents.evidence.tasks.score_evidence.tools.record_alignment import (
    record_alignment as record_alignment_impl,
)

SCORER_NAME = "evidence-scorer"
SCORER_MODEL = "claude-haiku-4-5-20251001"
SCORER_TEMPERATURE = 0.4
SCORER_MAX_TOKENS = 512

_SCORER_SYSTEM_PROMPT = """\
You judge whether a fetched source page actually supports a specific claim.

You will see: the claim, the source name, its URL, and an excerpt of the page
content. Decide ONE of:

  SUPPORTS     -- the content directly affirms the claim.
  CONTRADICTS  -- the content directly refutes or disproves the claim.
  PARTIAL      -- the content addresses the topic and is consistent with the
                  claim but does not fully confirm every element of it.
  ABSENT       -- the content does NOT bear on the claim. Use ABSENT when:
                    * the page is an empty search-results page
                      (e.g. "No results found", "0 results for ...")
                    * the page is a generic search form, login wall, or
                      error page
                    * the content is unrelated to the claim entirely
                    * the page only echoes your search query back without
                      returning any substantive article, dataset, or
                      release. A page that only contains query terms in
                      its chrome (breadcrumbs, search box label, "You
                      searched for: ...") is ABSENT.

Call the ``record_alignment`` tool exactly once with your verdict and a
1-2 sentence rationale quoting the page text that drove your decision.
If the excerpt is obviously an empty search page, say so in the rationale
and record ABSENT -- do NOT record SUPPORTS just because the query terms
appear on the page."""


class _ScorerState(AgentState):
    """Scorer subagent state: inherits messages from AgentState and adds
    the verdict fields tools write via ``Command(update=...)``."""

    alignment: NotRequired[str]
    rationale: NotRequired[str]


def build_scorer_subagent() -> Any:
    """Build the LLM-backed alignment scorer as a ``create_agent`` subagent.

    One inline ``@tool`` (``record_alignment``) writes the verdict into
    ``_ScorerState`` via ``Command(update=...)``. Model temperature is
    ``SCORER_TEMPERATURE`` (0.4) to give the LLM enough latitude to
    recognize degenerate pages (empty search results, login walls) as
    ABSENT rather than rubber-stamping keyword overlap.
    """
    model = ChatAnthropic(
        model=SCORER_MODEL,
        max_tokens=SCORER_MAX_TOKENS,
        temperature=SCORER_TEMPERATURE,
    )

    @tool
    def record_alignment(
        alignment: Literal["SUPPORTS", "CONTRADICTS", "PARTIAL", "ABSENT"],
        rationale: str,
        runtime: ToolRuntime,
    ) -> Command:
        """Record your alignment verdict for the fetched source.

        Args:
            alignment: One of SUPPORTS / CONTRADICTS / PARTIAL / ABSENT.
                Use ABSENT for empty search pages, login walls, or
                content that does not bear on the claim.
            rationale: 1-2 sentences citing the source wording that drove
                your verdict.
        """
        verdict = record_alignment_impl(alignment, rationale)
        return Command(
            update={
                **verdict,
                "messages": [
                    ToolMessage(
                        content=f"Recorded alignment={verdict['alignment']}",
                        tool_call_id=runtime.tool_call_id,
                    )
                ],
            }
        )

    return create_agent(
        model=model,
        tools=[record_alignment],
        system_prompt=_SCORER_SYSTEM_PROMPT,
        state_schema=_ScorerState,
        name=SCORER_NAME,
    )
