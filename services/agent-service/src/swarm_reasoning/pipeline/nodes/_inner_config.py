"""Shared helper: build a per-call config for inner agent invocations.

The outer pipeline graph's checkpointer leaks into inner ``create_agent``
invocations via subgraph inheritance. Reusing the outer thread_id +
checkpoint_ns causes the inner agent to load stale intermediate state
on node re-execution (e.g. after ``Command(resume=)``) and short-circuit
its tool loop. Mint a unique thread_id + fresh checkpoint_ns per inner
call so its namespace is independent and every invocation starts fresh.
``pipeline_context`` and progress-stream hooks are preserved so tools
still see the caller's observation sinks.

Originally introduced for intake's ``interrupt()`` flow (sr-ld49) and
generalized here so other agents inherit the same isolation, even when
they don't use interrupts.
"""

from __future__ import annotations

import uuid

from langgraph.types import RunnableConfig


def inner_agent_config(config: RunnableConfig, *, agent: str) -> RunnableConfig:
    """Return a new RunnableConfig with an isolated checkpoint namespace."""
    configurable = dict(config.get("configurable", {}) or {})
    configurable["thread_id"] = f"{agent}-inner-{uuid.uuid4()}"
    configurable["checkpoint_ns"] = ""
    configurable.pop("checkpoint_id", None)
    return {"configurable": configurable}
