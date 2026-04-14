"""Unit tests for synthesizer observation resolution."""

from __future__ import annotations

import pytest

from swarm_reasoning.agents.synthesizer.resolver import UPSTREAM_AGENTS, ObservationResolver
from swarm_reasoning.models.observation import Observation, ObservationCode, ValueType
from swarm_reasoning.models.stream import ObsMessage, Phase, StartMessage, StopMessage


class FakeStream:
    """In-memory stream for testing resolution."""

    def __init__(self):
        self.streams: dict[str, list] = {}

    def add_obs(
        self,
        run_id: str,
        agent: str,
        seq: int,
        code: str,
        value: str,
        value_type: str,
        status: str = "F",
        units: str | None = None,
        reference_range: str | None = None,
        method: str | None = None,
        note: str | None = None,
    ):
        key = f"reasoning:{run_id}:{agent}"
        if key not in self.streams:
            self.streams[key] = []
        obs = Observation(
            runId=run_id,
            agent=agent,
            seq=seq,
            code=ObservationCode(code),
            value=value,
            valueType=ValueType(value_type),
            status=status,
            timestamp="2026-01-01T00:00:00Z",
            units=units,
            referenceRange=reference_range,
            method=method,
            note=note,
        )
        self.streams[key].append(ObsMessage(observation=obs))

    def add_start(self, run_id: str, agent: str):
        key = f"reasoning:{run_id}:{agent}"
        if key not in self.streams:
            self.streams[key] = []
        self.streams[key].append(
            StartMessage(
                runId=run_id,
                agent=agent,
                phase=Phase.FANOUT,
                timestamp="2026-01-01T00:00:00Z",
            )
        )

    def add_stop(self, run_id: str, agent: str, count: int = 1):
        key = f"reasoning:{run_id}:{agent}"
        if key not in self.streams:
            self.streams[key] = []
        self.streams[key].append(
            StopMessage(
                runId=run_id,
                agent=agent,
                finalStatus="F",
                observationCount=count,
                timestamp="2026-01-01T00:00:00Z",
            )
        )

    async def read_range(self, stream_key: str, start: str = "-", end: str = "+"):
        return self.streams.get(stream_key, [])

    async def close(self):
        pass


@pytest.fixture
def stream():
    return FakeStream()


@pytest.fixture
def resolver():
    return ObservationResolver()


class TestResolutionCOverF:
    """C-status wins over F-status for the same (agent, code) pair."""

    @pytest.mark.asyncio
    async def test_c_wins_over_f(self, stream, resolver):
        stream.add_obs(
            "run1",
            "domain-evidence",
            seq=1,
            code="DOMAIN_EVIDENCE_ALIGNMENT",
            value="SUPPORTS^Supports^FCK",
            value_type="CWE",
            status="F",
        )
        stream.add_obs(
            "run1",
            "domain-evidence",
            seq=2,
            code="DOMAIN_EVIDENCE_ALIGNMENT",
            value="CONTRADICTS^Contradicts^FCK",
            value_type="CWE",
            status="C",
        )

        result = await resolver.resolve("run1", stream)
        obs = result.find("DOMAIN_EVIDENCE_ALIGNMENT")
        assert obs is not None
        assert obs.value == "CONTRADICTS^Contradicts^FCK"
        assert obs.resolution_method == "LATEST_C"
        assert obs.seq == 2

    @pytest.mark.asyncio
    async def test_latest_c_by_seq(self, stream, resolver):
        stream.add_obs(
            "run1",
            "domain-evidence",
            seq=5,
            code="DOMAIN_EVIDENCE_ALIGNMENT",
            value="SUPPORTS^Supports^FCK",
            value_type="CWE",
            status="C",
        )
        stream.add_obs(
            "run1",
            "domain-evidence",
            seq=10,
            code="DOMAIN_EVIDENCE_ALIGNMENT",
            value="PARTIAL^Partial^FCK",
            value_type="CWE",
            status="C",
        )

        result = await resolver.resolve("run1", stream)
        obs = result.find("DOMAIN_EVIDENCE_ALIGNMENT")
        assert obs is not None
        assert obs.value == "PARTIAL^Partial^FCK"
        assert obs.seq == 10


