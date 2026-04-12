"""domain-classification tool: LLM-powered domain assignment for claims."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from anthropic import AsyncAnthropic
from pydantic import BaseModel
from redis.asyncio import Redis

from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType
from swarm_reasoning.models.status import EpistemicStatus
from swarm_reasoning.models.stream import ObsMessage, StopMessage
from swarm_reasoning.stream.base import ReasoningStream
from swarm_reasoning.stream.key import stream_key

AGENT_NAME = "ingestion-agent"

DOMAIN_VOCABULARY: frozenset[str] = frozenset(
    {"HEALTHCARE", "ECONOMICS", "POLICY", "SCIENCE", "ELECTION", "CRIME", "OTHER"}
)

_SYSTEM_PROMPT = (
    "You are a domain classifier for a fact-checking system. "
    "Your task is to categorize the given claim into exactly one of the following domains:\n\n"
    "HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER\n\n"
    "Respond with exactly one word -- the domain code. "
    "Do not include punctuation, explanation, or any other text."
)

_RETRY_SUFFIX = (
    "\n\nNote: your previous response was not recognized. "
    "You must respond with exactly one of: "
    "HEALTHCARE, ECONOMICS, POLICY, SCIENCE, ELECTION, CRIME, OTHER"
)


class ClassificationResult(BaseModel):
    """Result from the classify_domain tool."""

    run_id: str
    domain: Literal["HEALTHCARE", "ECONOMICS", "POLICY", "SCIENCE", "ELECTION", "CRIME", "OTHER"]
    confidence: Literal["HIGH", "LOW"]
    attempt_count: int


class StreamStateError(Exception):
    """Stream is not in the expected state for classify_domain."""


class ClassificationServiceError(Exception):
    """Anthropic API call failed."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_prompt(claim_text: str, retry: bool = False) -> list[dict]:
    """Build Anthropic messages for domain classification."""
    user_content = f"Claim: {claim_text}"
    if retry:
        user_content += _RETRY_SUFFIX
    return [{"role": "user", "content": user_content}]


async def call_claude(client: AsyncAnthropic, prompt: list[dict]) -> str:
    """Call Claude for domain classification. Returns stripped uppercase text."""
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=10,
        temperature=0,
        system=_SYSTEM_PROMPT,
        messages=prompt,
    )
    return response.content[0].text.strip().upper()


def _make_domain_obs(
    run_id: str,
    seq: int,
    value: str,
    status: EpistemicStatus,
    note: str | None = None,
) -> ObsMessage:
    return ObsMessage(
        observation=Observation(
            runId=run_id,
            agent=AGENT_NAME,
            seq=seq,
            code=ObservationCode.CLAIM_DOMAIN,
            value=value,
            valueType=ValueType.ST,
            status=status.value,
            timestamp=_now_iso(),
            method="classify_domain",
            note=note,
        )
    )


async def _publish_progress(redis_client: Redis, run_id: str, message: str) -> None:
    await redis_client.xadd(
        f"progress:{run_id}",
        {"agent": AGENT_NAME, "message": message, "timestamp": _now_iso()},
    )


async def classify_domain(
    run_id: str,
    claim_text: str,
    *,
    stream: ReasoningStream,
    anthropic_client: AsyncAnthropic,
    redis_client: Redis,
) -> ClassificationResult:
    """Classify a claim's domain using Claude and publish CLAIM_DOMAIN observations.

    Precondition: ingest_claim must have been called for this run_id and stream
    must be open (START published, no STOP).
    """
    sk = stream_key(run_id, AGENT_NAME)

    # Check stream precondition
    messages = await stream.read_range(sk)
    if not messages:
        raise StreamStateError(f"Stream {sk} does not exist or is empty")

    has_start = False
    has_stop = False
    obs_count = 0
    for msg in messages:
        if msg.type == "START":
            has_start = True
        elif msg.type == "STOP":
            has_stop = True
        elif msg.type == "OBS":
            obs_count += 1

    if not has_start:
        raise StreamStateError(f"Stream {sk} has no START message")
    if has_stop:
        raise StreamStateError(f"Stream {sk} already has a STOP message")

    # Attempt classification
    import anthropic as anthropic_lib

    domain: str | None = None
    attempt_count = 0

    for attempt in range(2):
        attempt_count = attempt + 1
        try:
            prompt = build_prompt(claim_text, retry=(attempt > 0))
            result = await call_claude(anthropic_client, prompt)
        except anthropic_lib.AuthenticationError as exc:
            raise ClassificationServiceError(
                f"Authentication failed: {exc}", retryable=False
            ) from exc
        except (anthropic_lib.APIConnectionError, anthropic_lib.RateLimitError) as exc:
            raise ClassificationServiceError(f"API error: {exc}", retryable=True) from exc

        if result in DOMAIN_VOCABULARY:
            domain = result
            break

    # Publish observations
    if domain is not None:
        # Publish P then F
        seq = obs_count + 1
        await stream.publish(sk, _make_domain_obs(run_id, seq, domain, EpistemicStatus.PRELIMINARY))
        seq += 1
        await stream.publish(sk, _make_domain_obs(run_id, seq, domain, EpistemicStatus.FINAL))
        obs_count += 2
        confidence: Literal["HIGH", "LOW"] = "HIGH"
    else:
        # Fallback to OTHER after two failures
        domain = "OTHER"
        seq = obs_count + 1
        await stream.publish(
            sk,
            _make_domain_obs(
                run_id,
                seq,
                "OTHER",
                EpistemicStatus.FINAL,
                note="LLM returned unrecognized value after 2 attempts; fallback applied",
            ),
        )
        obs_count += 1
        confidence = "LOW"

    # Publish STOP
    await stream.publish(
        sk,
        StopMessage(
            runId=run_id,
            agent=AGENT_NAME,
            finalStatus="F",
            observationCount=obs_count,
            timestamp=_now_iso(),
        ),
    )

    await _publish_progress(redis_client, run_id, f"Domain classified: {domain}")

    return ClassificationResult(
        run_id=run_id,
        domain=domain,
        confidence=confidence,
        attempt_count=attempt_count,
    )
