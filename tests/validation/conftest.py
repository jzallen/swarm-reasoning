"""Pytest fixtures for the validation harness."""

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


@pytest.fixture(scope="session")
def corpus() -> dict:
    """Load and validate the corpus fixture."""
    corpus_data = json.loads(CORPUS_PATH.read_text())

    if SCHEMA_PATH.exists():
        schema = json.loads(SCHEMA_PATH.read_text())
        jsonschema.validate(instance=corpus_data, schema=schema)

    return corpus_data


@pytest.fixture(scope="session")
def corpus_claims(corpus: dict) -> list[dict]:
    """All 50 claims from the corpus."""
    return corpus["claims"]


@pytest.fixture(scope="session")
def category_map(corpus_claims: list[dict]) -> dict[str, list[str]]:
    """Map of category name to list of claim IDs in that category."""
    result: dict[str, list[str]] = {cat: [] for cat in CATEGORIES}
    for claim in corpus_claims:
        for cat in claim["categories"]:
            if cat in result:
                result[cat].append(claim["id"])
    return result


@pytest.fixture(scope="session")
def corpus_version(corpus: dict) -> str:
    """Corpus version string."""
    return corpus["version"]
