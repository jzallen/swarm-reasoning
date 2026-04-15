"""Unit tests for domain classification utilities."""

from __future__ import annotations

from swarm_reasoning.agents.intake.tools.domain_cls import (
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

    def test_all_codes_in_system_prompt(self):
        from swarm_reasoning.agents.intake.tools.domain_cls import _SYSTEM_PROMPT

        for code in DOMAIN_VOCABULARY:
            assert code in _SYSTEM_PROMPT
