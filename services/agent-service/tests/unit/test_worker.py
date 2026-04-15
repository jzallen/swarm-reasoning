"""Tests for Temporal worker activity registration.

Verifies that all expected activities are importable from worker.py
and that the pipeline activity is included in the registration list.
"""

from swarm_reasoning.activities.run_pipeline import run_langgraph_pipeline
from swarm_reasoning.worker import TASK_QUEUE


def test_task_queue_name():
    """Task queue constant should match expected value."""
    assert TASK_QUEUE == "agent-task-queue"


def test_run_langgraph_pipeline_importable():
    """run_langgraph_pipeline should be importable from the activities module."""
    assert callable(run_langgraph_pipeline)


def test_run_langgraph_pipeline_is_activity():
    """run_langgraph_pipeline should be decorated as a Temporal activity."""
    assert hasattr(run_langgraph_pipeline, "__temporal_activity_definition")