class TestResolutionLatestF:
    """Latest F-status is used when no C-status exists."""

    @pytest.mark.asyncio
    async def test_latest_f_by_seq(self, stream, resolver):
        stream.add_obs(
            "run1",
            "claimreview-matcher",
            seq=5,
            code="CLAIMREVIEW_VERDICT",
            value="TRUE^True^POLITIFACT",
            value_type="CWE",
            status="F",
        )
        stream.add_obs(
            "run1",
            "claimreview-matcher",
            seq=8,
            code="CLAIMREVIEW_VERDICT",
            value="FALSE^False^POLITIFACT",
            value_type="CWE",
            status="F",
        )

        result = await resolver.resolve("run1", stream)
        obs = result.find("CLAIMREVIEW_VERDICT")
        assert obs is not None
        assert obs.value == "FALSE^False^POLITIFACT"
        assert obs.resolution_method == "LATEST_F"
        assert obs.seq == 8

    @pytest.mark.asyncio
    async def test_single_f(self, stream, resolver):
        stream.add_obs(
            "run1",
            "claimreview-matcher",
            seq=5,
            code="CLAIMREVIEW_VERDICT",
            value="TRUE^True^POLITIFACT",
            value_type="CWE",
            status="F",
        )

        result = await resolver.resolve("run1", stream)
        obs = result.find("CLAIMREVIEW_VERDICT")
        assert obs is not None
        assert obs.resolution_method == "LATEST_F"


class TestExclusion:
    """X-status excluded silently; P-status excluded with warning."""

    @pytest.mark.asyncio
    async def test_x_excluded(self, stream, resolver):
        stream.add_obs(
            "run1",
            "domain-evidence",
            seq=9,
            code="DOMAIN_CONFIDENCE",
            value="0.8",
            value_type="NM",
            status="X",
            units="score",
            reference_range="0.0-1.0",
        )

        result = await resolver.resolve("run1", stream)
        assert result.find("DOMAIN_CONFIDENCE") is None
        assert result.synthesis_signal_count == 0
        assert len(result.excluded_observations) == 1
        assert len(result.warnings) == 0

    @pytest.mark.asyncio
    async def test_p_excluded_with_warning(self, stream, resolver):
        stream.add_obs(
            "run1",
            "coverage-left",
            seq=3,
            code="COVERAGE_FRAMING",
            value="SUPPORTIVE^Supportive^FCK",
            value_type="CWE",
            status="P",
        )

        result = await resolver.resolve("run1", stream)
        assert result.find("COVERAGE_FRAMING", agent="coverage-left") is None
        assert len(result.warnings) == 1
        assert "P-status" in result.warnings[0]
        assert "coverage-left" in result.warnings[0]

    @pytest.mark.asyncio
    async def test_f_preferred_over_p_and_x(self, stream, resolver):
        """F observation should still be picked even alongside P and X observations."""
        stream.add_obs(
            "run1",
            "domain-evidence",
            seq=1,
            code="DOMAIN_CONFIDENCE",
            value="0.5",
            value_type="NM",
            status="P",
            units="score",
            reference_range="0.0-1.0",
        )
        stream.add_obs(
            "run1",
            "domain-evidence",
            seq=2,
            code="DOMAIN_CONFIDENCE",
            value="0.7",
            value_type="NM",
            status="F",
            units="score",
            reference_range="0.0-1.0",
        )
        stream.add_obs(
            "run1",
            "domain-evidence",
            seq=3,
            code="DOMAIN_CONFIDENCE",
            value="0.9",
            value_type="NM",
            status="X",
            units="score",
            reference_range="0.0-1.0",
        )

        result = await resolver.resolve("run1", stream)
        obs = result.find("DOMAIN_CONFIDENCE")
        assert obs is not None
        assert obs.value == "0.7"
        assert obs.resolution_method == "LATEST_F"


