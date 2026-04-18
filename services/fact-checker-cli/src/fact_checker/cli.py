"""Fact-checker CLI: drive swarm-reasoning agents from the terminal.

Usage:
    fact-checker agents intake --url https://example.com/article
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import Any

import click

CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "fact-checker"
LLM_CACHE_PATH = CACHE_DIR / "llm.db"


@click.group()
def main() -> None:
    """Fact-checker CLI."""


@main.group()
def agents() -> None:
    """Run individual agents."""


@agents.command()
@click.option("--url", required=True, help="Article URL to ingest.")
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="Bypass the LLM and fetch caches; always hit upstream.",
)
def intake(url: str, no_cache: bool) -> None:
    """Run the intake agent on a URL and print the structured output."""
    try:
        asyncio.run(_run_intake(url, no_cache=no_cache))
    except KeyboardInterrupt as exc:
        raise click.Abort() from exc


def _enable_llm_cache() -> None:
    from langchain_community.cache import SQLiteCache
    from langchain_core.globals import set_llm_cache

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    set_llm_cache(SQLiteCache(database_path=str(LLM_CACHE_PATH)))


_INTAKE_OUTPUT_KEYS: tuple[str, ...] = (
    "article_text",
    "article_title",
    "article_author",
    "article_publisher",
    "article_published_at",
    "article_accessed_at",
    "extracted_claims",
    "selected_claim",
    "claim_text",
    "claim_domain",
    "entities",
    "is_check_worthy",
    "errors",
)


async def _run_intake(url: str, *, no_cache: bool) -> None:
    """Run intake in isolation: Phase A → human claim selection → Phase B.

    Builds an intake-scoped StateGraph (just ``intake_node`` + an in-memory
    checkpointer) so the agent's ``interrupt()``-based HITL works without
    pulling in the full pipeline. Evidence / coverage / validation /
    synthesizer are not touched.
    """
    if no_cache:
        os.environ["INTAKE_FETCH_CACHE"] = "bypass"
    else:
        _enable_llm_cache()

    # Lazy imports keep `fact-checker --help` fast and ensure the cache env
    # flag propagates before the intake tools module caches its own config.
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, StateGraph
    from langgraph.types import Command
    from swarm_reasoning.pipeline.nodes.intake import intake_node
    from swarm_reasoning.pipeline.state import PipelineState

    thread_id = str(uuid.uuid4())

    builder = StateGraph(PipelineState)
    builder.add_node("intake", intake_node)
    builder.set_entry_point("intake")
    builder.add_edge("intake", END)
    graph = builder.compile(checkpointer=InMemorySaver())

    ctx = _build_cli_context(run_id=thread_id, session_id=f"cli-{thread_id}")
    config = {
        "configurable": {
            "pipeline_context": ctx,
            "heartbeat_callback": ctx.heartbeat_callback,
            "run_id": thread_id,
            "session_id": ctx.session_id,
            "thread_id": thread_id,
        }
    }

    initial_state: dict[str, Any] = {
        "claim_url": url,
        "claim_text": url,
        "run_id": thread_id,
        "session_id": ctx.session_id,
    }

    result = await graph.ainvoke(initial_state, config=config)

    interrupts = result.get("__interrupt__")
    if not interrupts:
        _print_intake_output(result)
        return

    payload = _interrupt_payload(interrupts)
    selected_index = _prompt_claim_selection(payload)

    final_state = await graph.ainvoke(Command(resume=selected_index), config=config)
    _print_intake_output(final_state)


def _interrupt_payload(interrupts: Any) -> dict[str, Any]:
    """Extract the interrupt payload dict from LangGraph's ``__interrupt__`` value.

    LangGraph surfaces interrupts as a tuple of Interrupt objects; each has
    a ``.value`` attribute carrying the dict passed to ``interrupt(...)``.
    """
    if isinstance(interrupts, (list, tuple)) and interrupts:
        first = interrupts[0]
        value = getattr(first, "value", first)
        if isinstance(value, dict):
            return value
    if isinstance(interrupts, dict):
        return interrupts
    raise click.ClickException(f"Unexpected interrupt shape: {interrupts!r}")


def _prompt_claim_selection(payload: dict[str, Any]) -> int:
    claims = payload.get("claims") or []
    title = payload.get("article_title") or "(no title)"
    author = payload.get("article_author") or "(no author)"
    publisher = payload.get("article_publisher") or "(no publisher)"
    published = payload.get("article_published_at") or "(no date)"

    click.echo(click.style(f"\n{title}", fg="bright_white", bold=True), err=True)
    click.echo(click.style(f"  by {author} · {publisher} · {published}", fg="white"), err=True)
    click.echo(err=True)

    for claim in claims:
        idx = claim.get("index", "?")
        text = claim.get("claim_text", "")
        click.echo(click.style(f"  [{idx}] {text}", fg="cyan"), err=True)
    click.echo(err=True)

    choice = click.prompt(f"Select claim [1-{len(claims)}]", type=click.IntRange(1, len(claims)))
    return int(choice)


def _print_intake_output(state: dict[str, Any]) -> None:
    """Print the intake-relevant slice of pipeline state as JSON.

    Filters out internal fields (run_id, session_id, thread_id, claim_url
    duplicate) so the output matches the pre-HITL ``agents intake`` shape
    plus the new Phase B fields (selected_claim, claim_domain, entities).
    """
    output = {k: state[k] for k in _INTAKE_OUTPUT_KEYS if k in state}
    click.echo(json.dumps(output, indent=2, default=str, ensure_ascii=False))


# ---------------------------------------------------------------------------
# CLI-local PipelineContext stub
# ---------------------------------------------------------------------------


def _build_cli_context(*, run_id: str, session_id: str) -> Any:
    """Build a PipelineContext backed by stderr-printing stubs.

    The CLI has no Temporal activity and no guaranteed Redis; observation
    and progress writes go to stderr so the operator can eyeball the
    idempotency check required by sr-81o0 acceptance (CLAIM_SOURCE_URL
    must print exactly once per run).
    """
    from swarm_reasoning.pipeline.context import PipelineContext

    stream = _CliStream()
    redis_client = _CliRedis()

    def _heartbeat(node_name: str) -> None:
        return None

    return PipelineContext(
        stream=stream,
        redis_client=redis_client,  # type: ignore[arg-type]
        run_id=run_id,
        session_id=session_id,
        heartbeat_callback=_heartbeat,
    )


class _CliStream:
    """ReasoningStream-compatible stub that echoes observations to stderr."""

    async def publish(self, stream_key: str, message: Any) -> str:
        obs = getattr(message, "observation", None)
        if obs is not None:
            code = getattr(obs, "code", "?")
            value = getattr(obs, "value", "")
            code_name = getattr(code, "name", code)
            click.echo(
                click.style(f"OBS {code_name}: {value}", fg="green"),
                err=True,
            )
        return "0-0"

    async def read(self, stream_key: str, last_id: str = "0") -> list[Any]:
        return []

    async def read_range(self, stream_key: str, start: str = "-", end: str = "+") -> list[Any]:
        return []

    async def read_latest(self, stream_key: str) -> Any | None:
        return None

    async def list_streams(self, run_id: str) -> list[str]:
        return []

    async def health(self) -> bool:
        return True


class _CliRedis:
    """Minimal async-redis stub: ``xadd`` prints progress messages to stderr."""

    async def xadd(self, stream_key: str, fields: dict[str, Any]) -> str:
        message = fields.get("message")
        agent = fields.get("agent")
        if message:
            prefix = f"[{agent}] " if agent else ""
            click.echo(click.style(f"• {prefix}{message}", fg="cyan"), err=True)
        return "0-0"


if __name__ == "__main__":
    main()
