"""Typed I/O models for the evidence agent.

EvidenceInput is a narrow projection of IntakeOutput carrying only the
fields evidence needs (selected claim text, domain, and entity lists).
EvidenceOutput carries the full evidence result for pipeline state updates.

The agent never touches PipelineState or IntakeOutput directly; the
pipeline node projects state into EvidenceInput before invoking the agent.
``from_intake_output`` is exposed for callers (CLI, tests) that already
hold an ``IntakeOutput``.
"""

from __future__ import annotations

from typing_extensions import TypedDict

from swarm_reasoning.agents.intake.models import IntakeOutput


class EvidenceInputError(ValueError):
    """Raised when an IntakeOutput is missing fields required to build EvidenceInput.

    Indicates intake's Phase B did not complete (no selected_claim, no
    domain, or no entities). The pipeline must not invoke evidence on
    such an output.
    """


class EvidenceInput(TypedDict, total=False):
    """Input to the evidence agent, projected from intake's IntakeOutput.

    Field names mirror the intake output keys so future readers can trace
    the handoff. ``claim_text`` and ``domain`` are required; the entity
    lists default to empty.
    """

    claim_text: str
    """Selected claim text (from IntakeOutput.selected_claim.claim_text)."""

    domain: str
    """Domain classification (HEALTHCARE, ECONOMICS, POLICY, SCIENCE,
    ELECTION, CRIME, OTHER)."""

    persons: list[str]
    """Person entities extracted by intake."""

    organizations: list[str]
    """Organization entities extracted by intake."""

    dates: list[str]
    """Date references extracted by intake."""

    locations: list[str]
    """Location references extracted by intake."""

    statistics: list[str]
    """Numeric statistics extracted by intake."""


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


def from_intake_output(intake_output: IntakeOutput) -> EvidenceInput:
    """Project an IntakeOutput into the narrower EvidenceInput contract.

    Raises:
        EvidenceInputError: If intake's Phase B fields are missing.
    """
    selected = intake_output.get("selected_claim")
    domain = intake_output.get("domain")
    entities = intake_output.get("entities")
    if selected is None or domain is None or entities is None:
        missing = [
            name
            for name, value in (
                ("selected_claim", selected),
                ("domain", domain),
                ("entities", entities),
            )
            if value is None
        ]
        raise EvidenceInputError(
            f"IntakeOutput is missing required fields for evidence: {', '.join(missing)}"
        )

    claim_text = selected.get("claim_text", "")
    return EvidenceInput(
        claim_text=claim_text,
        domain=domain,
        persons=list(entities.get("persons", []) or []),
        organizations=list(entities.get("organizations", []) or []),
        dates=list(entities.get("dates", []) or []),
        locations=list(entities.get("locations", []) or []),
        statistics=list(entities.get("statistics", []) or []),
    )
