"""Intake agent tools.

Each submodule provides a single intake step (fetch, decompose, classify,
extract). Tool files export only functions and exceptions; constants are
accessed via ``get_<name>()`` getters.

Importers should reach into the specific submodule rather than this
package, so that tool-definition imports are colocated with each
``@tool``-decorated function in ``agent.py``.
"""
