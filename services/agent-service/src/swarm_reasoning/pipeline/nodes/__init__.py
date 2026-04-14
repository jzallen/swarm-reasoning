"""Pipeline node implementations (M1-M5).

Each node is an async function accepting PipelineState + RunnableConfig
and returning a dict of state updates for LangGraph to merge.
"""

from swarm_reasoning.pipeline.nodes.intake import intake_node

__all__ = ["intake_node"]
