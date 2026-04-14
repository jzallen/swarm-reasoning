"""Validation agent handler — procedural convergence + blindspot pipeline.

Procedural (no LLM) handler that calls compute_convergence_score and
analyze_blindspots in fixed order, passing the convergence score from the
first into the second. Receives cross_agent_data with URL associations and
coverage segments from upstream agents.
"""

from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis

from swarm_reasoning.activities.run_agent import AgentActivityInput, AgentActivityOutput
from swarm_reasoning.agents._utils import register_handler
from swarm_reasoning.agents.blindspot_detector.tools import analyze_blindspots
from swarm_reasoning.agents.fanout_base import ClaimContext, FanoutBase
from swarm_reasoning.agents.source_validator.tools.convergence import compute_convergence_score
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.stream.base import ReasoningStream

logger = logging.getLogger(__name__)

AGENT_NAME = "validation"


@register_handler("validation")
class ValidationHandler(FanoutBase):
    """Orchestrates convergence scoring and blindspot analysis procedurally.

    Calls @tool functions in fixed order:
      1. compute_convergence_score — source convergence across agents
      2. analyze_blindspots — coverage gap analysis with convergence score injected

    No LLM reasoning: tool calls are direct and deterministic.
    """

    AGENT_NAME = AGENT_NAME

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._cross_agent_data: dict = {}

    def _primary_code(self) -> ObservationCode:
        return ObservationCode.BLINDSPOT_SCORE

    def _primary_value_type(self) -> ValueType:
        return ValueType.NM

    def _timeout_value(self) -> str:
        return "1.0"

    async def run(self, input: AgentActivityInput) -> AgentActivityOutput:
        """Extract cross_agent_data before running base flow."""
        self._cross_agent_data = input.cross_agent_data or {}
        return await super().run(input)

    async def _load_upstream_context(self, stream: ReasoningStream, run_id: str) -> ClaimContext:
        """Validation uses cross_agent_data; skip Phase 1 context loading."""
        return ClaimContext()

    async def _execute(
        self,
        stream: ReasoningStream,
        redis_client: aioredis.Redis,
        run_id: str,
        sk: str,
        context: ClaimContext,
    ) -> None:
        agent_ctx = AgentContext(
            stream=stream,
            redis_client=redis_client,
            run_id=run_id,
            sk=sk,
            agent_name=AGENT_NAME,
        )

        # 1. Compute convergence score from URL data
        urls = self._cross_agent_data.get("urls", [])
        extracted_urls_json = json.dumps(urls)

        await self._publish_progress(
            redis_client, run_id, "Computing source convergence..."
        )

        convergence_result_json = await compute_convergence_score.ainvoke({
            "extracted_urls_json": extracted_urls_json,
            "context": agent_ctx,
        })
        convergence_result = json.loads(convergence_result_json)
        convergence_score = convergence_result["score"]

        await self._publish_progress(
            redis_client, run_id, f"Convergence score: {convergence_score:.2f}"
        )

        # 2. Build coverage data with convergence score injected
        coverage = self._cross_agent_data.get("coverage", {})
        coverage_with_score = {
            "coverage": coverage,
            "source_convergence_score": convergence_score,
        }

        await self._publish_progress(
            redis_client, run_id, "Analyzing coverage blindspots..."
        )

        await analyze_blindspots.ainvoke({
            "coverage_data": json.dumps(coverage_with_score),
            "context": agent_ctx,
        })

        # Sync seq counter from AgentContext to FanoutBase for STOP message
        self._seq = agent_ctx.seq_counter
