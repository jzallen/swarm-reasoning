"""Typed I/O models for the evidence agent.

EvidenceInput carries pre-extracted claim context from PipelineState.
EvidenceOutput carries the full evidence result (ClaimReview matches,
domain source lookups, alignment scoring, confidence) for pipeline state updates.
"""

from __future__ import annotations

from typing_extensions import TypedDict


class EvidenceInput(TypedDict):
    """Input to the evidence agent, translated from PipelineState.

    Fields are pre-extracted by the pipeline node from PipelineState so the
    agent has no coupling to PipelineState directly.
    """

    normalized_claim: str
    """Normalized claim text (falls back to raw claim_text if unavailable)."""

    claim_domain: str
    """Domain classification (e.g. HEALTHCARE, ECONOMICS, OTHER)."""

    persons: list[str]
    """Person entities extracted by the intake agent."""

    organizations: list[str]
    """Organization entities extracted by the intake agent."""


class EvidenceOutput(TypedDict):
    """Output from the evidence agent, translated to PipelineState updates.

    All fields are always present. Fields that yielded no results use
    empty defaults.
    """

    claimreview_matches: list[dict]
    """ClaimReview API matches. Each dict has keys: source, rating, url, score.
    Empty list when no matches found or API unavailable."""

    domain_sources: list[dict]
    """Domain-authoritative source results. Each dict has keys: name, url,
    alignment, confidence. Empty list when no sources found."""

    evidence_confidence: float
    """Overall evidence confidence score in [0.0, 1.0].
    0.0 when no evidence found."""
