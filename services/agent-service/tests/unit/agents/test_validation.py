"""Unit tests for ingestion agent validation layer."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from swarm_reasoning.pipeline.nodes.intake import check_duplicate
from swarm_reasoning.pipeline.nodes.intake_validation import (
    ValidationError,
    normalize_date,
    validate_claim_text,
    validate_source_url,
)

# ---------------------------------------------------------------------------
# validate_claim_text
# ---------------------------------------------------------------------------


class TestValidateClaimText:
    def test_valid_claim(self):
        validate_claim_text("The unemployment rate hit a 50-year low in 2019")

    def test_minimum_length(self):
        validate_claim_text("Hello")  # exactly 5 chars

    def test_maximum_length(self):
        validate_claim_text("x" * 2000)

    def test_empty_raises(self):
        with pytest.raises(ValidationError, match="CLAIM_TEXT_EMPTY"):
            validate_claim_text("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValidationError, match="CLAIM_TEXT_EMPTY"):
            validate_claim_text("   ")

    def test_too_short_raises(self):
        with pytest.raises(ValidationError, match="CLAIM_TEXT_TOO_SHORT"):
            validate_claim_text("Yes")

    def test_too_long_raises(self):
        with pytest.raises(ValidationError, match="CLAIM_TEXT_TOO_LONG"):
            validate_claim_text("x" * 2001)

    def test_strips_before_checking(self):
        # " ab " strips to "ab" which is < 5
        with pytest.raises(ValidationError, match="CLAIM_TEXT_TOO_SHORT"):
            validate_claim_text("  ab  ")


# ---------------------------------------------------------------------------
# validate_source_url
# ---------------------------------------------------------------------------


class TestValidateSourceUrl:
    def test_valid_https(self):
        validate_source_url("https://bls.gov/news.release/empsit.htm")

    def test_valid_http(self):
        validate_source_url("http://example.com/page")

    def test_missing_protocol(self):
        with pytest.raises(ValidationError, match="SOURCE_URL_INVALID_FORMAT"):
            validate_source_url("not-a-url")

    def test_missing_tld(self):
        with pytest.raises(ValidationError, match="SOURCE_URL_INVALID_FORMAT"):
            validate_source_url("https://localhost")

    def test_ftp_rejected(self):
        with pytest.raises(ValidationError, match="SOURCE_URL_INVALID_FORMAT"):
            validate_source_url("ftp://files.example.com/data")

    def test_empty_string(self):
        with pytest.raises(ValidationError, match="SOURCE_URL_INVALID_FORMAT"):
            validate_source_url("")


# ---------------------------------------------------------------------------
# normalize_date
# ---------------------------------------------------------------------------


class TestNormalizeDate:
    def test_full_date_string(self):
        assert normalize_date("January 10, 2020") == "20200110"

    def test_iso_format(self):
        assert normalize_date("2026-04-06") == "20260406"

    def test_slash_format(self):
        result = normalize_date("04/06/2026")
        assert result == "20260406"

    def test_unparseable(self):
        with pytest.raises(ValidationError, match="SOURCE_DATE_UNPARSEABLE"):
            normalize_date("not a date")

    def test_yesterday_ish(self):
        with pytest.raises(ValidationError, match="SOURCE_DATE_UNPARSEABLE"):
            normalize_date("yesterday-ish")


# ---------------------------------------------------------------------------
# check_duplicate
# ---------------------------------------------------------------------------


class TestCheckDuplicate:
    @pytest.mark.asyncio
    async def test_new_claim_returns_false(self):
        redis_mock = AsyncMock()
        redis_mock.set.return_value = True  # SETNX succeeded = new key
        result = await check_duplicate(redis_mock, "run-1", "The sky is blue")
        assert result is False
        redis_mock.set.assert_called_once()
        call_kwargs = redis_mock.set.call_args
        assert call_kwargs[1]["ex"] == 86400
        assert call_kwargs[1]["nx"] is True

    @pytest.mark.asyncio
    async def test_duplicate_claim_returns_true(self):
        redis_mock = AsyncMock()
        redis_mock.set.return_value = None  # SETNX failed = key exists
        result = await check_duplicate(redis_mock, "run-1", "The sky is blue")
        assert result is True

    @pytest.mark.asyncio
    async def test_same_text_different_run_is_not_duplicate(self):
        redis_mock = AsyncMock()
        redis_mock.set.return_value = True
        result = await check_duplicate(redis_mock, "run-2", "The sky is blue")
        assert result is False
        # Key should contain "run-2"
        key_arg = redis_mock.set.call_args[0][0]
        assert "run-2" in key_arg
