"""Structural validators for claim intake (ADR-004)."""

from __future__ import annotations

import hashlib
import re

from dateutil import parser as dateutil_parser
from redis.asyncio import Redis


class ValidationError(Exception):
    """Raised when a claim submission fails structural validation."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


_URL_PATTERN = re.compile(r"^https?://[^\s]+\.[^\s]{2,}$")


def validate_claim_text(text: str) -> None:
    """Validate claim text length. Raises ValidationError on failure."""
    stripped = text.strip()
    if not stripped:
        raise ValidationError("CLAIM_TEXT_EMPTY")
    if len(stripped) < 5:
        raise ValidationError("CLAIM_TEXT_TOO_SHORT")
    if len(stripped) > 2000:
        raise ValidationError("CLAIM_TEXT_TOO_LONG")


def validate_source_url(url: str) -> None:
    """Validate URL format. Raises ValidationError if malformed."""
    if not _URL_PATTERN.match(url):
        raise ValidationError("SOURCE_URL_INVALID_FORMAT")


def normalize_date(date_str: str) -> str:
    """Parse a date string and return YYYYMMDD. Raises ValidationError if unparseable."""
    try:
        dt = dateutil_parser.parse(date_str)
    except (ValueError, OverflowError):
        raise ValidationError("SOURCE_DATE_UNPARSEABLE")
    return dt.strftime("%Y%m%d")


async def check_duplicate(redis_client: Redis, run_id: str, claim_text: str) -> bool:
    """Return True if this claim text was already submitted for this run.

    Uses SETNX with 24h TTL for dedup. Returns True = duplicate, False = new.
    """
    claim_hash = hashlib.sha256(claim_text.strip().encode()).hexdigest()
    key = f"reasoning:dedup:{run_id}:{claim_hash}"
    # SET ... NX EX — returns True if key was SET (new), None if already exists (dup)
    was_set = await redis_client.set(key, "1", ex=86400, nx=True)
    return was_set is None  # True means duplicate
