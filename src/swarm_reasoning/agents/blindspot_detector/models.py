"""Data models for the blindspot-detector agent."""

from __future__ import annotations

from dataclasses import dataclass

# Valid framing values from coverage agents
VALID_FRAMINGS = {"SUPPORTIVE", "CRITICAL", "NEUTRAL", "ABSENT"}


@dataclass
class SegmentCoverage:
    """Coverage data for a single spectrum segment (left, center, or right)."""

    article_count: int
    framing: str


@dataclass
class CoverageSnapshot:
    """Cross-agent coverage data from all three spectrum segments."""

    left: SegmentCoverage
    center: SegmentCoverage
    right: SegmentCoverage
    source_convergence_score: float | None

    @classmethod
    def from_activity_input(cls, data: dict) -> CoverageSnapshot:
        """Parse cross_agent_data dict from Temporal activity input.

        Missing segments default to article_count=0, framing="ABSENT".
        Missing source_convergence_score defaults to None.
        """
        coverage = data.get("coverage", {})
        absent = SegmentCoverage(article_count=0, framing="ABSENT")

        def _parse_segment(name: str) -> SegmentCoverage:
            seg = coverage.get(name)
            if seg is None:
                return SegmentCoverage(article_count=0, framing="ABSENT")
            return SegmentCoverage(
                article_count=seg.get("article_count", 0),
                framing=seg.get("framing", "ABSENT"),
            )

        return cls(
            left=_parse_segment("left"),
            center=_parse_segment("center"),
            right=_parse_segment("right"),
            source_convergence_score=data.get("source_convergence_score"),
        )
