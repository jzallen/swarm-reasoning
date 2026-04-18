"""Fact-checker CLI: drive swarm-reasoning agents from the terminal.

Usage:
    fact-checker agents intake --url https://example.com/article
    fact-checker pipeline run --url https://example.com/article
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


@main.group()
def pipeline() -> None:
    """Run the full claim-verification pipeline."""


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


@pipeline.command("run")
@click.option("--url", required=True, help="Article URL to verify.")
@click.option(
    "--thread-id",
    default=None,
    help="LangGraph thread_id for the checkpointer. Auto-generated if omitted.",
)
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="Bypass the LLM and fetch caches; always hit upstream.",
)
def pipeline_run(url: str, thread_id: str | None, no_cache: bool) -> None:
    """Run the pipeline through intake's human-in-the-loop interrupt.

    Builds the compiled pipeline graph with an in-memory checkpointer,
    drives intake Phase A, prompts for claim selection at the interrupt,
    resumes with ``Command(resume=<index>)``, and prints the final state.
    """
    try:
        asyncio.run(_run_pipeline(url, thread_id=thread_id, no_cache=no_cache))
    except KeyboardInterrupt as exc:
        raise click.Abort() from exc


def _enable_llm_cache() -> None:
    from langchain_community.cache import SQLiteCache
    from langchain_core.globals import set_llm_cache

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    set_llm_cache(SQLiteCache(database_path=str(LLM_CACHE_PATH)))


async def _run_intake(url: str, *, no_cache: bool) -> None:
    if no_cache:
        os.environ["INTAKE_FETCH_CACHE"] = "bypass"
    else:
        _enable_llm_cache()

    # Imported lazily so `fact-checker --help` works without the agent
    # service installed in the current environment, and so the fetch cache
    # bypass env var is set before the tools module reads it.
    from swarm_reasoning.agents.intake.agent import build_intake_agent

    agent = build_intake_agent()
    inputs = {"messages": [("user", f"Process this URL: {url}")]}

    final_state = None
    async for mode, payload in agent.astream(inputs, stream_mode=["custom", "values"]):
        if mode == "custom":
            message = payload.get("message") if isinstance(payload, dict) else None
            if message:
                click.echo(click.style(f"• {message}", fg="cyan"), err=True)
        elif mode == "values":
            final_state = payload

    if not final_state:
        click.echo(click.style("No result returned.", fg="red"), err=True)
        raise click.Abort()

    structured = final_state.get("structured_response")
    if structured is None:
        click.echo(
            click.style("No structured_response in final state.", fg="yellow"),
            err=True,
        )
        click.echo(json.dumps(final_state, indent=2, default=str, ensure_ascii=False))
        return

    output = structured.model_dump() if hasattr(structured, "model_dump") else structured
    click.echo(json.dumps(output, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Pipeline run: interrupt/resume driver
# ---------------------------------------------------------------------------


async def _run_pipeline(url: str, *, thread_id: str | None, no_cache: bool) -> None:
    if no_cache:
        os.environ["INTAKE_FETCH_CACHE"] = "bypass"
    else:
        _enable_llm_cache()

    # Lazy imports: keep `fact-checker --help` fast and let the cache env
    # flag propagate before the intake tools module caches its own config.
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command
    from swarm_reasoning.pipeline.graph import build_pipeline_graph

    thread_id = thread_id or str(uuid.uuid4())
    graph = build_pipeline_graph(checkpointer=InMemorySaver())

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
        _print_final(result)
        return

    payload = _interrupt_payload(interrupts)
    selected_index = _prompt_claim_selection(payload)

    final_state = await graph.ainvoke(Command(resume=selected_index), config=config)
    _print_final(final_state)


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


def _print_final(state: dict[str, Any]) -> None:
    click.echo(json.dumps(state, indent=2, default=str, ensure_ascii=False))


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
