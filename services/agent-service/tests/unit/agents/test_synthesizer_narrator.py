"""Unit tests for synthesizer narrative generation."""

from __future__ import annotations

import pytest

from swarm_reasoning.agents.synthesizer.models import ResolvedObservation, ResolvedObservationSet
from swarm_reasoning.agents.synthesizer.narrator import NarrativeGenerator


def _obs(code: str, value: str, agent: str = "test-agent", seq: int = 1) -> ResolvedObservation:
    return ResolvedObservation(
        agent=agent,
        code=code,
        value=value,
        value_type="CWE",
        seq=seq,
        status="F",
        resolution_method="LATEST_F",
        timestamp="2026-01-01T00:00:00Z",
    )


def _nm_obs(code: str, value: str, agent: str = "test-agent", seq: int = 1) -> ResolvedObservation:
    return ResolvedObservation(
        agent=agent,
        code=code,
        value=value,
        value_type="NM",
        seq=seq,
        status="F",
        resolution_method="LATEST_F",
        timestamp="2026-01-01T00:00:00Z",
    )


def _basic_resolved() -> ResolvedObservationSet:
    return ResolvedObservationSet(
        observations=[
            _obs(
                "DOMAIN_EVIDENCE_ALIGNMENT", "SUPPORTS^Supports^FCK", agent="evidence", seq=1
            ),
            _nm_obs("DOMAIN_CONFIDENCE", "0.9", agent="evidence", seq=2),
            _obs("CLAIMREVIEW_MATCH", "TRUE^Match Found^FCK", agent="evidence", seq=3),
            _obs("CLAIMREVIEW_VERDICT", "TRUE^True^POLITIFACT", agent="evidence", seq=4),
            _obs(
                "CROSS_SPECTRUM_CORROBORATION",
                "TRUE^Corroborated^FCK",
                agent="validation",
                seq=5,
            ),
            _nm_obs("BLINDSPOT_SCORE", "0.0", agent="validation", seq=6),
        ],
        synthesis_signal_count=6,
    )


@pytest.fixture
def narrator():
    return NarrativeGenerator()


class TestFallbackNarrative:
    """Fallback narrative when LLM is unavailable."""

    @pytest.mark.asyncio
    async def test_fallback_length_bounds(self, narrator):
        """Fallback narrative must be 200-1000 characters."""
        resolved = _basic_resolved()
        # Force fallback by not having ANTHROPIC_API_KEY
        narrative = narrator._fallback_narrative(
            resolved,
            "TRUE",
            0.95,
            "",
            [],
            6,
            [],
        )
        assert 200 <= len(narrative) <= 1000

    @pytest.mark.asyncio
    async def test_fallback_mentions_verdict(self, narrator):
        resolved = _basic_resolved()
        narrative = narrator._fallback_narrative(
            resolved,
            "MOSTLY_TRUE",
            0.75,
            "",
            [],
            6,
            [],
        )
        assert "MOSTLY_TRUE" in narrative

    @pytest.mark.asyncio
    async def test_fallback_mentions_signal_count(self, narrator):
        resolved = _basic_resolved()
        narrative = narrator._fallback_narrative(
            resolved,
            "TRUE",
            0.95,
            "",
            [],
            6,
            [],
        )
        assert "6" in narrative

    @pytest.mark.asyncio
    async def test_fallback_with_domain_evidence(self, narrator):
        resolved = _basic_resolved()
        narrative = narrator._fallback_narrative(
            resolved,
            "TRUE",
            0.95,
            "",
            [],
            6,
            [],
        )
        assert "domain evidence" in narrative.lower() or "Domain evidence" in narrative

    @pytest.mark.asyncio
    async def test_fallback_with_claimreview(self, narrator):
        resolved = _basic_resolved()
        narrative = narrator._fallback_narrative(
            resolved,
            "TRUE",
            0.95,
            "",
            [],
            6,
            [],
        )
        assert "external fact-check" in narrative.lower() or "fact-check" in narrative.lower()

    @pytest.mark.asyncio
    async def test_fallback_with_warnings(self, narrator):
        resolved = _basic_resolved()
        narrative = narrator._fallback_narrative(
            resolved,
            "TRUE",
            0.95,
            "",
            ["WARNING: coverage incomplete"],
            6,
            [],
        )
        assert "incomplete" in narrative.lower()

    @pytest.mark.asyncio
    async def test_fallback_with_citations(self, narrator):
        resolved = _basic_resolved()
        citations = [
            {"sourceName": "CDC", "validationStatus": "live", "sourceUrl": "https://cdc.gov"},
            {
                "sourceName": "Reuters",
                "validationStatus": "dead",
                "sourceUrl": "https://reuters.com",
            },
        ]
        narrative = narrator._fallback_narrative(
            resolved,
            "TRUE",
            0.95,
            "",
            [],
            6,
            citations,
        )
        assert "2 citations" in narrative
        assert "1 live" in narrative
        assert "1 dead" in narrative

    @pytest.mark.asyncio
    async def test_fallback_convergence(self, narrator):
        resolved = _basic_resolved()
        resolved.observations.append(
            _nm_obs("SOURCE_CONVERGENCE_SCORE", "0.75", agent="validation", seq=7)
        )
        narrative = narrator._fallback_narrative(
            resolved,
            "TRUE",
            0.95,
            "",
            [],
            7,
            [],
        )
        assert "convergence" in narrative.lower()

    @pytest.mark.asyncio
    async def test_fallback_unverifiable(self, narrator):
        resolved = ResolvedObservationSet(observations=[], synthesis_signal_count=3)
        narrative = narrator._fallback_narrative(
            resolved,
            "UNVERIFIABLE",
            None,
            "",
            [],
            3,
            [],
        )
        assert 200 <= len(narrative) <= 1000
        assert "UNVERIFIABLE" in narrative

    @pytest.mark.asyncio
    async def test_fallback_absent_domain_evidence(self, narrator):
        resolved = ResolvedObservationSet(
            observations=[
                _obs(
                    "CROSS_SPECTRUM_CORROBORATION",
                    "TRUE^Corroborated^FCK",
                    agent="validation",
                    seq=1,
                ),
            ],
            synthesis_signal_count=5,
        )
        narrative = narrator._fallback_narrative(
            resolved,
            "HALF_TRUE",
            0.55,
            "",
            [],
            5,
            [],
        )
        assert "absent" in narrative.lower()


class TestTruncation:
    """Truncation at last sentence before 1000 characters."""

    def test_truncate_at_sentence_boundary(self, narrator):
        text = "First sentence. " * 100  # > 1000 chars
        result = narrator._truncate(text)
        assert len(result) <= 1000
        assert result.endswith(".")

    def test_no_truncation_under_limit(self, narrator):
        text = "Short text."
        result = narrator._truncate(text)
        assert result == text


class TestParseCitationList:
    """CITATION_LIST value parsing."""

    def test_valid_json_array(self):
        from swarm_reasoning.agents.synthesizer.narrator import _parse_citation_list

        result = _parse_citation_list('[{"sourceName": "CDC"}]')
        assert len(result) == 1
        assert result[0]["sourceName"] == "CDC"

    def test_invalid_json(self):
        from swarm_reasoning.agents.synthesizer.narrator import _parse_citation_list

        result = _parse_citation_list("not json")
        assert result == []

    def test_empty_string(self):
        from swarm_reasoning.agents.synthesizer.narrator import _parse_citation_list

        result = _parse_citation_list("")
        assert result == []

    def test_none(self):
        from swarm_reasoning.agents.synthesizer.narrator import _parse_citation_list

        result = _parse_citation_list(None)
        assert result == []
