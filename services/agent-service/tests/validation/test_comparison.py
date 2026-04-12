"""Unit tests for the comparison module."""

from tests.validation.comparison import (
    assess_nfrs,
    check_corpus_drift,
    compute_gap,
)
from tests.validation.scorer import ClaimResult


def _make_result(claim_id: str, aligned: bool) -> ClaimResult:
    return ClaimResult(
        claim_id=claim_id,
        claim_text="",
        ground_truth="TRUE",
        system_verdict="true",
        ground_truth_tier=5,
        system_tier=5 if aligned else 1,
        aligned=aligned,
        confidence_score=0.9 if aligned else 0.3,
        signal_count=10,
    )


class TestComputeGap:
    def test_swarm_outperforms_baseline(self) -> None:
        swarm = [_make_result(f"c{i}", True) for i in range(8)]
        swarm += [_make_result(f"c{i}", False) for i in range(8, 10)]

        baseline = [_make_result(f"c{i}", True) for i in range(4)]
        baseline += [_make_result(f"c{i}", False) for i in range(4, 10)]

        result = compute_gap(swarm, baseline)
        assert result.swarm_alignment_rate == 0.8
        assert result.baseline_alignment_rate == 0.4
        assert result.gap_pp == 40.0
        assert result.nfr_020_must is True
        assert result.nfr_020_plan is True
        assert result.nfr_020_wish is True

    def test_marginal_gap(self) -> None:
        swarm = [_make_result(f"c{i}", True) for i in range(7)]
        swarm += [_make_result(f"c{i}", False) for i in range(7, 10)]

        baseline = [_make_result(f"c{i}", True) for i in range(5)]
        baseline += [_make_result(f"c{i}", False) for i in range(5, 10)]

        result = compute_gap(swarm, baseline)
        assert result.gap_pp == 20.0
        assert result.nfr_020_must is True
        assert result.nfr_020_plan is False

    def test_no_gap(self) -> None:
        swarm = [_make_result(f"c{i}", True) for i in range(5)]
        swarm += [_make_result(f"c{i}", False) for i in range(5, 10)]

        baseline = [_make_result(f"c{i}", True) for i in range(5)]
        baseline += [_make_result(f"c{i}", False) for i in range(5, 10)]

        result = compute_gap(swarm, baseline)
        assert result.gap_pp == 0.0
        assert result.nfr_020_must is False


class TestAssessNfrs:
    def test_all_pass(self) -> None:
        overall = [_make_result(f"c{i}", True) for i in range(50)]
        swarm_ni = [_make_result(f"c{i}", True) for i in range(10)]
        baseline_ni = [_make_result(f"c{i}", False) for i in range(10)]

        nfr = assess_nfrs(overall, swarm_ni, baseline_ni)
        assert nfr.nfr_019_rate == 1.0
        assert nfr.nfr_019_must is True
        assert nfr.nfr_019_plan is True
        assert nfr.nfr_019_wish is True
        assert nfr.nfr_020_must is True

    def test_borderline_019(self) -> None:
        overall = [_make_result(f"c{i}", True) for i in range(35)]
        overall += [_make_result(f"c{i}", False) for i in range(35, 50)]

        nfr = assess_nfrs(overall, [], [])
        assert nfr.nfr_019_rate == 0.7
        assert nfr.nfr_019_must is True
        assert nfr.nfr_019_plan is False


class TestCheckCorpusDrift:
    def test_no_drift(self) -> None:
        corpus = [
            {"id": "c1", "categories": ["NOT_CLAIMREVIEW_INDEXED"]},
            {"id": "c2", "categories": ["CLAIMREVIEW_INDEXED"]},
        ]
        results = [
            {
                "claim_id": "c1",
                "observations": [
                    {"code": "CLAIMREVIEW_MATCH", "value": "FALSE^No Match^FCK"}
                ],
            },
        ]
        assert check_corpus_drift(corpus, results) == []

    def test_drift_detected(self) -> None:
        corpus = [
            {"id": "c1", "categories": ["NOT_CLAIMREVIEW_INDEXED"]},
        ]
        results = [
            {
                "claim_id": "c1",
                "observations": [
                    {"code": "CLAIMREVIEW_MATCH", "value": "TRUE^Match^FCK"}
                ],
            },
        ]
        assert check_corpus_drift(corpus, results) == ["c1"]

    def test_indexed_claims_not_flagged(self) -> None:
        corpus = [
            {"id": "c1", "categories": ["CLAIMREVIEW_INDEXED"]},
        ]
        results = [
            {
                "claim_id": "c1",
                "observations": [
                    {"code": "CLAIMREVIEW_MATCH", "value": "TRUE^Match^FCK"}
                ],
            },
        ]
        assert check_corpus_drift(corpus, results) == []
