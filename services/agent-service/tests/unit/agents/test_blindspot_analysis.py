"""Unit tests for blindspot-detector analysis: score, direction, corroboration."""

from __future__ import annotations

from swarm_reasoning.agents.blindspot_detector.analysis import (
    compute_blindspot_direction,
    compute_blindspot_score,
    compute_corroboration,
)
from swarm_reasoning.agents.blindspot_detector.models import (
    CoverageSnapshot,
    SegmentCoverage,
)


def _snap(
    left: tuple[int, str] = (5, "SUPPORTIVE"),
    center: tuple[int, str] = (5, "NEUTRAL"),
    right: tuple[int, str] = (5, "CRITICAL"),
    convergence: float | None = None,
) -> CoverageSnapshot:
    """Helper to build CoverageSnapshot from (article_count, framing) tuples."""
    return CoverageSnapshot(
        left=SegmentCoverage(*left),
        center=SegmentCoverage(*center),
        right=SegmentCoverage(*right),
        source_convergence_score=convergence,
    )


# --- BLINDSPOT_SCORE ---


class TestComputeBlindspotScore:
    def test_zero_absent(self):
        snap = _snap(left=(5, "SUPPORTIVE"), center=(3, "NEUTRAL"), right=(7, "CRITICAL"))
        assert compute_blindspot_score(snap) == 0.0

    def test_one_absent_framing(self):
        snap = _snap(left=(5, "SUPPORTIVE"), center=(3, "NEUTRAL"), right=(0, "ABSENT"))
        assert compute_blindspot_score(snap) == round(1 / 3, 4)

    def test_two_absent(self):
        snap = _snap(left=(0, "ABSENT"), center=(3, "NEUTRAL"), right=(0, "ABSENT"))
        assert compute_blindspot_score(snap) == round(2 / 3, 4)

    def test_three_absent(self):
        snap = _snap(left=(0, "ABSENT"), center=(0, "ABSENT"), right=(0, "ABSENT"))
        assert compute_blindspot_score(snap) == 1.0

    def test_article_count_zero_treated_as_absent(self):
        """article_count=0 even with non-ABSENT framing counts as absent."""
        snap = _snap(left=(0, "SUPPORTIVE"), center=(5, "NEUTRAL"), right=(5, "CRITICAL"))
        assert compute_blindspot_score(snap) == round(1 / 3, 4)

    def test_framing_absent_with_nonzero_count(self):
        """framing=ABSENT even with article_count > 0 counts as absent."""
        snap = _snap(left=(5, "ABSENT"), center=(5, "NEUTRAL"), right=(5, "CRITICAL"))
        assert compute_blindspot_score(snap) == round(1 / 3, 4)


# --- BLINDSPOT_DIRECTION ---


class TestComputeBlindspotDirection:
    def test_no_absent_returns_none(self):
        snap = _snap(left=(5, "SUPPORTIVE"), center=(3, "NEUTRAL"), right=(7, "CRITICAL"))
        assert compute_blindspot_direction(snap) == "NONE^No Blindspot^FCK"

    def test_left_absent(self):
        snap = _snap(left=(0, "ABSENT"), center=(3, "NEUTRAL"), right=(7, "CRITICAL"))
        assert compute_blindspot_direction(snap) == "LEFT^Left Absent^FCK"

    def test_right_absent(self):
        snap = _snap(left=(5, "SUPPORTIVE"), center=(3, "NEUTRAL"), right=(0, "ABSENT"))
        assert compute_blindspot_direction(snap) == "RIGHT^Right Absent^FCK"

    def test_center_absent(self):
        snap = _snap(left=(5, "SUPPORTIVE"), center=(0, "ABSENT"), right=(7, "CRITICAL"))
        assert compute_blindspot_direction(snap) == "CENTER^Center Absent^FCK"

    def test_two_absent_returns_multiple(self):
        snap = _snap(left=(0, "ABSENT"), center=(3, "NEUTRAL"), right=(0, "ABSENT"))
        assert compute_blindspot_direction(snap) == "MULTIPLE^Multiple Absent^FCK"

    def test_three_absent_returns_multiple(self):
        snap = _snap(left=(0, "ABSENT"), center=(0, "ABSENT"), right=(0, "ABSENT"))
        assert compute_blindspot_direction(snap) == "MULTIPLE^Multiple Absent^FCK"

    def test_article_count_zero_counts_as_absent_for_direction(self):
        snap = _snap(left=(0, "SUPPORTIVE"), center=(5, "NEUTRAL"), right=(5, "CRITICAL"))
        assert compute_blindspot_direction(snap) == "LEFT^Left Absent^FCK"


# --- CROSS_SPECTRUM_CORROBORATION ---


