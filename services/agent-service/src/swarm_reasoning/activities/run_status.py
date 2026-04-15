"""Run lifecycle activities: status transitions persisted to PostgreSQL (ADR-0017).

The Temporal workflow calls these activities to update run status. The NestJS
backend queries PostgreSQL directly for run status, decoupling the query path
from the Temporal workflow.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from temporalio import activity
from temporalio.exceptions import ApplicationError


class RunStatusEnum(str, Enum):
    PENDING = "pending"
    INGESTING = "ingesting"
    ANALYZING = "analyzing"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


TERMINAL_STATUSES = frozenset({
    RunStatusEnum.COMPLETED, RunStatusEnum.CANCELLED, RunStatusEnum.FAILED,
})

# Valid state transitions matching services/backend/src/domain/entities/run.entity.ts
_CANCEL_FAIL = frozenset({RunStatusEnum.CANCELLED, RunStatusEnum.FAILED})
_COMPLETE = frozenset({RunStatusEnum.COMPLETED})
VALID_TRANSITIONS: dict[RunStatusEnum, frozenset[RunStatusEnum]] = {
    # Pending can go to Ingesting (phased) or directly to Completed (simplified pipeline)
    RunStatusEnum.PENDING: frozenset({RunStatusEnum.INGESTING}) | _COMPLETE | _CANCEL_FAIL,
    RunStatusEnum.INGESTING: frozenset({RunStatusEnum.ANALYZING}) | _COMPLETE | _CANCEL_FAIL,
    RunStatusEnum.ANALYZING: frozenset({RunStatusEnum.SYNTHESIZING}) | _COMPLETE | _CANCEL_FAIL,
    RunStatusEnum.SYNTHESIZING: _COMPLETE | _CANCEL_FAIL,
    RunStatusEnum.COMPLETED: frozenset(),
    RunStatusEnum.CANCELLED: frozenset(),
    RunStatusEnum.FAILED: frozenset(),
}

# Maps phase names to the run status that should be active during that phase
PHASE_STATUS_MAP: dict[str, RunStatusEnum] = {
    "ingestion": RunStatusEnum.INGESTING,
    "fanout": RunStatusEnum.ANALYZING,
    "fanout-validation": RunStatusEnum.ANALYZING,
    "synthesis": RunStatusEnum.SYNTHESIZING,
}


class InvalidRunTransition(ValueError):
    """Raised when an invalid run status transition is attempted."""

    def __init__(self, from_status: RunStatusEnum, to_status: RunStatusEnum) -> None:
        super().__init__(f"Invalid run transition: {from_status.value} -> {to_status.value}")
        self.from_status = from_status
        self.to_status = to_status


def validate_transition(from_status: RunStatusEnum, to_status: RunStatusEnum) -> None:
    """Validate that a run status transition is allowed."""
    allowed = VALID_TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise InvalidRunTransition(from_status, to_status)


@dataclass
class RunStatusInput:
    run_id: str
    new_status: str
    reason: str | None = None


@dataclass
class RunStatusResult:
    run_id: str
    previous_status: str
    current_status: str


# In-memory run status store. In production, this writes to PostgreSQL via
# async SQLAlchemy. For now, activities use a module-level dict that the
# worker populates with a real DB adapter at startup.
_run_store: dict[str, RunStatusEnum] = {}


def set_run_store(store: dict[str, RunStatusEnum]) -> None:
    """Inject the run status store. Called by worker setup."""
    global _run_store
    _run_store = store


def get_run_store() -> dict[str, RunStatusEnum]:
    """Get the current run status store reference."""
    return _run_store


@activity.defn
async def update_run_status(input: RunStatusInput) -> RunStatusResult:
    """Validate transition and persist new run status."""
    current = _run_store.get(input.run_id, RunStatusEnum.PENDING)
    new_status = RunStatusEnum(input.new_status)
    try:
        validate_transition(current, new_status)
    except InvalidRunTransition as exc:
        raise ApplicationError(
            str(exc), type="InvalidRunTransition", non_retryable=True,
        ) from exc
    _run_store[input.run_id] = new_status
    activity.logger.info(
        "Run %s: %s -> %s", input.run_id, current.value, new_status.value
    )
    return RunStatusResult(
        run_id=input.run_id,
        previous_status=current.value,
        current_status=new_status.value,
    )


@activity.defn
async def cancel_run(input: RunStatusInput) -> RunStatusResult:
    """Transition run to cancelled. No-op if already terminal."""
    current = _run_store.get(input.run_id, RunStatusEnum.PENDING)
    if current in TERMINAL_STATUSES:
        activity.logger.info(
            "Run %s already terminal (%s), cancel is no-op", input.run_id, current.value
        )
        return RunStatusResult(
            run_id=input.run_id,
            previous_status=current.value,
            current_status=current.value,
        )
    _run_store[input.run_id] = RunStatusEnum.CANCELLED
    activity.logger.info(
        "Run %s: %s -> cancelled (reason: %s)",
        input.run_id, current.value, input.reason,
    )
    return RunStatusResult(
        run_id=input.run_id,
        previous_status=current.value,
        current_status=RunStatusEnum.CANCELLED.value,
    )


@activity.defn
async def fail_run(input: RunStatusInput) -> RunStatusResult:
    """Transition run to failed. No-op if already terminal."""
    current = _run_store.get(input.run_id, RunStatusEnum.PENDING)
    if current in TERMINAL_STATUSES:
        activity.logger.info(
            "Run %s already terminal (%s), fail is no-op", input.run_id, current.value
        )
        return RunStatusResult(
            run_id=input.run_id,
            previous_status=current.value,
            current_status=current.value,
        )
    _run_store[input.run_id] = RunStatusEnum.FAILED
    activity.logger.info(
        "Run %s: %s -> failed (reason: %s)",
        input.run_id, current.value, input.reason,
    )
    return RunStatusResult(
        run_id=input.run_id,
        previous_status=current.value,
        current_status=RunStatusEnum.FAILED.value,
    )


@activity.defn
async def get_run_status(run_id: str) -> str:
    """Read current run status from the store."""
    status = _run_store.get(run_id, RunStatusEnum.PENDING)
    return status.value
