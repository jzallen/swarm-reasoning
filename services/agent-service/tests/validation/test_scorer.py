"""Unit tests for the accuracy scorer."""

import pytest

from tests.validation.scorer import (
    ClaimResult,
    VerdictTier,
    compute_alignment_rate,
    compute_category_alignment,
    label_to_tier,
    score_claim,
    within_one_tier,
)


class TestLabelToTier:
    def test_corpus_labels(self) -> None:
        assert label_to_tier("TRUE") == VerdictTier.TRUE
        assert label_to_tier("MOSTLY_TRUE") == VerdictTier.MOSTLY_TRUE
        assert label_to_tier("HALF_TRUE") == VerdictTier.HALF_TRUE
        assert label_to_tier("MOSTLY_FALSE") == VerdictTier.MOSTLY_FALSE
        assert label_to_tier("FALSE") == VerdictTier.FALSE
        assert label_to_tier("PANTS_FIRE") == VerdictTier.PANTS_FIRE

    def test_system_labels(self) -> None:
        assert label_to_tier("true") == VerdictTier.TRUE
        assert label_to_tier("mostly-true") == VerdictTier.MOSTLY_TRUE
        assert label_to_tier("half-true") == VerdictTier.HALF_TRUE
        assert label_to_tier("mostly-false") == VerdictTier.MOSTLY_FALSE
        assert label_to_tier("false") == VerdictTier.FALSE
        assert label_to_tier("pants-on-fire") == VerdictTier.PANTS_FIRE

    def test_unknown_label_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown verdict label"):
            label_to_tier("GARBAGE")


class TestWithinOneTier:
    def test_exact_match(self) -> None:
        assert within_one_tier("true", "TRUE") is True
        assert within_one_tier("false", "FALSE") is True

    def test_one_tier_away(self) -> None:
        assert within_one_tier("true", "MOSTLY_TRUE") is True
        assert within_one_tier("mostly-true", "HALF_TRUE") is True
        assert within_one_tier("false", "MOSTLY_FALSE") is True
        assert within_one_tier("pants-on-fire", "FALSE") is True

    def test_two_tiers_away(self) -> None:
        assert within_one_tier("true", "HALF_TRUE") is False
        assert within_one_tier("pants-on-fire", "MOSTLY_FALSE") is False

    def test_extreme_distance(self) -> None:
        assert within_one_tier("true", "PANTS_FIRE") is False
        assert within_one_tier("pants-on-fire", "TRUE") is False

    def test_cross_format(self) -> None:
        assert within_one_tier("mostly-true", "TRUE") is True
        assert within_one_tier("half-true", "MOSTLY_FALSE") is True


class TestScoreClaim:
    def test_aligned_claim(self) -> None:
        result = score_claim("pf-001", "A claim", "TRUE", "true", 0.9, 15)
        assert result.aligned is True
        assert result.ground_truth_tier == 5
        assert result.system_tier == 5

    def test_misaligned_claim(self) -> None:
        result = score_claim("pf-002", "A claim", "TRUE", "false", 0.3, 10)
        assert result.aligned is False
        assert result.ground_truth_tier == 5
        assert result.system_tier == 1


class TestComputeAlignmentRate:
    def test_all_aligned(self) -> None:
        results = [
            ClaimResult("1", "", "TRUE", "true", 5, 5, True, 0.9, 10),
            ClaimResult("2", "", "FALSE", "false", 1, 1, True, 0.1, 10),
        ]
        assert compute_alignment_rate(results) == 1.0

    def test_none_aligned(self) -> None:
        results = [
            ClaimResult("1", "", "TRUE", "false", 5, 1, False, 0.3, 10),
            ClaimResult("2", "", "FALSE", "true", 1, 5, False, 0.8, 10),
        ]
        assert compute_alignment_rate(results) == 0.0

    def test_partial_alignment(self) -> None:
        results = [
            ClaimResult("1", "", "TRUE", "true", 5, 5, True, 0.9, 10),
            ClaimResult("2", "", "FALSE", "true", 1, 5, False, 0.8, 10),
        ]
        assert compute_alignment_rate(results) == 0.5

    def test_empty_results(self) -> None:
        assert compute_alignment_rate([]) == 0.0


class TestComputeCategoryAlignment:
    def test_filters_by_category(self) -> None:
        results = [
            ClaimResult("1", "", "TRUE", "true", 5, 5, True, 0.9, 10),
            ClaimResult("2", "", "FALSE", "true", 1, 5, False, 0.8, 10),
            ClaimResult("3", "", "TRUE", "true", 5, 5, True, 0.9, 10),
        ]
        rate = compute_category_alignment(results, ["1", "3"])
        assert rate == 1.0

    def test_empty_category(self) -> None:
        results = [
            ClaimResult("1", "", "TRUE", "true", 5, 5, True, 0.9, 10),
        ]
        rate = compute_category_alignment(results, ["99"])
        assert rate == 0.0
