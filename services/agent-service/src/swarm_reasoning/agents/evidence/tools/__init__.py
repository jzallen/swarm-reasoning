"""Evidence agent tools -- pure functions for evidence gathering.

Each module exposes one aspect of evidence collection:

- ``search_factchecks`` -- Google Fact Check Tools API search and scoring
- ``lookup_domain_sources`` -- domain routing, query derivation, URL formatting
- ``fetch_source_content`` -- HTTP content fetching and relevance checking
- ``score_evidence`` -- claim alignment scoring and confidence computation

Callers import the submodules directly so the ``@tool`` definitions in
``agents/evidence/agent.py`` can import lazily inside their bodies.
"""
