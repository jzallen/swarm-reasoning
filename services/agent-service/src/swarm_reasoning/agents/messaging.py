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


def share_heartbeat(agent: str) -> None:
    """Emit a ``heartbeat`` event to the current LangGraph stream writer.

    Used inside long-running tools so the pipeline node wrapper can keep
    the Temporal activity heartbeat fresh without coupling tools to
    PipelineContext.
    """
    writer = get_stream_writer()
    writer({"type": "heartbeat", "agent": agent})
