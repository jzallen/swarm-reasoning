"""URL validation via HTTP HEAD with soft-404 detection."""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

from swarm_reasoning.agents.source_validator.models import ValidationResult, ValidationStatus

logger = logging.getLogger(__name__)

# Soft-404 indicators (case-insensitive)
_TITLE_INDICATORS = re.compile(
    r"<title[^>]*>.*?(page not found|404|not found|no longer available).*?</title>",
    re.IGNORECASE | re.DOTALL,
)

_BODY_INDICATORS = (
    "this page doesn't exist",
    "the page you requested",
    "has been removed",
)

# Per-URL timeout
_URL_TIMEOUT_S = 5.0

# Max concurrent connections
_MAX_CONCURRENCY = 10


def _is_soft_404(body: str) -> bool:
    """Check if response body indicates a soft-404 page."""
    if _TITLE_INDICATORS.search(body):
        return True
    body_lower = body.lower()
    return any(indicator in body_lower for indicator in _BODY_INDICATORS)


class UrlValidator:
    """Validates URLs via HTTP HEAD with redirect following and soft-404 detection."""

    async def validate_all(
        self, urls: list[str], timeout_s: float = 25.0
    ) -> dict[str, ValidationResult]:
        """Validate all URLs concurrently with bounded concurrency.

        Returns a dict mapping URL -> ValidationResult.
        Handles overall timeout by marking remaining URLs as TIMEOUT.
        """
        if not urls:
            return {}

        sem = asyncio.Semaphore(_MAX_CONCURRENCY)
        results: dict[str, ValidationResult] = {}

        async def validate_one(client: httpx.AsyncClient, url: str) -> None:
            async with sem:
                results[url] = await self._validate_url(client, url)

        try:
            async with httpx.AsyncClient(
                timeout=_URL_TIMEOUT_S,
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                tasks = [asyncio.create_task(validate_one(client, u)) for u in urls]
                gathered = asyncio.gather(*tasks, return_exceptions=True)
                await asyncio.wait_for(gathered, timeout=timeout_s)
        except asyncio.TimeoutError:
            logger.warning(
                "URL validation timed out after %.0fs, marking remaining as TIMEOUT",
                timeout_s,
            )

        # Mark any URLs not yet validated as TIMEOUT
        for url in urls:
            if url not in results:
                results[url] = ValidationResult(
                    url=url, status=ValidationStatus.TIMEOUT, error="Activity timeout"
                )

        return results

    async def _validate_url(self, client: httpx.AsyncClient, url: str) -> ValidationResult:
        """Validate a single URL."""
        try:
            resp = await client.head(url)

            # HEAD 405 fallback to GET
            if resp.status_code == 405:
                resp = await client.get(url, headers={"Range": "bytes=0-1023"})

            if resp.status_code >= 400:
                return ValidationResult(url=url, status=ValidationStatus.DEAD)

            # Check for redirect (history non-empty means redirects occurred)
            if resp.history:
                return ValidationResult(
                    url=url,
                    status=ValidationStatus.REDIRECT,
                    final_url=str(resp.url),
                )

            # HTTP 200 — check for soft-404
            if resp.status_code == 200:
                if await self._check_soft_404(client, url):
                    return ValidationResult(url=url, status=ValidationStatus.SOFT404)

            return ValidationResult(url=url, status=ValidationStatus.LIVE)

        except httpx.TimeoutException:
            return ValidationResult(url=url, status=ValidationStatus.TIMEOUT)
        except Exception as exc:
            logger.warning("Validation error for %s: %s", url, exc)
            return ValidationResult(url=url, status=ValidationStatus.TIMEOUT, error=str(exc))

    async def _check_soft_404(self, client: httpx.AsyncClient, url: str) -> bool:
        """Fetch first 2KB of body and check for soft-404 indicators."""
        try:
            resp = await client.get(url)
            body = resp.text[:2048]
            return _is_soft_404(body)
        except Exception:
            return False
