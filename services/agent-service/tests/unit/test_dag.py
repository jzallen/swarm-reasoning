"""Tests for the three-phase DAG definition."""

from swarm_reasoning.workflows.dag import ALL_AGENTS, DAG, PhaseMode


def test_dag_has_three_phases():
    assert len(DAG) == 3


def test_total_agent_count_is_10():
    assert len(ALL_AGENTS) == 10


def test_no_duplicate_agents():
    assert len(ALL_AGENTS) == len(set(ALL_AGENTS))


def test_phase_1_ingestion_sequential():
    p = DAG[0]
    assert p.id == "1"
    assert p.name == "ingestion"
    assert p.mode == PhaseMode.SEQUENTIAL
    assert p.agents == ("ingestion-agent", "claim-detector", "entity-extractor")


def test_phase_2_fanout_parallel():
    p = DAG[1]
    assert p.id == "2"
    assert p.name == "fanout"
    assert p.mode == PhaseMode.PARALLEL
    assert len(p.agents) == 5
    assert "claimreview-matcher" in p.agents
    assert "coverage-left" in p.agents
    assert "coverage-center" in p.agents
    assert "coverage-right" in p.agents
    assert "domain-evidence" in p.agents


def test_phase_3_synthesis_sequential():
    p = DAG[2]
    assert p.id == "3"
    assert p.name == "synthesis"
    assert p.mode == PhaseMode.SEQUENTIAL
    assert p.agents == ("validation", "synthesizer")


def test_all_agents_tuple():
    expected = (
        "ingestion-agent", "claim-detector", "entity-extractor",
        "claimreview-matcher", "coverage-left", "coverage-center",
        "coverage-right", "domain-evidence",
        "validation", "synthesizer",
    )
    assert ALL_AGENTS == expected
