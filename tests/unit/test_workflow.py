"""Tests for ClaimVerificationWorkflow contracts and constants."""

from swarm_reasoning.temporal.workflow import (
    _PHASE_1_AGENTS,
    _PHASE_2A_AGENTS,
    _PHASE_2B_AGENT,
    _PHASE_3_AGENTS,
    CHECK_WORTHINESS_THRESHOLD,
    ClaimVerificationWorkflow,
    RunStatus,
    WorkflowInput,
    WorkflowResult,
)


class TestRunStatus:
    def test_all_statuses_defined(self):
        assert RunStatus.PENDING == "pending"
        assert RunStatus.INGESTING == "ingesting"
        assert RunStatus.ANALYZING == "analyzing"
        assert RunStatus.SYNTHESIZING == "synthesizing"
        assert RunStatus.COMPLETED == "completed"
        assert RunStatus.CANCELLED == "cancelled"
        assert RunStatus.FAILED == "failed"


class TestWorkflowInput:
    def test_required_fields(self):
        inp = WorkflowInput(
            run_id="run-1",
            session_id="sess-1",
            claim_text="Test claim",
        )
        assert inp.run_id == "run-1"
        assert inp.session_id == "sess-1"
        assert inp.claim_text == "Test claim"
        assert inp.source_url is None
        assert inp.source_date is None

    def test_optional_fields(self):
        inp = WorkflowInput(
            run_id="run-2",
            session_id="sess-2",
            claim_text="Claim",
            source_url="https://example.com",
            source_date="2026-01-01",
        )
        assert inp.source_url == "https://example.com"
        assert inp.source_date == "2026-01-01"


class TestWorkflowResult:
    def test_completed_result(self):
        result = WorkflowResult(
            run_id="run-1",
            status=RunStatus.COMPLETED,
            phase_results={
                "ingestion-agent": "F",
                "synthesizer": "F",
            },
        )
        assert result.status == "completed"
        assert result.phase_results["ingestion-agent"] == "F"

    def test_cancelled_result(self):
        result = WorkflowResult(
            run_id="run-1",
            status=RunStatus.CANCELLED,
            phase_results={"ingestion-agent": "F", "claim-detector": "F"},
        )
        assert result.status == "cancelled"
        assert len(result.phase_results) == 2


class TestCheckWorthinessThreshold:
    def test_threshold_value(self):
        assert CHECK_WORTHINESS_THRESHOLD == 0.4


class TestPhaseAgentAssignment:
    def test_phase_1_agents(self):
        assert _PHASE_1_AGENTS == [
            "ingestion-agent",
            "claim-detector",
            "entity-extractor",
        ]

    def test_phase_2a_agents(self):
        assert set(_PHASE_2A_AGENTS) == {
            "claimreview-matcher",
            "coverage-left",
            "coverage-center",
            "coverage-right",
            "domain-evidence",
        }
        assert len(_PHASE_2A_AGENTS) == 5

    def test_phase_2b_agent(self):
        assert _PHASE_2B_AGENT == "source-validator"

    def test_phase_3_agents(self):
        assert _PHASE_3_AGENTS == [
            "blindspot-detector",
            "synthesizer",
        ]

    def test_all_11_agents_covered(self):
        all_agents = (
            set(_PHASE_1_AGENTS) | set(_PHASE_2A_AGENTS) | {_PHASE_2B_AGENT} | set(_PHASE_3_AGENTS)
        )
        assert len(all_agents) == 11

    def test_phase_1_is_sequential(self):
        """Phase 1 order matters: ingestion -> claim-detector -> entity-extractor."""
        assert _PHASE_1_AGENTS[0] == "ingestion-agent"
        assert _PHASE_1_AGENTS[1] == "claim-detector"
        assert _PHASE_1_AGENTS[2] == "entity-extractor"

    def test_phase_3_is_sequential(self):
        """Phase 3 order matters: blindspot-detector -> synthesizer."""
        assert _PHASE_3_AGENTS[0] == "blindspot-detector"
        assert _PHASE_3_AGENTS[1] == "synthesizer"


class TestCheckWorthinessGate:
    def test_low_score_should_cancel(self):
        from swarm_reasoning.temporal.activities import AgentActivityOutput

        output = AgentActivityOutput(
            agent_name="claim-detector",
            terminal_status="F",
            observation_count=2,
            duration_ms=100,
            check_worthiness_score=0.3,
        )
        assert ClaimVerificationWorkflow._should_cancel(output) is True

    def test_high_score_should_not_cancel(self):
        from swarm_reasoning.temporal.activities import AgentActivityOutput

        output = AgentActivityOutput(
            agent_name="claim-detector",
            terminal_status="F",
            observation_count=2,
            duration_ms=100,
            check_worthiness_score=0.7,
        )
        assert ClaimVerificationWorkflow._should_cancel(output) is False

    def test_threshold_boundary_should_not_cancel(self):
        from swarm_reasoning.temporal.activities import AgentActivityOutput

        output = AgentActivityOutput(
            agent_name="claim-detector",
            terminal_status="F",
            observation_count=2,
            duration_ms=100,
            check_worthiness_score=0.4,
        )
        assert ClaimVerificationWorkflow._should_cancel(output) is False

    def test_none_score_should_not_cancel(self):
        from swarm_reasoning.temporal.activities import AgentActivityOutput

        output = AgentActivityOutput(
            agent_name="claim-detector",
            terminal_status="F",
            observation_count=2,
            duration_ms=100,
            check_worthiness_score=None,
        )
        assert ClaimVerificationWorkflow._should_cancel(output) is False
