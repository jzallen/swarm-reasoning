"""Unit tests for stream key generation."""

from swarm_reasoning.stream.key import stream_key


class TestStreamKey:
    def test_format(self):
        result = stream_key("claim-42-run-001", "coverage-left")
        assert result == "reasoning:claim-42-run-001:coverage-left"

    def test_different_agents(self):
        k1 = stream_key("run-001", "agent-a")
        k2 = stream_key("run-001", "agent-b")
        assert k1 != k2
        assert k1.startswith("reasoning:run-001:")
