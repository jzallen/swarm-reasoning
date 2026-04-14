"""Pipeline node implementations (M1+).

Each node is an async function with signature:
    async def node_name(state: PipelineState, config: RunnableConfig) -> dict
"""

from swarm_reasoning.pipeline.nodes.intake import intake_node

__all__ = ["intake_node"]
