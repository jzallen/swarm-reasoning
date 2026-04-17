"""Messaging helpers shared by all agents.

Encapsulates the ``get_stream_writer()`` + event-dict construction so every
message emitted from a tool shares the same shape and transport.
"""

from __future__ import annotations

from langgraph.config import get_stream_writer


def share_progress(message: str) -> None:
    """Emit a ``progress`` event to the current LangGraph stream writer."""
    writer = get_stream_writer()
    writer({"type": "progress", "message": message})
