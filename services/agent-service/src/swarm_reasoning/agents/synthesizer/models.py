"""Data models for synthesizer agent -- typed I/O and observation resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing_extensions import TypedDict

# ---------------------------------------------------------------------------
# Typed I/O for the synthesizer agent graph
# ---------------------------------------------------------------------------


class SynthesizerInput(TypedDict):
    """Input to the synthesizer agent from the pipeline.

    The pipeline node translates PipelineState into this typed contract
    before invoking the synthesizer StateGraph.
    """

    observations: list[dict]
    """Raw upstream observations from all prior pipeline nodes."""


class SynthesizerOutput(TypedDict):
    """Output from the synthesizer agent returned to the pipeline.

    The pipeline node maps these fields back to PipelineState updates.
    """

    verdict: str
    """Verdict code (e.g. TRUE, FALSE, UNVERIFIABLE, NOT_CHECK_WORTHY)."""

    confidence: float | None
    """Calibrated confidence score in [0.0, 1.0], or None if unverifiable."""

    narrative: str
    """Human-readable verdict narrative with OBX citations."""

    verdict_observations: list[dict]
    """Summary of observations produced by the synthesizer."""

    override_reason: str
    """ClaimReview override reason, or empty string if no override."""


# ---------------------------------------------------------------------------
# Observation resolution data models
# ---------------------------------------------------------------------------


@dataclass
class ResolvedObservation:
    """A single canonical observation after epistemic resolution."""

    agent: str
    code: str
    value: str
    value_type: str
    seq: int
    status: str
    resolution_method: str  # "LATEST_C" or "LATEST_F"
    timestamp: str
    method: str | None = None
    note: str | None = None
    units: str | None = None
    reference_range: str | None = None


@dataclass
class ResolvedObservationSet:
    """Complete resolved observation set from all upstream agents."""

    observations: list[ResolvedObservation] = field(default_factory=list)
    synthesis_signal_count: int = 0
    excluded_observations: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def find(self, code: str, agent: str | None = None) -> ResolvedObservation | None:
        """Find a resolved observation by code and optionally agent."""
        for obs in self.observations:
            if obs.code == code and (agent is None or obs.agent == agent):
                return obs
        return None

    def find_all(self, code: str) -> list[ResolvedObservation]:
        """Find all resolved observations matching a code."""
        return [obs for obs in self.observations if obs.code == code]
