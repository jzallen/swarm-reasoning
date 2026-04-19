"""Unit tests for evidence tasks.format_response."""

from __future__ import annotations

from swarm_reasoning.agents.evidence.tasks.format_response import format_response


def test_format_response_empty_inputs_produces_zero_confidence():
    result = format_response(claimreview_matches=[], scored_sources=[])
    assert result == {
        "claimreview_matches": [],
        "domain_sources": [],
        "best_confidence": 0.0,
    }


def test_format_response_supports_maps_to_confidence_one():
    result = format_response(
        claimreview_matches=[],
        scored_sources=[
            {"name": "BLS", "url": "https://bls.gov/x", "alignment": "SUPPORTS"},
        ],
    )
    assert result["domain_sources"][0]["confidence"] == 1.0
    assert result["best_confidence"] == 1.0


def test_format_response_contradicts_maps_to_confidence_one():
    result = format_response(
        claimreview_matches=[],
        scored_sources=[
            {"name": "X", "url": "https://x", "alignment": "CONTRADICTS"},
        ],
    )
    assert result["domain_sources"][0]["confidence"] == 1.0
    assert result["best_confidence"] == 1.0


def test_format_response_partial_maps_to_confidence_point_six():
    result = format_response(
        claimreview_matches=[],
        scored_sources=[
            {"name": "X", "url": "https://x", "alignment": "PARTIAL"},
        ],
    )
    assert result["domain_sources"][0]["confidence"] == 0.6
    assert result["best_confidence"] == 0.6


def test_format_response_absent_maps_to_confidence_zero():
    """The fabricated-SUPPORTS regression guard: an honest ABSENT from
    the scorer must produce 0.0 confidence, not a keyword-overlap score."""
    result = format_response(
        claimreview_matches=[],
        scored_sources=[
            {
                "name": "FRED",
                "url": "https://fred.stlouisfed.org/searchresults/?st=foo",
                "alignment": "ABSENT",
                "rationale": "empty search page",
            },
        ],
    )
    assert result["domain_sources"][0]["alignment"] == "ABSENT"
    assert result["domain_sources"][0]["confidence"] == 0.0
    assert result["domain_sources"][0]["rationale"] == "empty search page"
    assert result["best_confidence"] == 0.0


def test_format_response_unknown_alignment_defaults_to_zero():
    result = format_response(
        claimreview_matches=[],
        scored_sources=[
            {"name": "X", "url": "https://x", "alignment": "GARBAGE"},
        ],
    )
    assert result["domain_sources"][0]["confidence"] == 0.0
    assert result["best_confidence"] == 0.0


def test_format_response_preserves_claimreview_matches():
    matches = [
        {
            "source": "PolitiFact",
            "rating": "False",
            "url": "https://politifact.com/factchecks/2026/apr/19/x",
            "score": 0.9,
        }
    ]
    result = format_response(claimreview_matches=matches, scored_sources=[])
    assert result["claimreview_matches"] == matches


def test_format_response_best_confidence_picks_max_across_sources():
    result = format_response(
        claimreview_matches=[],
        scored_sources=[
            {"name": "A", "url": "https://a", "alignment": "PARTIAL"},
            {"name": "B", "url": "https://b", "alignment": "SUPPORTS"},
            {"name": "C", "url": "https://c", "alignment": "ABSENT"},
        ],
    )
    assert result["best_confidence"] == 1.0
