"""Integration tests for source-validator agent full flow."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.source_validator.handler import SourceValidatorHandler
from swarm_reasoning.models.observation import ObservationCode
from swarm_reasoning.models.stream import ObsMessage, StopMessage


def _make_input(cross_agent_data: dict | None = None) -> MagicMock:
    inp = MagicMock()
    inp.run_id = "run-int-001"
    inp.agent_name = "source-validator"
    inp.claim_text = "Test claim"
    inp.cross_agent_data = cross_agent_data
    return inp


def _make_stream_mock() -> AsyncMock:
    stream_mock = AsyncMock()
    stream_mock.read_range = AsyncMock(return_value=[])
    stream_mock.publish = AsyncMock()
    stream_mock.close = AsyncMock()
    return stream_mock


def _make_http_response(
    status_code: int = 200, body: str = "<html><title>Real Page</title><body>Content</body></html>"
):
    resp = MagicMock()
    resp.status_code = status_code
    resp.history = []
    resp.url = "https://example.com"
    resp.text = body
    return resp


def _standard_cross_agent_data(num_urls: int = 5) -> dict:
    """Generate cross-agent data with num_urls URLs from different agents."""
    agents = [
        ("https://reuters.com/article/1", "coverage-left", "COVERAGE_TOP_SOURCE_URL", "Reuters"),
        ("https://apnews.com/article/2", "coverage-center", "COVERAGE_TOP_SOURCE_URL", "AP"),
        ("https://foxnews.com/article/3", "coverage-right", "COVERAGE_TOP_SOURCE_URL", "Fox News"),
        (
            "https://www.politifact.com/factchecks/2023/test",
            "claimreview-matcher",
            "CLAIMREVIEW_URL",
            "PolitiFact",
        ),
        ("https://www.cdc.gov/covid/data/", "domain-evidence", "DOMAIN_SOURCE_URL", "CDC"),
        ("https://who.int/news/item/2023", "domain-evidence", "DOMAIN_SOURCE_URL", "WHO"),
        ("https://bbc.com/news/article-1", "coverage-center", "COVERAGE_TOP_SOURCE_URL", "BBC"),
        ("https://nytimes.com/2023/article", "coverage-left", "COVERAGE_TOP_SOURCE_URL", "NYT"),
        ("https://wsj.com/articles/test", "coverage-right", "COVERAGE_TOP_SOURCE_URL", "WSJ"),
        ("https://snopes.com/fact-check/test", "claimreview-matcher", "CLAIMREVIEW_URL", "Snopes"),
    ]
    return {
        "urls": [
            {"url": url, "agent": agent, "code": code, "source_name": name}
            for url, agent, code, name in agents[:num_urls]
        ]
    }


class TestSourceValidatorFullFlow:
    @pytest.mark.asyncio
    async def test_full_flow_10_urls(self):
        """Mock HTTP -> 10 URLs -> verify all 4 observation types."""
        cross_data = _standard_cross_agent_data(10)
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        live_resp = _make_http_response(200)
        body_resp = _make_http_response(
            200, "<html><title>Article</title><body>Real content</body></html>"
        )

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=live_resp)
        mock_client.get = AsyncMock(return_value=body_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream", return_value=stream_mock
            ),
            patch("swarm_reasoning.agents.fanout_base.aioredis.Redis", return_value=redis_mock),
            patch("swarm_reasoning.agents.fanout_base.activity"),
            patch(
                "swarm_reasoning.agents.source_validator.validator.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            handler = SourceValidatorHandler()
            result = await handler.run(_make_input(cross_data))

        assert result.terminal_status == "F"
        assert result.observation_count > 0

        # Collect observation codes
        obs_codes = []
        for call in stream_mock.publish.call_args_list:
            msg = call[0][1]
            if isinstance(msg, ObsMessage):
                obs_codes.append(msg.observation.code)

        # Verify all 4 observation types present
        assert ObservationCode.SOURCE_EXTRACTED_URL in obs_codes
        assert ObservationCode.SOURCE_VALIDATION_STATUS in obs_codes
        assert ObservationCode.SOURCE_CONVERGENCE_SCORE in obs_codes
        assert ObservationCode.CITATION_LIST in obs_codes

        # Verify counts: 10 extracted + 10 validated + 1 convergence + 1 citation = 22
        extracted_count = obs_codes.count(ObservationCode.SOURCE_EXTRACTED_URL)
        validated_count = obs_codes.count(ObservationCode.SOURCE_VALIDATION_STATUS)
        assert extracted_count == 10
        assert validated_count == 10

    @pytest.mark.asyncio
    async def test_convergence_3_agents_same_url(self):
        """3 agents cite same URL -> convergence > 0.0, convergenceCount = 3."""
        cross_data = {
            "urls": [
                {
                    "url": "https://cdc.gov/covid/data",
                    "agent": "coverage-center",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "CDC",
                },
                {
                    "url": "https://cdc.gov/covid/data",
                    "agent": "domain-evidence",
                    "code": "DOMAIN_SOURCE_URL",
                    "source_name": "CDC",
                },
                {
                    "url": "https://cdc.gov/covid/data",
                    "agent": "claimreview-matcher",
                    "code": "CLAIMREVIEW_URL",
                    "source_name": "CDC",
                },
                {
                    "url": "https://reuters.com/article",
                    "agent": "coverage-left",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "Reuters",
                },
            ]
        }

        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        live_resp = _make_http_response(200)
        body_resp = _make_http_response(
            200, "<html><title>Article</title><body>Content</body></html>"
        )

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=live_resp)
        mock_client.get = AsyncMock(return_value=body_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream", return_value=stream_mock
            ),
            patch("swarm_reasoning.agents.fanout_base.aioredis.Redis", return_value=redis_mock),
            patch("swarm_reasoning.agents.fanout_base.activity"),
            patch(
                "swarm_reasoning.agents.source_validator.validator.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            handler = SourceValidatorHandler()
            result = await handler.run(_make_input(cross_data))

        assert result.terminal_status == "F"

        # Check convergence score > 0
        for call in stream_mock.publish.call_args_list:
            msg = call[0][1]
            if (
                isinstance(msg, ObsMessage)
                and msg.observation.code == ObservationCode.SOURCE_CONVERGENCE_SCORE
            ):
                score = float(msg.observation.value)
                assert score > 0.0

        # Check CITATION_LIST has convergenceCount = 3 for CDC
        for call in stream_mock.publish.call_args_list:
            msg = call[0][1]
            if (
                isinstance(msg, ObsMessage)
                and msg.observation.code == ObservationCode.CITATION_LIST
            ):
                citations = json.loads(msg.observation.value)
                cdc_citations = [
                    c for c in citations if c["sourceUrl"] == "https://cdc.gov/covid/data"
                ]
                assert all(c["convergenceCount"] == 3 for c in cdc_citations)

    @pytest.mark.asyncio
    async def test_mixed_validation_statuses(self):
        """Mix of live, dead, soft-404 URLs -> correct validation statuses."""
        cross_data = {
            "urls": [
                {
                    "url": "https://live.com/article",
                    "agent": "coverage-left",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "Live",
                },
                {
                    "url": "https://dead.com/removed",
                    "agent": "coverage-center",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "Dead",
                },
                {
                    "url": "https://soft404.com/gone",
                    "agent": "coverage-right",
                    "code": "COVERAGE_TOP_SOURCE_URL",
                    "source_name": "Soft404",
                },
            ]
        }

        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        def make_head_response(url, **kwargs):
            resp = MagicMock()
            resp.history = []
            if "dead.com" in str(url):
                resp.status_code = 404
            else:
                resp.status_code = 200
            return resp

        def make_get_response(url, **kwargs):
            resp = MagicMock()
            resp.history = []
            resp.status_code = 200
            if "soft404.com" in str(url):
                resp.text = (
                    "<html><head><title>Page Not Found</title></head><body>Sorry</body></html>"
                )
            else:
                resp.text = (
                    "<html><head><title>Real Article</title></head><body>Content</body></html>"
                )
            return resp

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(side_effect=make_head_response)
        mock_client.get = AsyncMock(side_effect=make_get_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream", return_value=stream_mock
            ),
            patch("swarm_reasoning.agents.fanout_base.aioredis.Redis", return_value=redis_mock),
            patch("swarm_reasoning.agents.fanout_base.activity"),
            patch(
                "swarm_reasoning.agents.source_validator.validator.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            handler = SourceValidatorHandler()
            result = await handler.run(_make_input(cross_data))

        assert result.terminal_status == "F"

        # Collect validation statuses
        validation_values = []
        for call in stream_mock.publish.call_args_list:
            msg = call[0][1]
            if (
                isinstance(msg, ObsMessage)
                and msg.observation.code == ObservationCode.SOURCE_VALIDATION_STATUS
            ):
                validation_values.append(msg.observation.value)

        assert "LIVE^Live^FCK" in validation_values
        assert "DEAD^Dead^FCK" in validation_values
        assert "SOFT404^Soft 404^FCK" in validation_values

    @pytest.mark.asyncio
    async def test_empty_input(self):
        """Empty input -> convergence 0.0, empty citation list, STOP F."""
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream", return_value=stream_mock
            ),
            patch("swarm_reasoning.agents.fanout_base.aioredis.Redis", return_value=redis_mock),
            patch("swarm_reasoning.agents.fanout_base.activity"),
        ):
            handler = SourceValidatorHandler()
            result = await handler.run(_make_input({"urls": []}))

        assert result.terminal_status == "F"

        # Check convergence = 0.0
        convergence_found = False
        citation_found = False
        for call in stream_mock.publish.call_args_list:
            msg = call[0][1]
            if isinstance(msg, ObsMessage):
                if msg.observation.code == ObservationCode.SOURCE_CONVERGENCE_SCORE:
                    assert msg.observation.value == "0.0"
                    convergence_found = True
                elif msg.observation.code == ObservationCode.CITATION_LIST:
                    data = json.loads(msg.observation.value)
                    assert data == []
                    citation_found = True

        assert convergence_found
        assert citation_found

        # Verify STOP with F
        stop_found = False
        for call in stream_mock.publish.call_args_list:
            msg = call[0][1]
            if isinstance(msg, StopMessage):
                assert msg.final_status == "F"
                stop_found = True
        assert stop_found

    @pytest.mark.asyncio
    async def test_citation_list_valid_json(self):
        """CITATION_LIST JSON is valid and matches Citation schema."""
        cross_data = _standard_cross_agent_data(4)
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        live_resp = _make_http_response(200)
        body_resp = _make_http_response(
            200, "<html><title>Article</title><body>Content</body></html>"
        )

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=live_resp)
        mock_client.get = AsyncMock(return_value=body_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream", return_value=stream_mock
            ),
            patch("swarm_reasoning.agents.fanout_base.aioredis.Redis", return_value=redis_mock),
            patch("swarm_reasoning.agents.fanout_base.activity"),
            patch(
                "swarm_reasoning.agents.source_validator.validator.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            handler = SourceValidatorHandler()
            await handler.run(_make_input(cross_data))

        for call in stream_mock.publish.call_args_list:
            msg = call[0][1]
            if (
                isinstance(msg, ObsMessage)
                and msg.observation.code == ObservationCode.CITATION_LIST
            ):
                data = json.loads(msg.observation.value)
                assert isinstance(data, list)
                assert len(data) == 4
                for entry in data:
                    assert set(entry.keys()) == {
                        "sourceUrl",
                        "sourceName",
                        "agent",
                        "observationCode",
                        "validationStatus",
                        "convergenceCount",
                    }

    @pytest.mark.asyncio
    async def test_progress_events(self):
        """Progress events published to progress:{runId}."""
        cross_data = _standard_cross_agent_data(3)
        stream_mock = _make_stream_mock()
        redis_mock = AsyncMock()
        redis_mock.xadd = AsyncMock()
        redis_mock.aclose = AsyncMock()

        live_resp = _make_http_response(200)
        body_resp = _make_http_response(
            200, "<html><title>Article</title><body>Content</body></html>"
        )

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=live_resp)
        mock_client.get = AsyncMock(return_value=body_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "swarm_reasoning.agents.fanout_base.RedisReasoningStream", return_value=stream_mock
            ),
            patch("swarm_reasoning.agents.fanout_base.aioredis.Redis", return_value=redis_mock),
            patch("swarm_reasoning.agents.fanout_base.activity"),
            patch(
                "swarm_reasoning.agents.source_validator.validator.httpx.AsyncClient",
                return_value=mock_client,
            ),
        ):
            handler = SourceValidatorHandler()
            await handler.run(_make_input(cross_data))

        # Check progress events were published
        progress_messages = []
        for call in redis_mock.xadd.call_args_list:
            key = call[0][0]
            if key.startswith("progress:"):
                progress_messages.append(call[0][1]["message"])

        # Should have: starting, validating, validated, aggregated
        assert any("source-validator" in m for m in progress_messages)
        assert any("Validating" in m for m in progress_messages)
