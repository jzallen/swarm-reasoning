"""Unit tests for corpus fixture integrity and schema validation."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

CORPUS_PATH = Path(__file__).parent.parent.parent / "docs" / "validation" / "corpus.json"
SCHEMA_PATH = Path(__file__).parent.parent.parent / "docs" / "validation" / "corpus-schema.json"

CATEGORIES = [
    "TRUE_MOSTLY_TRUE",
    "FALSE_PANTS_FIRE",
    "HALF_TRUE",
    "CLAIMREVIEW_INDEXED",
    "NOT_CLAIMREVIEW_INDEXED",
]


@pytest.fixture(scope="module")
def corpus() -> dict:
    return json.loads(CORPUS_PATH.read_text())


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


class TestCorpusSchema:
    def test_corpus_validates_against_schema(
        self, corpus: dict, schema: dict
    ) -> None:
        jsonschema.validate(instance=corpus, schema=schema)

    def test_exactly_50_claims(self, corpus: dict) -> None:
        assert len(corpus["claims"]) == 50

    def test_version_present(self, corpus: dict) -> None:
        assert "version" in corpus
        assert corpus["version"] == "1.0"


class TestCorpusCategoryDistribution:
    def test_10_claims_per_category(self, corpus: dict) -> None:
        counts: dict[str, int] = {cat: 0 for cat in CATEGORIES}
        for claim in corpus["claims"]:
            for cat in claim["categories"]:
                if cat in counts:
                    counts[cat] += 1

        for cat, count in counts.items():
            assert count == 10, (
                f"Category {cat} has {count} claims, expected 10"
            )

    def test_claimreview_categories_mutually_exclusive(self, corpus: dict) -> None:
        for claim in corpus["claims"]:
            cats = set(claim["categories"])
            indexed = "CLAIMREVIEW_INDEXED" in cats
            not_indexed = "NOT_CLAIMREVIEW_INDEXED" in cats
            assert not (indexed and not_indexed), (
                f"Claim {claim['id']} is in both CLAIMREVIEW_INDEXED "
                f"and NOT_CLAIMREVIEW_INDEXED"
            )


class TestCorpusClaimFields:
    def test_unique_ids(self, corpus: dict) -> None:
        ids = [c["id"] for c in corpus["claims"]]
        assert len(ids) == len(set(ids)), "Duplicate claim IDs found"

    def test_id_format(self, corpus: dict) -> None:
        import re

        pattern = re.compile(r"^pf-\d{4}-\d{3}$")
        for claim in corpus["claims"]:
            assert pattern.match(claim["id"]), (
                f"Claim ID {claim['id']} does not match pf-YYYY-NNN format"
            )

    def test_ground_truth_values(self, corpus: dict) -> None:
        valid = {"TRUE", "MOSTLY_TRUE", "HALF_TRUE", "MOSTLY_FALSE", "FALSE", "PANTS_FIRE"}
        for claim in corpus["claims"]:
            assert claim["ground_truth"] in valid, (
                f"Claim {claim['id']} has invalid ground_truth: {claim['ground_truth']}"
            )

    def test_claim_text_nonempty(self, corpus: dict) -> None:
        for claim in corpus["claims"]:
            assert len(claim["claim_text"]) >= 10, (
                f"Claim {claim['id']} has claim_text shorter than 10 chars"
            )

    def test_politifact_url_format(self, corpus: dict) -> None:
        for claim in corpus["claims"]:
            assert claim["politifact_url"].startswith("https://www.politifact.com/"), (
                f"Claim {claim['id']} has invalid politifact_url"
            )

    def test_captured_date_format(self, corpus: dict) -> None:
        import re

        pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        for claim in corpus["claims"]:
            assert pattern.match(claim["captured_date"]), (
                f"Claim {claim['id']} has invalid captured_date: {claim['captured_date']}"
            )
