"""Evidence agent tools -- pure functions supporting the evidence tasks.

Each module exposes one aspect of evidence collection:

- ``search_factchecks`` -- Google Fact Check Tools API search and scoring
- ``lookup_domain_sources`` -- domain routing, query derivation, URL formatting

URL fetching is shared via ``swarm_reasoning.agents.web``. Alignment
judgment is performed by the LLM scorer subagent in ``agent.py``; no
deterministic keyword-overlap scorer remains here.
"""
