"""Tests for TemporalConfig."""

from swarm_reasoning.temporal.config import TemporalConfig


class TestTemporalConfig:
    def test_defaults(self):
        cfg = TemporalConfig()
        assert cfg.address == "localhost:7233"
        assert cfg.namespace == "swarm-reasoning"

    def test_explicit_values(self):
        cfg = TemporalConfig(address="temporal:7233", namespace="test-ns")
        assert cfg.address == "temporal:7233"
        assert cfg.namespace == "test-ns"

    def test_env_override_address(self, monkeypatch):
        monkeypatch.setenv("TEMPORAL_ADDRESS", "remote:7233")
        cfg = TemporalConfig()
        assert cfg.address == "remote:7233"

    def test_env_override_namespace(self, monkeypatch):
        monkeypatch.setenv("TEMPORAL_NAMESPACE", "prod-ns")
        cfg = TemporalConfig()
        assert cfg.namespace == "prod-ns"

    def test_explicit_overrides_env(self, monkeypatch):
        monkeypatch.setenv("TEMPORAL_ADDRESS", "from-env:7233")
        cfg = TemporalConfig(address="explicit:7233")
        assert cfg.address == "explicit:7233"
