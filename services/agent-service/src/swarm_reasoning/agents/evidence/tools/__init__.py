"""Evidence agent tools -- pure functions for evidence gathering.

Each module exposes one aspect of evidence collection:

- ``search_factchecks`` -- Google Fact Check Tools API search and scoring
- ``lookup_domain_sources`` -- domain routing, query derivation, URL formatting
- ``score_evidence`` -- claim alignment scoring and confidence computation

URL fetching is shared via ``swarm_reasoning.agents.web``.

Callers import the submodules directly; the StateGraph nodes in
``agents/evidence/agent.py`` wrap these pure functions without an LLM.
"""
