"""Epistemic status enum with transition validation (ADR-005)."""

from enum import Enum


class InvalidStatusTransition(ValueError):
    """Raised when an invalid epistemic status transition is attempted."""

    def __init__(self, from_status: "EpistemicStatus", to_status: "EpistemicStatus") -> None:
        super().__init__(f"Invalid status transition: {from_status.value} → {to_status.value}")
        self.from_status = from_status
        self.to_status = to_status


class EpistemicStatus(str, Enum):
    """Epistemic status carried on every observation.

    P — Preliminary: hypothesis or initial finding, not yet corroborated
    F — Final: agent considers this finding settled
    C — Corrected: supersedes an earlier observation of the same code
    X — Cancelled: claim not check-worthy or finding retracted
    """

    PRELIMINARY = "P"
    FINAL = "F"
    CORRECTED = "C"
    CANCELLED = "X"


# Valid transitions: from_status -> set of allowed to_statuses
_VALID_TRANSITIONS: dict[EpistemicStatus, set[EpistemicStatus]] = {
    EpistemicStatus.PRELIMINARY: {EpistemicStatus.FINAL, EpistemicStatus.CANCELLED},
    EpistemicStatus.FINAL: {EpistemicStatus.CORRECTED},
    EpistemicStatus.CORRECTED: {EpistemicStatus.CORRECTED},
    EpistemicStatus.CANCELLED: set(),
}


def validate_status_transition(from_status: EpistemicStatus, to_status: EpistemicStatus) -> None:
    """Validate that a status transition is allowed.

    Raises InvalidStatusTransition if the transition is not in the allowed set.
    """
    allowed = _VALID_TRANSITIONS.get(from_status, set())
    if to_status not in allowed:
        raise InvalidStatusTransition(from_status, to_status)
