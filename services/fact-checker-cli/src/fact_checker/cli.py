"""Fact-checker CLI: drive swarm-reasoning agents from the terminal.

Usage:
    fact-checker agents intake --url https://example.com/article
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

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


if __name__ == "__main__":
    main()
