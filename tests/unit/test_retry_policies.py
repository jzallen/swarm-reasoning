"""Tests for retry policies and phase-specific activity timeouts."""

from datetime import timedelta

from swarm_reasoning.temporal.errors import NON_RETRYABLE_ERROR_TYPES
from swarm_reasoning.temporal.retry import (
    DEFAULT_RETRY_POLICY,
    PHASE_1_SCHEDULE_TO_CLOSE,
    PHASE_1_START_TO_CLOSE,
    PHASE_2_SCHEDULE_TO_CLOSE,
    PHASE_2_START_TO_CLOSE,
    PHASE_3_SCHEDULE_TO_CLOSE,
    PHASE_3_START_TO_CLOSE,
)


class TestDefaultRetryPolicy:
    def test_max_attempts(self):
        assert DEFAULT_RETRY_POLICY.maximum_attempts == 3

    def test_initial_interval(self):
        assert DEFAULT_RETRY_POLICY.initial_interval == timedelta(seconds=5)

    def test_backoff_coefficient(self):
        assert DEFAULT_RETRY_POLICY.backoff_coefficient == 2.0

    def test_maximum_interval(self):
        assert DEFAULT_RETRY_POLICY.maximum_interval == timedelta(seconds=30)

    def test_non_retryable_error_types(self):
        assert "InvalidClaimError" in DEFAULT_RETRY_POLICY.non_retryable_error_types
        assert "MissingApiKeyError" in DEFAULT_RETRY_POLICY.non_retryable_error_types
        assert "SchemaValidationError" in DEFAULT_RETRY_POLICY.non_retryable_error_types


class TestNonRetryableErrors:
    def test_three_error_types(self):
        assert len(NON_RETRYABLE_ERROR_TYPES) == 3

    def test_error_type_names(self):
        assert set(NON_RETRYABLE_ERROR_TYPES) == {
            "InvalidClaimError",
            "MissingApiKeyError",
            "SchemaValidationError",
        }


class TestPhaseTimeouts:
    def test_phase_1_start_to_close(self):
        assert PHASE_1_START_TO_CLOSE == timedelta(seconds=30)

    def test_phase_1_schedule_to_close(self):
        assert PHASE_1_SCHEDULE_TO_CLOSE == timedelta(seconds=60)

    def test_phase_2_start_to_close(self):
        assert PHASE_2_START_TO_CLOSE == timedelta(seconds=45)

    def test_phase_2_schedule_to_close(self):
        assert PHASE_2_SCHEDULE_TO_CLOSE == timedelta(seconds=90)

    def test_phase_3_start_to_close(self):
        assert PHASE_3_START_TO_CLOSE == timedelta(seconds=60)

    def test_phase_3_schedule_to_close(self):
        assert PHASE_3_SCHEDULE_TO_CLOSE == timedelta(seconds=120)

    def test_schedule_is_double_start(self):
        """Schedule-to-close should be 2x start-to-close for all phases."""
        assert PHASE_1_SCHEDULE_TO_CLOSE == PHASE_1_START_TO_CLOSE * 2
        assert PHASE_2_SCHEDULE_TO_CLOSE == PHASE_2_START_TO_CLOSE * 2
        assert PHASE_3_SCHEDULE_TO_CLOSE == PHASE_3_START_TO_CLOSE * 2

    def test_timeouts_increase_by_phase(self):
        """Later phases get progressively longer timeouts."""
        assert PHASE_1_START_TO_CLOSE < PHASE_2_START_TO_CLOSE
        assert PHASE_2_START_TO_CLOSE < PHASE_3_START_TO_CLOSE
