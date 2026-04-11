"""Tests for run lifecycle status transitions."""

import pytest

from swarm_reasoning.activities.run_status import (
    TERMINAL_STATUSES,
    VALID_TRANSITIONS,
    InvalidRunTransition,
    RunStatusEnum,
    validate_transition,
)


def test_all_statuses_have_transition_entries():
    for status in RunStatusEnum:
        assert status in VALID_TRANSITIONS


def test_terminal_statuses():
    assert RunStatusEnum.COMPLETED in TERMINAL_STATUSES
    assert RunStatusEnum.CANCELLED in TERMINAL_STATUSES
    assert RunStatusEnum.FAILED in TERMINAL_STATUSES
    assert RunStatusEnum.PENDING not in TERMINAL_STATUSES


def test_valid_transitions():
    # Happy path through all phases
    validate_transition(RunStatusEnum.PENDING, RunStatusEnum.INGESTING)
    validate_transition(RunStatusEnum.INGESTING, RunStatusEnum.ANALYZING)
    validate_transition(RunStatusEnum.ANALYZING, RunStatusEnum.SYNTHESIZING)
    validate_transition(RunStatusEnum.SYNTHESIZING, RunStatusEnum.COMPLETED)


def test_cancel_from_any_non_terminal():
    for status in (RunStatusEnum.PENDING, RunStatusEnum.INGESTING,
                   RunStatusEnum.ANALYZING, RunStatusEnum.SYNTHESIZING):
        validate_transition(status, RunStatusEnum.CANCELLED)


def test_fail_from_any_non_terminal():
    for status in (RunStatusEnum.PENDING, RunStatusEnum.INGESTING,
                   RunStatusEnum.ANALYZING, RunStatusEnum.SYNTHESIZING):
        validate_transition(status, RunStatusEnum.FAILED)


def test_invalid_transition_completed():
    with pytest.raises(InvalidRunTransition):
        validate_transition(RunStatusEnum.COMPLETED, RunStatusEnum.INGESTING)


def test_invalid_transition_cancelled():
    with pytest.raises(InvalidRunTransition):
        validate_transition(RunStatusEnum.CANCELLED, RunStatusEnum.PENDING)


def test_invalid_transition_failed():
    with pytest.raises(InvalidRunTransition):
        validate_transition(RunStatusEnum.FAILED, RunStatusEnum.PENDING)


def test_invalid_skip_phase():
    with pytest.raises(InvalidRunTransition):
        validate_transition(RunStatusEnum.PENDING, RunStatusEnum.ANALYZING)


def test_invalid_backward_transition():
    with pytest.raises(InvalidRunTransition):
        validate_transition(RunStatusEnum.ANALYZING, RunStatusEnum.INGESTING)


def test_terminal_statuses_have_no_outgoing():
    for status in TERMINAL_STATUSES:
        assert len(VALID_TRANSITIONS[status]) == 0


def test_exception_attributes():
    try:
        validate_transition(RunStatusEnum.COMPLETED, RunStatusEnum.INGESTING)
    except InvalidRunTransition as e:
        assert e.from_status == RunStatusEnum.COMPLETED
        assert e.to_status == RunStatusEnum.INGESTING
