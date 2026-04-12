"""Retry policies and activity timeouts per phase (ADR-016).

Phase 1 (ingestion): 30s start-to-close — local NLP, no external APIs.
Phase 2 (fan-out):   45s start-to-close — external API calls may be slower.
Phase 3 (synthesis): 60s start-to-close — reads all streams, produces verdict.

Schedule-to-close is 2x start-to-close to allow for queuing + retries.

Retry: 3 attempts with exponential backoff for transient LLM/API failures.
Non-retryable errors (invalid claim, missing key, schema violation) fail
immediately.
"""

from datetime import timedelta

from temporalio.common import RetryPolicy

from swarm_reasoning.temporal.errors import NON_RETRYABLE_ERROR_TYPES

# ---------------------------------------------------------------------------
# Retry policy — shared across all phases
# ---------------------------------------------------------------------------

DEFAULT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=30),
    maximum_attempts=3,
    non_retryable_error_types=NON_RETRYABLE_ERROR_TYPES,
)

# ---------------------------------------------------------------------------
# Phase 1: Sequential ingestion (ingestion-agent, claim-detector, entity-extractor)
# ---------------------------------------------------------------------------

PHASE_1_START_TO_CLOSE = timedelta(seconds=30)
PHASE_1_SCHEDULE_TO_CLOSE = timedelta(seconds=60)

# ---------------------------------------------------------------------------
# Phase 2: Parallel fan-out (claimreview-matcher, coverage-*, domain-evidence,
#           source-validator)
# ---------------------------------------------------------------------------

PHASE_2_START_TO_CLOSE = timedelta(seconds=45)
PHASE_2_SCHEDULE_TO_CLOSE = timedelta(seconds=90)

# ---------------------------------------------------------------------------
# Phase 3: Sequential synthesis (blindspot-detector, synthesizer)
# ---------------------------------------------------------------------------

PHASE_3_START_TO_CLOSE = timedelta(seconds=60)
PHASE_3_SCHEDULE_TO_CLOSE = timedelta(seconds=120)
