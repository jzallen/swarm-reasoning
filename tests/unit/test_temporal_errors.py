"""Tests for non-retryable error types."""

import pytest

from swarm_reasoning.temporal.errors import (
    NON_RETRYABLE_ERROR_TYPES,
    InvalidClaimError,
    MissingApiKeyError,
    SchemaValidationError,
)


class TestErrorTypes:
    def test_invalid_claim_error_is_exception(self):
        with pytest.raises(InvalidClaimError, match="empty"):
            raise InvalidClaimError("Claim text is empty")

    def test_missing_api_key_error_is_exception(self):
        with pytest.raises(MissingApiKeyError, match="ANTHROPIC"):
            raise MissingApiKeyError("ANTHROPIC_API_KEY not set")

    def test_schema_validation_error_is_exception(self):
        with pytest.raises(SchemaValidationError, match="CWE"):
            raise SchemaValidationError("CWE format invalid")

    def test_non_retryable_list_matches_classes(self):
        error_classes = [InvalidClaimError, MissingApiKeyError, SchemaValidationError]
        for cls in error_classes:
            assert cls.__name__ in NON_RETRYABLE_ERROR_TYPES
