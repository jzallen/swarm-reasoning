"""Tests for activity contracts: AgentActivityInput, AgentActivityOutput, and agent registry."""

from swarm_reasoning.temporal.activities import (
    AGENT_NAMES,
    WORKFLOW_TASK_QUEUE,
    AgentActivityInput,
    AgentActivityOutput,
    task_queue_for_agent,
)


class TestAgentActivityInput:
    def test_required_fields(self):
        inp = AgentActivityInput(
            run_id="run-1",
            claim_text="Test claim",
            agent_name="ingestion-agent",
            phase="ingestion",
        )
        assert inp.run_id == "run-1"
        assert inp.claim_text == "Test claim"
        assert inp.agent_name == "ingestion-agent"
        assert inp.phase == "ingestion"
        assert inp.source_url is None
        assert inp.source_date is None

    def test_optional_fields(self):
        inp = AgentActivityInput(
            run_id="run-2",
            claim_text="Another claim",
            agent_name="coverage-left",
            phase="fanout",
            source_url="https://example.com",
            source_date="2026-01-01",
        )
        assert inp.source_url == "https://example.com"
        assert inp.source_date == "2026-01-01"

    def test_all_phases(self):
        for phase in ("ingestion", "fanout", "synthesis"):
            inp = AgentActivityInput(run_id="r", claim_text="c", agent_name="a", phase=phase)
            assert inp.phase == phase


class TestAgentActivityOutput:
    def test_successful_output(self):
        out = AgentActivityOutput(
            agent_name="synthesizer",
            terminal_status="F",
            observation_count=5,
            duration_ms=1200,
        )
        assert out.agent_name == "synthesizer"
        assert out.terminal_status == "F"
        assert out.observation_count == 5
        assert out.duration_ms == 1200
        assert out.check_worthiness_score is None

    def test_cancelled_output(self):
        out = AgentActivityOutput(
            agent_name="ingestion-agent",
            terminal_status="X",
            observation_count=0,
            duration_ms=50,
        )
        assert out.terminal_status == "X"
        assert out.observation_count == 0

    def test_with_check_worthiness_score(self):
        out = AgentActivityOutput(
            agent_name="claim-detector",
            terminal_status="F",
            observation_count=2,
            duration_ms=800,
            check_worthiness_score=0.85,
        )
        assert out.check_worthiness_score == 0.85


class TestAgentRegistry:
    def test_eleven_agents(self):
        assert len(AGENT_NAMES) == 11

    def test_known_agents_present(self):
        expected = {
            "ingestion-agent",
            "claim-detector",
            "entity-extractor",
            "claimreview-matcher",
            "coverage-left",
            "coverage-center",
            "coverage-right",
            "domain-evidence",
            "source-validator",
            "blindspot-detector",
            "synthesizer",
        }
        assert set(AGENT_NAMES) == expected

    def test_task_queue_format(self):
        assert task_queue_for_agent("ingestion-agent") == "agent:ingestion-agent"
        assert task_queue_for_agent("synthesizer") == "agent:synthesizer"

    def test_workflow_task_queue(self):
        assert WORKFLOW_TASK_QUEUE == "claim-verification"

    def test_all_agents_have_unique_queues(self):
        queues = [task_queue_for_agent(a) for a in AGENT_NAMES]
        assert len(queues) == len(set(queues))
