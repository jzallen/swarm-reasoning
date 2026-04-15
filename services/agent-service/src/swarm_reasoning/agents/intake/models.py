"""Typed I/O models for the intake agent.

IntakeInput carries the raw claim submission data pre-extracted from PipelineState.
IntakeOutput carries the full intake result (validation, domain classification,
normalization, check-worthiness scoring, entity extraction) for pipeline state updates.
"""

from __future__ import annotations

from typing import TypedDict


class IntakeInput(TypedDict):
    """Input to the intake agent, translated from PipelineState.

    Fields are pre-extracted by the pipeline node from PipelineState so the
    agent has no coupling to PipelineState directly.
    """

    claim_text: str
    """Raw claim text submitted by the user."""

    claim_url: str | None
    """Optional source URL for the claim."""

    submission_date: str | None
    """Optional submission date (ISO 8601 or free-form, normalized by the agent)."""


class IntakeOutput(TypedDict):
    """Output from the intake agent, translated to PipelineState updates.

    All fields are always present. Fields that were not reached due to early
    rejection use None or empty defaults.
    """

    is_check_worthy: bool
    """Whether the claim passed the check-worthiness gate."""

    normalized_claim: str | None
    """Normalized claim text, or None if rejected before normalization."""

    claim_domain: str | None
    """Domain classification (e.g. HEALTHCARE, ECONOMICS), or None if rejected."""

    check_worthy_score: float | None
    """Check-worthiness score in [0.0, 1.0], or None if rejected before scoring."""

    entities: dict[str, list[str]]
    """Extracted entities keyed by type (persons, organizations, dates, locations,
    statistics). Empty dict if not check-worthy or rejected."""

    errors: list[str]
    """Rejection or validation errors. Empty list on success."""
