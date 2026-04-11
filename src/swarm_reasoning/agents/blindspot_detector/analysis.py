"""Asymmetry scoring, direction classification, and corroboration logic."""

from __future__ import annotations

from swarm_reasoning.agents.blindspot_detector.models import CoverageSnapshot


def _is_absent(framing: str, article_count: int) -> bool:
    """A segment is absent if framing is ABSENT or article_count is 0."""
    return framing == "ABSENT" or article_count == 0


def compute_blindspot_score(coverage: CoverageSnapshot) -> float:
    """Compute BLINDSPOT_SCORE: absent_count / 3, rounded to 4 decimal places."""
    segments = [coverage.left, coverage.center, coverage.right]
    absent_count = sum(1 for seg in segments if _is_absent(seg.framing, seg.article_count))
    return round(absent_count / 3, 4)


def compute_blindspot_direction(coverage: CoverageSnapshot) -> str:
    """Compute BLINDSPOT_DIRECTION as CWE coded string."""
    named_segments = [
        ("LEFT", coverage.left),
        ("CENTER", coverage.center),
        ("RIGHT", coverage.right),
    ]
    absent_segments = [
        name for name, seg in named_segments if _is_absent(seg.framing, seg.article_count)
    ]

    if not absent_segments:
        return "NONE^No Blindspot^FCK"
    if len(absent_segments) >= 2:
        return "MULTIPLE^Multiple Absent^FCK"
    return f"{absent_segments[0]}^{absent_segments[0].capitalize()} Absent^FCK"


def compute_corroboration(coverage: CoverageSnapshot) -> tuple[str, str | None]:
    """Compute CROSS_SPECTRUM_CORROBORATION.

    Returns (CWE coded string, optional note about convergence strength).
    """
    segments = [coverage.left, coverage.center, coverage.right]
    all_present = all(
        not _is_absent(seg.framing, seg.article_count) for seg in segments
    )
    framings = {seg.framing for seg in segments}
    no_conflict = not ("SUPPORTIVE" in framings and "CRITICAL" in framings)

    if all_present and no_conflict:
        note = None
        if (
            coverage.source_convergence_score is not None
            and coverage.source_convergence_score > 0.5
        ):
            note = f"Strong corroboration: source convergence score {coverage.source_convergence_score:.2f}"
        return "TRUE^Corroborated^FCK", note

    return "FALSE^Not Corroborated^FCK", None
