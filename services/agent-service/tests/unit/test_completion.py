"""Tests for the CompletionRegister."""

import pytest

from swarm_reasoning.completion.register import CompletionRegister


@pytest.fixture
def register():
    r = CompletionRegister()
    r.register_agents(["agent-a", "agent-b", "agent-c"])
    return r


def test_register_agents(register):
    assert set(register.all_agents) == {"agent-a", "agent-b", "agent-c"}


def test_initial_state_is_none(register):
    assert register.get_status("agent-a") is None
    assert not register.is_agent_complete("agent-a")


def test_mark_complete(register):
    register.mark_complete("agent-a", "F")
    assert register.is_agent_complete("agent-a")
    assert register.get_status("agent-a") == "F"


def test_mark_complete_with_x(register):
    register.mark_complete("agent-b", "X")
    assert register.get_status("agent-b") == "X"
    assert register.is_agent_complete("agent-b")


def test_mark_complete_invalid_status(register):
    with pytest.raises(ValueError, match="Terminal status must be"):
        register.mark_complete("agent-a", "P")


def test_mark_complete_idempotent(register):
    register.mark_complete("agent-a", "F")
    register.mark_complete("agent-a", "F")  # No error
    assert register.get_status("agent-a") == "F"


def test_is_phase_complete(register):
    assert not register.is_phase_complete(["agent-a", "agent-b"])
    register.mark_complete("agent-a", "F")
    assert not register.is_phase_complete(["agent-a", "agent-b"])
    register.mark_complete("agent-b", "F")
    assert register.is_phase_complete(["agent-a", "agent-b"])


def test_get_incomplete_agents(register):
    register.mark_complete("agent-a", "F")
    incomplete = register.get_incomplete_agents()
    assert set(incomplete) == {"agent-b", "agent-c"}


def test_complete_count(register):
    assert register.complete_count == 0
    register.mark_complete("agent-a", "F")
    assert register.complete_count == 1
    register.mark_complete("agent-b", "X")
    assert register.complete_count == 2


def test_reset(register):
    register.mark_complete("agent-a", "F")
    register.reset()
    assert register.all_agents == []
    assert register.complete_count == 0


def test_merge_from_rebuild(register):
    rebuild_data = {"agent-a": "F", "agent-c": "X"}
    register.merge_from_rebuild(rebuild_data)
    assert register.get_status("agent-a") == "F"
    assert register.get_status("agent-b") is None
    assert register.get_status("agent-c") == "X"


def test_merge_from_rebuild_ignores_invalid():
    r = CompletionRegister()
    r.register_agents(["agent-a"])
    r.merge_from_rebuild({"agent-a": "P"})  # P is not terminal
    assert r.get_status("agent-a") is None


def test_register_agent_idempotent():
    r = CompletionRegister()
    r.register_agent("agent-a")
    r.mark_complete("agent-a", "F")
    r.register_agent("agent-a")  # Should not reset status
    assert r.get_status("agent-a") == "F"
