"""Unit tests for claim intake tool."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from swarm_reasoning.agents.ingestion_agent.tools.claim_intake import (
    IngestionResult,
    StreamNotOpenError,
    StreamPublishError,
    ingest_claim,
)


def _stream_and_redis(*, stream_empty: bool = True, dedup_is_new: bool = True):
    """Create mocked stream and redis client."""
    stream = AsyncMock()
    if stream_empty:
        stream.read_latest.return_value = None
    else:
        stream.read_latest.return_value = AsyncMock()  # non-None = existing messages
    stream.publish = AsyncMock()

    redis_mock = AsyncMock()
    # SETNX returns True (new) or None (dup)
    redis_mock.set.return_value = True if dedup_is_new else None
    redis_mock.xadd = AsyncMock()

    return stream, redis_mock


class TestIngestClaimHappyPath:
    @pytest.mark.asyncio
    async def test_valid_claim_full_metadata(self):
        stream, redis = _stream_and_redis()

        result = await ingest_claim(
            run_id="run-001",
            claim_text="The unemployment rate hit a 50-year low in 2019",
            source_url="https://bls.gov/news.release/empsit.htm",
            source_date="January 10, 2020",
            stream=stream,
            redis_client=redis,
        )

        assert isinstance(result, IngestionResult)
        assert result.accepted is True
        assert result.run_id == "run-001"
        assert result.normalized_date == "20200110"
        assert result.rejection_reason is None

        # START + 3 OBS = 4 publishes (no STOP on success)
        assert stream.publish.call_count == 4

    @pytest.mark.asyncio
    async def test_valid_claim_no_url_no_date(self):
        stream, redis = _stream_and_redis()

        result = await ingest_claim(
            run_id="run-002",
            claim_text="Climate change is accelerating faster than predicted",
            stream=stream,
            redis_client=redis,
        )

        assert result.accepted is True
        assert result.normalized_date is None
        # START + 3 OBS = 4 publishes
        assert stream.publish.call_count == 4

    @pytest.mark.asyncio
    async def test_progress_events_published(self):
        stream, redis = _stream_and_redis()

        await ingest_claim(
            run_id="run-003",
            claim_text="Taxes were raised by 10%",
            stream=stream,
            redis_client=redis,
        )

        # Should have published 2 progress events: validating + accepted
        progress_calls = [c for c in redis.xadd.call_args_list if c[0][0].startswith("progress:")]
        assert len(progress_calls) == 2


class TestIngestClaimRejections:
    @pytest.mark.asyncio
    async def test_text_too_short(self):
        stream, redis = _stream_and_redis()

        result = await ingest_claim(
            run_id="run-010",
            claim_text="Yes",
            stream=stream,
            redis_client=redis,
        )

        assert result.accepted is False
        assert result.rejection_reason == "CLAIM_TEXT_TOO_SHORT"
        # START + X-obs + STOP = 3 publishes
        assert stream.publish.call_count == 3

    @pytest.mark.asyncio
    async def test_text_empty(self):
        stream, redis = _stream_and_redis()

        result = await ingest_claim(
            run_id="run-011",
            claim_text="",
            stream=stream,
            redis_client=redis,
        )

        assert result.accepted is False
        assert result.rejection_reason == "CLAIM_TEXT_EMPTY"

    @pytest.mark.asyncio
    async def test_text_too_long(self):
        stream, redis = _stream_and_redis()

        result = await ingest_claim(
            run_id="run-012",
            claim_text="x" * 2001,
            stream=stream,
            redis_client=redis,
        )

        assert result.accepted is False
        assert result.rejection_reason == "CLAIM_TEXT_TOO_LONG"

    @pytest.mark.asyncio
    async def test_invalid_url(self):
        stream, redis = _stream_and_redis()

        result = await ingest_claim(
            run_id="run-013",
            claim_text="GDP grew 3% in Q3",
            source_url="not-a-url",
            stream=stream,
            redis_client=redis,
        )

        assert result.accepted is False
        assert result.rejection_reason == "SOURCE_URL_INVALID_FORMAT"

    @pytest.mark.asyncio
    async def test_unparseable_date(self):
        stream, redis = _stream_and_redis()

        result = await ingest_claim(
            run_id="run-014",
            claim_text="Taxes were raised last year",
            source_date="yesterday-ish",
            stream=stream,
            redis_client=redis,
        )

        assert result.accepted is False
        assert result.rejection_reason == "SOURCE_DATE_UNPARSEABLE"

    @pytest.mark.asyncio
    async def test_duplicate_claim(self):
        stream, redis = _stream_and_redis(dedup_is_new=False)

        result = await ingest_claim(
            run_id="run-015",
            claim_text="The sky is definitely blue",
            stream=stream,
            redis_client=redis,
        )

        assert result.accepted is False
        assert result.rejection_reason == "DUPLICATE_CLAIM_IN_RUN"

    @pytest.mark.asyncio
    async def test_rejection_publishes_x_status_obs(self):
        stream, redis = _stream_and_redis()

        await ingest_claim(
            run_id="run-016",
            claim_text="No",
            stream=stream,
            redis_client=redis,
        )

        # Second publish should be the X-status observation
        obs_call = stream.publish.call_args_list[1]
        obs_msg = obs_call[0][1]
        assert obs_msg.type == "OBS"
        assert obs_msg.observation.status == "X"
        assert obs_msg.observation.note == "CLAIM_TEXT_TOO_SHORT"


class TestIngestClaimErrors:
    @pytest.mark.asyncio
    async def test_already_open_stream_raises(self):
        stream, redis = _stream_and_redis(stream_empty=False)

        with pytest.raises(StreamNotOpenError):
            await ingest_claim(
                run_id="run-020",
                claim_text="Test claim text here",
                stream=stream,
                redis_client=redis,
            )

    @pytest.mark.asyncio
    async def test_redis_failure_on_start_raises(self):
        stream, redis = _stream_and_redis()
        stream.read_latest.return_value = None
        stream.publish.side_effect = ConnectionError("Redis down")

        with pytest.raises(StreamPublishError):
            await ingest_claim(
                run_id="run-021",
                claim_text="Test claim text here",
                stream=stream,
                redis_client=redis,
            )
