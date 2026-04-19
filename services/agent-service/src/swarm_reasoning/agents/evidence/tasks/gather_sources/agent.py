"""Pass-1 source-discovery subagent for the gather_sources task.

A small Anthropic Haiku ``create_agent`` subagent that reads a claim plus
its domain and entities and returns up to 20 authoritative source
domains (bare hostnames) along with an optional recency hint. The
verdict is recorded by the inline ``record_authoritative_domains``
``@tool`` closure, which delegates to the framework-free plain impl in
``tools/record_authoritative_domains.py`` and wraps the result in a
``Command(update=...)`` carrying the matching ``ToolMessage``.

Framework coupling (``@tool``, ``ToolRuntime``, ``Command``,
``ToolMessage``, langchain/langgraph imports) stays at this
registration site; the plain impl module remains framework-free.
"""

from __future__ import annotations

from typing import Any

from langchain.agents import AgentState, create_agent
from langchain.tools import ToolRuntime
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command
from typing_extensions import NotRequired

from swarm_reasoning.agents.evidence.tasks.gather_sources.tools import (
    record_authoritative_domains as record_authoritative_domains_impl,
)

DISCOVERY_NAME = "evidence-source-discovery"
DISCOVERY_MODEL = "claude-haiku-4-5-20251001"
DISCOVERY_TEMPERATURE = 0.0
DISCOVERY_MAX_TOKENS = 256

_DISCOVERY_SYSTEM_PROMPT = """\
Given a claim, its domain classification, and its entities, list up to 20
authoritative source *domains* (bare hostnames, no https://, no paths) that
a fact-checker would consult to verify or refute the claim.

Prefer: .gov, .edu, peer-reviewed journals, primary-source regulators and
registries. Avoid: content aggregators, social media, partisan blogs.

For context, our curated defaults for the claim's domain appear in <seeds>.
Extend and refine them -- do not just echo them back.

Also return a recency hint. Pick whichever fits the claim best:
  - window: one of "hour" / "day" / "week" / "month" / "year" for a rolling window
  - after_date / before_date: ISO8601 YYYY-MM-DD for a hard bound
  - omit all three for "no recency preference"

Call record_authoritative_domains exactly once with your final list, a
1-2 sentence rationale, and the recency hint."""


class _DiscoverState(AgentState):
    """Discovery subagent state: AgentState + the verdict slots tools write."""

    domains: NotRequired[list[str]]
    rationale: NotRequired[str]
    window: NotRequired[str]
    after_date: NotRequired[str]
    before_date: NotRequired[str]


def build_source_discovery_subagent() -> Any:
    """Build the Haiku-backed source-discovery subagent.

    One inline ``@tool`` (``record_authoritative_domains``) writes the
    domain list, rationale, and optional recency hint into the subagent's
    state via ``Command(update=...)``. ``DISCOVERY_TEMPERATURE`` is 0.0:
    the task is enumeration of canonical sources, not creative writing.
    """
    model = ChatAnthropic(
        model=DISCOVERY_MODEL,
        max_tokens=DISCOVERY_MAX_TOKENS,
        temperature=DISCOVERY_TEMPERATURE,
    )

    @tool
    def record_authoritative_domains(
        domains: list[str],
        rationale: str,
        runtime: ToolRuntime,
        window: str | None = None,
        after_date: str | None = None,
        before_date: str | None = None,
    ) -> Command:
        """Record up to 20 authoritative domains and an optional recency hint.

        Args:
            domains: Bare hostnames (no scheme, no path). Capped at 20.
            rationale: 1-2 sentence justification.
            window: Optional rolling-window recency
                (``hour|day|week|month|year``).
            after_date: Optional ISO8601 ``YYYY-MM-DD`` lower bound.
            before_date: Optional ISO8601 ``YYYY-MM-DD`` upper bound.
        """
        update = record_authoritative_domains_impl(
            domains, rationale, window, after_date, before_date
        )
        update["messages"] = [
            ToolMessage(
                content=f"Recorded {len(update['domains'])} domains",
                tool_call_id=runtime.tool_call_id,
            )
        ]
        return Command(update=update)

    return create_agent(
        model=model,
        tools=[record_authoritative_domains],
        system_prompt=_DISCOVERY_SYSTEM_PROMPT,
        state_schema=_DiscoverState,
        name=DISCOVERY_NAME,
    )
