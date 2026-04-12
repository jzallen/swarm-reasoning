"""Harness runner: submits claims to the backend API and collects verdicts."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:3000"
POLL_INTERVAL_S = 2.0
POLL_TIMEOUT_S = 150.0


@dataclass
class RunResult:
    """Result of a single claim run."""

    session_id: str
    claim_id: str
    verdict: dict | None
    observations: list[dict]
    elapsed_seconds: float


class HarnessRunner:
    """Submits claims to the backend and polls for completion."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def create_session(self) -> str:
        """Create a new session and return its ID."""
        resp = await self._client.post("/sessions")
        resp.raise_for_status()
        return resp.json()["sessionId"]

    async def submit_claim(self, session_id: str, claim_text: str) -> None:
        """Submit a claim to an existing session."""
        resp = await self._client.post(
            f"/sessions/{session_id}/claims",
            json={"claim": claim_text},
        )
        resp.raise_for_status()

    async def poll_until_frozen(self, session_id: str) -> float:
        """Poll session status until frozen/expired. Returns elapsed seconds."""
        import time

        start = time.monotonic()
        deadline = start + POLL_TIMEOUT_S

        while time.monotonic() < deadline:
            resp = await self._client.get(f"/sessions/{session_id}")
            resp.raise_for_status()
            status = resp.json()["status"]

            if status in ("frozen", "expired"):
                return time.monotonic() - start

            await asyncio.sleep(POLL_INTERVAL_S)

        raise TimeoutError(
            f"Session {session_id} did not reach frozen state within {POLL_TIMEOUT_S}s"
        )

    async def fetch_verdict(self, session_id: str) -> dict | None:
        """Fetch the verdict for a session."""
        resp = await self._client.get(f"/sessions/{session_id}/verdict")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    async def fetch_observations(self, session_id: str) -> list[dict]:
        """Fetch the observation streams for a session."""
        resp = await self._client.get(f"/sessions/{session_id}/observations")
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return resp.json()

    async def run_claim(self, claim_id: str, claim_text: str) -> RunResult:
        """Run a single claim end-to-end: create, submit, poll, fetch."""
        session_id = await self.create_session()
        await self.submit_claim(session_id, claim_text)
        elapsed = await self.poll_until_frozen(session_id)
        verdict = await self.fetch_verdict(session_id)
        observations = await self.fetch_observations(session_id)

        return RunResult(
            session_id=session_id,
            claim_id=claim_id,
            verdict=verdict,
            observations=observations,
            elapsed_seconds=elapsed,
        )

    async def run_corpus(
        self,
        claims: list[dict],
    ) -> list[RunResult]:
        """Run all claims sequentially (submit sequential, poll parallel)."""
        results: list[RunResult] = []

        for claim in claims:
            logger.info("Processing claim %s: %s", claim["id"], claim["claim_text"][:60])
            result = await self.run_claim(claim["id"], claim["claim_text"])
            results.append(result)
            logger.info(
                "Claim %s completed in %.1fs — verdict: %s",
                claim["id"],
                result.elapsed_seconds,
                result.verdict.get("ratingLabel") if result.verdict else "NONE",
            )

        return results
