"""Typed I/O models for the coverage agent.

CoverageInput carries the normalized claim pre-extracted from PipelineState.
CoverageOutput carries the per-spectrum coverage result (articles, framing,
sentiment, top source) for pipeline state updates.
"""

from __future__ import annotations

from typing_extensions import TypedDict


class CoverageInput(TypedDict):
    """Input to a coverage agent, translated from PipelineState.

    Fields are pre-extracted by the pipeline node from PipelineState so the
    agent has no coupling to PipelineState directly.  Each coverage agent
    instance (left/center/right) receives the same input.
    """

    normalized_claim: str
    """Normalized claim text to search coverage for."""


class CoverageOutput(TypedDict):
    """Output from a single coverage agent (one spectrum), translated to
    PipelineState updates.

    The pipeline node collects one CoverageOutput per spectrum and merges
    them into the corresponding ``coverage_left``, ``coverage_center``,
    ``coverage_right``, and ``framing_analysis`` state fields.
    """

    articles: list[dict]
    """Coverage articles found, each with title, url, source, and framing keys."""

    framing: str
    """Framing classification code: SUPPORTIVE, CRITICAL, NEUTRAL, or ABSENT."""

    compound_score: float
    """VADER-style compound sentiment score in [-1.0, 1.0]."""

    top_source: dict | None
    """Highest-credibility source dict with name and url keys, or None if no
    articles were found."""
