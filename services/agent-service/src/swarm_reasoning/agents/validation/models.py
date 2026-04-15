"""Typed I/O models for the validation agent.

ValidationInput carries pre-extracted upstream data (URLs and coverage segments).
ValidationOutput carries the full validation result for pipeline state updates.
"""

from __future__ import annotations

from typing import TypedDict


class ValidationInput(TypedDict):
    """Input to the validation agent, translated from PipelineState.

    Fields are pre-extracted by the pipeline node from PipelineState so the
    agent has no coupling to PipelineState directly.
    """

    cross_agent_urls: list[dict]
    """URL entries from upstream agents: each dict has url, agent, code, source_name."""

    coverage_left: list[dict]
    """Left-leaning coverage articles from coverage node."""

    coverage_center: list[dict]
    """Centrist coverage articles from coverage node."""

    coverage_right: list[dict]
    """Right-leaning coverage articles from coverage node."""


class ValidationOutput(TypedDict):
    """Output from the validation agent, translated to PipelineState updates."""

    validated_urls: list[dict]
    """URL validation results with status and associations."""

    convergence_score: float
    """Proportion of URLs cited by 2+ agents (0.0-1.0)."""

    citations: list[dict]
    """Aggregated citation list combining extraction, validation, convergence."""

    blindspot_score: float
    """Coverage gap score: absent_segments / 3 (0.0-1.0)."""

    blindspot_direction: str
    """CWE-coded blindspot direction: NONE, LEFT, CENTER, RIGHT, or MULTIPLE."""
