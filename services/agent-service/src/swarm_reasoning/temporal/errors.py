"""Non-retryable error types for Temporal activity execution.

These errors indicate permanent failures that should NOT be retried.
Temporal's retry policy uses error type names to match against
non_retryable_error_types.
"""


class InvalidClaimError(Exception):
    """Claim text is malformed or empty — retrying won't fix it."""


class MissingApiKeyError(Exception):
    """Required API key is not configured — retrying won't fix it."""


class SchemaValidationError(Exception):
    """Observation schema validation failed — retrying won't fix it."""


NON_RETRYABLE_ERROR_TYPES = [
    "InvalidClaimError",
    "MissingApiKeyError",
    "SchemaValidationError",
]
