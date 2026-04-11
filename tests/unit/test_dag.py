"""Tests for the three-phase DAG definition."""

from swarm_reasoning.workflows.dag import ALL_AGENTS, DAG, PhaseMode


def test_dag_has_four_phases():
    assert len(DAG) == 4


def test_total_agent_count_is_11():
    assert len(ALL_AGENTS) == 11


def test_no_duplicate_agents():
    assert len(ALL_AGENTS) == len(set(ALL_AGENTS))


def test_phase_1_ingestion_sequential():
    p = DAG[0]
    assert p.id == "1"
    assert p.name == "ingestion"
    assert p.mode == PhaseMode.SEQUENTIAL
    assert p.agents == ("ingestion-agent", "claim-detector", "entity-extractor")


def test_phase_2a_fanout_parallel():
    p = DAG[1]
    assert p.id == "2a"
    assert p.name == "fanout"
    assert p.mode == PhaseMode.PARALLEL
    assert len(p.agents) == 5
    assert "claimreview-matcher" in p.agents
    assert "coverage-left" in p.agents
    assert "coverage-center" in p.agents
    assert "coverage-right" in p.agents
    assert "domain-evidence" in p.agents


def test_phase_2b_source_validator_sequential():
    p = DAG[2]
    assert p.id == "2b"
    assert p.name == "fanout-validation"
    assert p.mode == PhaseMode.SEQUENTIAL
    assert p.agents == ("source-validator",)


def test_phase_3_synthesis_sequential():
    p = DAG[3]
    assert p.id == "3"
    assert p.name == "synthesis"
    assert p.mode == PhaseMode.SEQUENTIAL
    assert p.agents == ("blindspot-detector", "synthesizer")


def test_source_validator_in_phase_2():
    """Source-validator must be in a Phase 2 sub-phase (not Phase 1 or 3)."""
    phase_2_agents = set(DAG[1].agents) | set(DAG[2].agents)
    assert "source-validator" in phase_2_agents


def test_all_agents_tuple():
    expected = (
        "ingestion-agent", "claim-detector", "entity-extractor",
        "claimreview-matcher", "coverage-left", "coverage-center",
        "coverage-right", "domain-evidence",
        "source-validator",
        "blindspot-detector", "synthesizer",
    )
    assert ALL_AGENTS == expected
