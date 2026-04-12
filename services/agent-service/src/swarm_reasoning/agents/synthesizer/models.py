"""Data models for synthesizer observation resolution."""

from __future__ import annotations

from dataclasses import dataclass, field


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
