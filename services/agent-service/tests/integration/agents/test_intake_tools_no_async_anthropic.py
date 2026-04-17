"""S9/9.13: No tool in ``agents/intake/tools/`` imports or instantiates
``AsyncAnthropic`` directly.

Every LLM sub-call must go through ``ChatAnthropic`` via the closure /
``RunnableConfig`` pattern set up in ``agent.py``. Direct use of the
low-level ``anthropic.AsyncAnthropic`` client inside a tool breaks
LangSmith tracing, callback propagation, and stream-writer routing
across the agent's tool call tree -- the invariant the pipeline relies
on for observability (see design.md §2).

This is a pure source-level grep assertion: each ``.py`` file in the
tools package is scanned for the literal token ``AsyncAnthropic``. Any
occurrence -- import line, type annotation, or instantiation -- fails
the test. No fake LLMs, graphs, or transports are needed; the invariant
is purely about source code content.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import swarm_reasoning.agents.intake.tools as _tools_pkg

TOOLS_DIR = Path(_tools_pkg.__file__).parent

ASYNC_ANTHROPIC_PATTERN = re.compile(r"\bAsyncAnthropic\b")


def _tool_source_files() -> list[Path]:
    """Return every ``.py`` file under the intake tools package, excluding
    ``__pycache__`` and dunder-only directories.
    """
    return sorted(p for p in TOOLS_DIR.rglob("*.py") if "__pycache__" not in p.parts)


class TestNoToolImportsAsyncAnthropic:
    """S9/9.13: source-level grep assertion across ``agents/intake/tools/``."""

    def test_tools_directory_is_discoverable(self):
        """Sanity check: the tools package path resolves and contains files --
        guards against the scan silently skipping everything if the package
        gets relocated and the import in this file goes stale."""
        assert TOOLS_DIR.is_dir(), f"tools package path is not a directory: {TOOLS_DIR}"
        assert _tool_source_files(), f"no .py files found under {TOOLS_DIR}"

    @pytest.mark.parametrize("source_file", _tool_source_files(), ids=lambda p: p.name)
    def test_tool_file_does_not_reference_async_anthropic(self, source_file: Path):
        """Each tool file is free of the literal token ``AsyncAnthropic`` --
        no ``from anthropic import AsyncAnthropic``, no
        ``client: AsyncAnthropic`` annotation, no
        ``AsyncAnthropic(api_key=...)`` construction."""
        text = source_file.read_text(encoding="utf-8")

        matches = ASYNC_ANTHROPIC_PATTERN.findall(text)
        assert not matches, (
            f"{source_file.name} references ``AsyncAnthropic`` "
            f"({len(matches)} occurrence(s)); tools must go through "
            f"ChatAnthropic via RunnableConfig, not the low-level SDK client."
        )

    def test_no_tool_file_references_async_anthropic(self):
        """Aggregate assertion: the entire tools package is AsyncAnthropic-free.
        Complements the parametrized per-file test by surfacing *all* offending
        files together in the failure message rather than only the first."""
        offenders: dict[str, int] = {}
        for source_file in _tool_source_files():
            text = source_file.read_text(encoding="utf-8")
            matches = ASYNC_ANTHROPIC_PATTERN.findall(text)
            if matches:
                offenders[source_file.name] = len(matches)

        assert not offenders, (
            "tool files reference ``AsyncAnthropic`` -- all LLM sub-calls "
            f"must go through ChatAnthropic: {offenders}"
        )
