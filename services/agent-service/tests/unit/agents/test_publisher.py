"""Unit tests for normalize_date utility (ported from entity_extractor/publisher)."""

from __future__ import annotations

from swarm_reasoning.agents._utils import normalize_date


class TestNormalizeDate:
    def test_yyyymmdd_passthrough(self):
        value, note = normalize_date("20210115")
        assert value == "20210115"
        assert note is None

    def test_range_passthrough(self):
        value, note = normalize_date("20210101-20211231")
        assert value == "20210101-20211231"
        assert note is None

    def test_year_only_expands_to_range(self):
        value, note = normalize_date("2021")
        assert value == "20210101-20211231"
        assert note is None

    def test_unparseable_returns_raw_with_note(self):
        value, note = normalize_date("last Tuesday")
        assert value == "last Tuesday"
        assert note == "date-not-normalized"

    def test_strips_whitespace(self):
        value, note = normalize_date("  20210115  ")
        assert value == "20210115"
        assert note is None
