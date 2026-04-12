"""Unit tests for domain-evidence agent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.domain_evidence.handler import (
    DomainEvidenceHandler,
    derive_query,
    score_alignment,
    score_confidence,
)
from swarm_reasoning.agents.fanout_base import ClaimContext
from swarm_reasoning.models.observation import ObservationCode
from swarm_reasoning.models.stream import ObsMessage

# ---- Query derivation tests ----


class TestDeriveQuery:
    def test_includes_entities(self):
        ctx = ClaimContext(
            normalized_claim="fda approved pfizer vaccine for children under 5",
            organizations=["FDA", "Pfizer"],
        )
        query = derive_query(ctx)
        assert "FDA" in query
        assert "Pfizer" in query

    def test_truncates_to_80_chars(self):
        ctx = ClaimContext(normalized_claim="word " * 100)
        query = derive_query(ctx)
        assert len(query) <= 80

    def test_includes_statistics(self):
        ctx = ClaimContext(
            normalized_claim="unemployment rate fell",
            statistics=["3.4%"],
        )
        query = derive_query(ctx)
        assert "3.4%" in query


# ---- Alignment scoring tests ----


class TestAlignmentScoring:
    def test_high_overlap_no_negation_supports(self):
        ctx = ClaimContext(
            normalized_claim="vaccines reduced hospitalizations by 90 percent"
        )
        content = "vaccines reduced hospitalizations by 90 percent according to latest data"
        result = score_alignment(content, ctx)
        assert "SUPPORTS" in result

    def test_high_overlap_with_negation_contradicts(self):
        ctx = ClaimContext(
            normalized_claim="vaccines reduced hospitalizations by 90 percent"
        )
        content = "no evidence that vaccines reduced hospitalizations by 90 percent"
        result = score_alignment(content, ctx)
        assert "CONTRADICTS" in result

    def test_low_overlap_absent(self):
        ctx = ClaimContext(
            normalized_claim="unemployment rate fell dramatically last quarter"
        )
        content = "weather forecast for this weekend shows sunny skies"
        result = score_alignment(content, ctx)
        assert "ABSENT" in result

    def test_moderate_overlap_partial(self):
        ctx = ClaimContext(
            normalized_claim="unemployment rate fell to 3.4 percent in january 2023"
        )
        # Contains some keywords but not enough for full overlap
        content = "unemployment rate was discussed in recent economic reports"
        result = score_alignment(content, ctx)
        # Should be PARTIAL or ABSENT depending on ratio
        assert "PARTIAL" in result or "ABSENT" in result

    def test_empty_content_absent(self):
        ctx = ClaimContext(normalized_claim="test claim")
        result = score_alignment("", ctx)
        assert "ABSENT" in result


# ---- Confidence scoring tests ----


class TestConfidenceScoring:
    def test_primary_source_high_confidence(self):
        confidence = score_confidence("SUPPORTS^Supports Claim^FCK")
        assert confidence == 1.0

    def test_fallback_penalty(self):
        confidence = score_confidence(
            "SUPPORTS^Supports Claim^FCK", fallback_depth=2
        )
        assert confidence == pytest.approx(0.80)

    def test_old_source_penalty(self):
        confidence = score_confidence(
            "SUPPORTS^Supports Claim^FCK", source_is_old=True
        )
        assert confidence == pytest.approx(0.85)

    def test_indirect_source_penalty(self):
        confidence = score_confidence(
            "SUPPORTS^Supports Claim^FCK", is_indirect=True
        )
        assert confidence == pytest.approx(0.80)

    def test_partial_alignment_penalty(self):
        confidence = score_confidence("PARTIAL^Partially Supports^FCK")
        assert confidence == pytest.approx(0.90)

    def test_absent_always_zero(self):
        confidence = score_confidence("ABSENT^No Evidence Found^FCK")
        assert confidence == 0.0

    def test_combined_penalties(self):
        # fallback=2 (-0.20) + partial (-0.10) = 0.70
        confidence = score_confidence(
            "PARTIAL^Partially Supports^FCK", fallback_depth=2
        )
        assert confidence == pytest.approx(0.70)

    def test_floor_at_0_10(self):
        # Many penalties but not absent
        confidence = score_confidence(
            "PARTIAL^Partially Supports^FCK",
            fallback_depth=5,
            source_is_old=True,
            is_indirect=True,
        )
        assert confidence == 0.10


# ---- Handler tests ----


def _mock_upstream_streams() -> dict[str, list]:
    from tests.unit.agents.test_fanout_base import _mock_upstream_streams
    return _mock_upstream_streams(
        normalized_claim="covid vaccines reduced hospitalizations by 90%",
        domain="HEALTHCARE",
        persons=[],
        orgs=["CDC"],
    )


def _make_stream_mock(streams: dict[str, list]) -> AsyncMock:
    stream_mock = AsyncMock()

    async def read_range(key, **kwargs):
        return streams.get(key, [])

    stream_mock.read_range = AsyncMock(side_effect=read_range)
    stream_mock.publish = AsyncMock()
    stream_mock.close = AsyncMock()
    return stream_mock


def _make_input() -> MagicMock:
    inp = MagicMock()
    inp.run_id = "run-001"
    inp.agent_name = "domain-evidence"
    inp.claim_text = "Test claim"
    return inp


class TestDomainEvidenceFullPath:
    @pytest.mark.asyncio
    async def test_publishes_4_observations_on_success(self):
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        # Content with relevant keywords
        mock_resp.text = "CDC reports that covid vaccines reduced hospitalizations significantly"

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream",
                return_value=stream_mock,
            ),
            patch(
                "swarm_reasoning.agents.fanout_base.aioredis.Redis",
                return_value=redis_mock,
            ),
            patch("swarm_reasoning.agents.fanout_base.activity"),
            patch(
                "swarm_reasoning.agents.domain_evidence.handler.httpx.AsyncClient",
            ) as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            handler = DomainEvidenceHandler()
            result = await handler.run(_make_input())

        assert result.terminal_status == "F"
        assert result.observation_count == 4

        # Verify all 4 observation codes
        obs_codes = []
        for call in stream_mock.publish.call_args_list:
            msg = call[0][1]
            if isinstance(msg, ObsMessage):
                obs_codes.append(msg.observation.code)

        assert obs_codes == [
            ObservationCode.DOMAIN_SOURCE_NAME,
            ObservationCode.DOMAIN_SOURCE_URL,
            ObservationCode.DOMAIN_EVIDENCE_ALIGNMENT,
            ObservationCode.DOMAIN_CONFIDENCE,
        ]


class TestDomainEvidenceAllFail:
    @pytest.mark.asyncio
    async def test_all_sources_fail_publishes_absent(self):
        streams = _mock_upstream_streams()
        stream_mock = _make_stream_mock(streams)
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = ""

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream",
                return_value=stream_mock,
            ),
            patch(
                "swarm_reasoning.agents.fanout_base.aioredis.Redis",
                return_value=redis_mock,
            ),
            patch("swarm_reasoning.agents.fanout_base.activity"),
            patch(
                "swarm_reasoning.agents.domain_evidence.handler.httpx.AsyncClient",
            ) as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            handler = DomainEvidenceHandler()
            result = await handler.run(_make_input())

        assert result.terminal_status == "F"
        assert result.observation_count == 4

        # Check alignment is ABSENT and confidence is 0.0
        for call in stream_mock.publish.call_args_list:
            msg = call[0][1]
            if isinstance(msg, ObsMessage):
                if msg.observation.code == ObservationCode.DOMAIN_EVIDENCE_ALIGNMENT:
                    assert "ABSENT" in msg.observation.value
                elif msg.observation.code == ObservationCode.DOMAIN_CONFIDENCE:
                    assert msg.observation.value == "0.00"
                elif msg.observation.code == ObservationCode.DOMAIN_SOURCE_NAME:
                    assert msg.observation.value == "N/A"