class TestSignalCount:
    """SYNTHESIS_SIGNAL_COUNT matches resolved pair count."""

    @pytest.mark.asyncio
    async def test_count_accuracy(self, stream, resolver):
        # 3 different (agent, code) pairs
        stream.add_obs(
            "run1",
            "domain-evidence",
            seq=1,
            code="DOMAIN_EVIDENCE_ALIGNMENT",
            value="SUPPORTS^Supports^FCK",
            value_type="CWE",
            status="F",
        )
        stream.add_obs(
            "run1",
            "domain-evidence",
            seq=2,
            code="DOMAIN_CONFIDENCE",
            value="0.9",
            value_type="NM",
            status="F",
            units="score",
            reference_range="0.0-1.0",
        )
        stream.add_obs(
            "run1",
            "validation",
            seq=1,
            code="BLINDSPOT_SCORE",
            value="0.0",
            value_type="NM",
            status="F",
            units="score",
            reference_range="0.0-1.0",
        )

        result = await resolver.resolve("run1", stream)
        assert result.synthesis_signal_count == 3
        assert len(result.observations) == 3


class TestValidationIncluded:
    """Validation agent observations are included in resolution."""

    @pytest.mark.asyncio
    async def test_source_convergence_resolved(self, stream, resolver):
        stream.add_obs(
            "run1",
            "validation",
            seq=1,
            code="SOURCE_CONVERGENCE_SCORE",
            value="0.75",
            value_type="NM",
            status="F",
            units="score",
            reference_range="0.0-1.0",
        )

        result = await resolver.resolve("run1", stream)
        obs = result.find("SOURCE_CONVERGENCE_SCORE")
        assert obs is not None
        assert obs.value == "0.75"
        assert obs.agent == "validation"

    @pytest.mark.asyncio
    async def test_citation_list_resolved(self, stream, resolver):
        long_value = '{"citations":' + " " * 200 + "[]}"
        stream.add_obs(
            "run1",
            "validation",
            seq=2,
            code="CITATION_LIST",
            value=long_value,
            value_type="TX",
            status="F",
        )

        result = await resolver.resolve("run1", stream)
        obs = result.find("CITATION_LIST")
        assert obs is not None


class TestMixedStatuses:
    """Resolution with mix of C, F, X, P for the same (agent, code) pair."""

    @pytest.mark.asyncio
    async def test_c_wins_in_mixed(self, stream, resolver):
        stream.add_obs(
            "run1",
            "domain-evidence",
            seq=1,
            code="DOMAIN_EVIDENCE_ALIGNMENT",
            value="SUPPORTS^Supports^FCK",
            value_type="CWE",
            status="P",
        )
        stream.add_obs(
            "run1",
            "domain-evidence",
            seq=5,
            code="DOMAIN_EVIDENCE_ALIGNMENT",
            value="PARTIAL^Partial^FCK",
            value_type="CWE",
            status="F",
        )
        stream.add_obs(
            "run1",
            "domain-evidence",
            seq=10,
            code="DOMAIN_EVIDENCE_ALIGNMENT",
            value="CONTRADICTS^Contradicts^FCK",
            value_type="CWE",
            status="C",
        )
        stream.add_obs(
            "run1",
            "domain-evidence",
            seq=15,
            code="DOMAIN_EVIDENCE_ALIGNMENT",
            value="ABSENT^Absent^FCK",
            value_type="CWE",
            status="X",
        )

        result = await resolver.resolve("run1", stream)
        obs = result.find("DOMAIN_EVIDENCE_ALIGNMENT")
        assert obs is not None
        assert obs.value == "CONTRADICTS^Contradicts^FCK"
        assert obs.resolution_method == "LATEST_C"


class TestEmptyStreams:
    """Handle empty or missing streams gracefully."""

    @pytest.mark.asyncio
    async def test_no_observations(self, stream, resolver):
        result = await resolver.resolve("run1", stream)
        assert result.synthesis_signal_count == 0
        assert len(result.observations) == 0

    @pytest.mark.asyncio
    async def test_only_start_stop(self, stream, resolver):
        stream.add_start("run1", "domain-evidence")
        stream.add_stop("run1", "domain-evidence", count=0)

        result = await resolver.resolve("run1", stream)
        assert result.synthesis_signal_count == 0


class TestUpstreamAgentCount:
    """Verify all 9 upstream agents are read."""

    def test_upstream_agents_list(self):
        assert len(UPSTREAM_AGENTS) == 9
        assert "synthesizer" not in UPSTREAM_AGENTS
        assert "validation" in UPSTREAM_AGENTS