class TestComputeCorroboration:
    def test_all_present_no_conflict_returns_true(self):
        snap = _snap(left=(5, "NEUTRAL"), center=(3, "NEUTRAL"), right=(7, "NEUTRAL"))
        value, note = compute_corroboration(snap)
        assert value == "TRUE^Corroborated^FCK"
        assert note is None

    def test_all_supportive_returns_true(self):
        snap = _snap(left=(5, "SUPPORTIVE"), center=(3, "SUPPORTIVE"), right=(7, "SUPPORTIVE"))
        value, note = compute_corroboration(snap)
        assert value == "TRUE^Corroborated^FCK"

    def test_one_absent_returns_false(self):
        snap = _snap(left=(5, "SUPPORTIVE"), center=(3, "NEUTRAL"), right=(0, "ABSENT"))
        value, note = compute_corroboration(snap)
        assert value == "FALSE^Not Corroborated^FCK"
        assert note is None

    def test_supportive_critical_conflict_returns_false(self):
        snap = _snap(left=(5, "SUPPORTIVE"), center=(3, "NEUTRAL"), right=(7, "CRITICAL"))
        value, note = compute_corroboration(snap)
        assert value == "FALSE^Not Corroborated^FCK"
        assert note is None

    def test_high_convergence_adds_note(self):
        snap = _snap(
            left=(5, "SUPPORTIVE"),
            center=(3, "SUPPORTIVE"),
            right=(7, "NEUTRAL"),
            convergence=0.8,
        )
        value, note = compute_corroboration(snap)
        assert value == "TRUE^Corroborated^FCK"
        assert note == "Strong corroboration: source convergence score 0.80"

    def test_absent_convergence_no_note(self):
        snap = _snap(
            left=(5, "SUPPORTIVE"),
            center=(3, "SUPPORTIVE"),
            right=(7, "NEUTRAL"),
            convergence=None,
        )
        value, note = compute_corroboration(snap)
        assert value == "TRUE^Corroborated^FCK"
        assert note is None

    def test_low_convergence_no_note(self):
        snap = _snap(
            left=(5, "SUPPORTIVE"),
            center=(3, "SUPPORTIVE"),
            right=(7, "NEUTRAL"),
            convergence=0.3,
        )
        value, note = compute_corroboration(snap)
        assert value == "TRUE^Corroborated^FCK"
        assert note is None

    def test_convergence_exactly_0_5_no_note(self):
        """Convergence must be > 0.5, not >=."""
        snap = _snap(
            left=(5, "SUPPORTIVE"),
            center=(3, "SUPPORTIVE"),
            right=(7, "NEUTRAL"),
            convergence=0.5,
        )
        value, note = compute_corroboration(snap)
        assert value == "TRUE^Corroborated^FCK"
        assert note is None

    def test_article_count_zero_means_not_corroborated(self):
        snap = _snap(left=(0, "NEUTRAL"), center=(5, "NEUTRAL"), right=(5, "NEUTRAL"))
        value, note = compute_corroboration(snap)
        assert value == "FALSE^Not Corroborated^FCK"


# --- CoverageSnapshot.from_activity_input ---


class TestCoverageSnapshotFromActivityInput:
    def test_full_data(self):
        data = {
            "coverage": {
                "left": {"article_count": 12, "framing": "SUPPORTIVE"},
                "center": {"article_count": 7, "framing": "NEUTRAL"},
                "right": {"article_count": 0, "framing": "ABSENT"},
            },
            "source_convergence_score": 0.35,
        }
        snap = CoverageSnapshot.from_activity_input(data)
        assert snap.left.article_count == 12
        assert snap.left.framing == "SUPPORTIVE"
        assert snap.center.article_count == 7
        assert snap.center.framing == "NEUTRAL"
        assert snap.right.article_count == 0
        assert snap.right.framing == "ABSENT"
        assert snap.source_convergence_score == 0.35

    def test_missing_segment_defaults_absent(self):
        data = {
            "coverage": {
                "left": {"article_count": 5, "framing": "SUPPORTIVE"},
                # center and right missing
            }
        }
        snap = CoverageSnapshot.from_activity_input(data)
        assert snap.left.article_count == 5
        assert snap.center.article_count == 0
        assert snap.center.framing == "ABSENT"
        assert snap.right.article_count == 0
        assert snap.right.framing == "ABSENT"

    def test_empty_dict(self):
        snap = CoverageSnapshot.from_activity_input({})
        assert snap.left.article_count == 0
        assert snap.left.framing == "ABSENT"
        assert snap.center.article_count == 0
        assert snap.right.article_count == 0
        assert snap.source_convergence_score is None

    def test_with_convergence_score(self):
        data = {
            "coverage": {
                "left": {"article_count": 1, "framing": "NEUTRAL"},
                "center": {"article_count": 1, "framing": "NEUTRAL"},
                "right": {"article_count": 1, "framing": "NEUTRAL"},
            },
            "source_convergence_score": 0.75,
        }
        snap = CoverageSnapshot.from_activity_input(data)
        assert snap.source_convergence_score == 0.75

    def test_without_convergence_score(self):
        data = {
            "coverage": {
                "left": {"article_count": 1, "framing": "NEUTRAL"},
                "center": {"article_count": 1, "framing": "NEUTRAL"},
                "right": {"article_count": 1, "framing": "NEUTRAL"},
            },
        }
        snap = CoverageSnapshot.from_activity_input(data)
        assert snap.source_convergence_score is None
