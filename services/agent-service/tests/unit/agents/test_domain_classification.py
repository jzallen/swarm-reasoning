"""Unit tests for domain classification utilities."""

from __future__ import annotations

from swarm_reasoning.agents.intake.tools.domain_classification import (
    DOMAIN_VOCABULARY,
    build_prompt,
)

# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_first_attempt(self):
        msgs = build_prompt("GDP grew 3%")
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert "GDP grew 3%" in msgs[0]["content"]
        assert "previous response" not in msgs[0]["content"]

    def test_retry_has_suffix(self):
        msgs = build_prompt("GDP grew 3%", retry=True)
        assert "previous response was not recognized" in msgs[0]["content"]


# ---------------------------------------------------------------------------
# DOMAIN_VOCABULARY
# ---------------------------------------------------------------------------


class TestDomainVocabulary:
    def test_expected_codes(self):
        expected = {"HEALTHCARE", "ECONOMICS", "POLICY", "SCIENCE", "ELECTION", "CRIME", "OTHER"}
        assert DOMAIN_VOCABULARY == expected

    def test_is_frozenset(self):
        assert isinstance(DOMAIN_VOCABULARY, frozenset)
