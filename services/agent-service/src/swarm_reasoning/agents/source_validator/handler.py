"""Source-validator agent handler — URL validation, convergence, citation aggregation.

Phase 2b agent: scans upstream agent streams for cited URLs, validates via HTTP HEAD
with redirect/soft-404 detection, computes source convergence score, and publishes
an aggregated citation list for the synthesizer.

Delegates to @tool definitions (ADR-004) for observation publishing.
"""

from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis

from swarm_reasoning.activities.run_agent import AgentActivityInput, AgentActivityOutput
from swarm_reasoning.agents._utils import register_handler
from swarm_reasoning.agents.fanout_base import ClaimContext, FanoutBase
from swarm_reasoning.agents.source_validator.aggregator import CitationAggregator
from swarm_reasoning.agents.source_validator.tools.aggregate import aggregate_citations
from swarm_reasoning.agents.source_validator.tools.convergence import compute_convergence_score
from swarm_reasoning.agents.source_validator.tools.extract import extract_urls
from swarm_reasoning.agents.source_validator.tools.validate import validate_urls
from swarm_reasoning.agents.tool_runtime import AgentContext
from swarm_reasoning.config import RedisConfig
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.stream.base import ReasoningStream

logger = logging.getLogger(__name__)

AGENT_NAME = "source-validator"


def _serialize_extracted_urls(cross_agent_data: dict) -> str:
    """Serialize cross-agent URL data for tool consumption."""
    return json.dumps(cross_agent_data)


@register_handler("source-validator")
class SourceValidatorHandler(FanoutBase):
    """Orchestrates link extraction, URL validation, convergence, and citation aggregation.

    Delegates to @tool definitions for each step, which publish observations
    via AgentContext (ADR-004).
    """

    AGENT_NAME = AGENT_NAME

    def __init__(self, redis_config: RedisConfig | None = None) -> None:
        super().__init__(redis_config)
        self._cross_agent_data: dict = {}

    def _primary_code(self) -> ObservationCode:
        return ObservationCode.SOURCE_CONVERGENCE_SCORE

    def _primary_value_type(self) -> ValueType:
        return ValueType.NM

    def _timeout_value(self) -> str:
        return "0.0"

    async def run(self, input: AgentActivityInput) -> AgentActivityOutput:
        """Override to extract cross_agent_data before running base flow."""
        self._cross_agent_data = input.cross_agent_data or {}
        return await super().run(input)

    async def _load_upstream_context(self, stream: ReasoningStream, run_id: str) -> ClaimContext:
        """Source-validator uses cross_agent_data; skip Phase 1 context loading."""
        return ClaimContext()

    async def _execute(
        self,
        stream: ReasoningStream,
        redis_client: aioredis.Redis,
        run_id: str,
        sk: str,
        context: ClaimContext,
    ) -> None:
        # Create AgentContext for @tool observation publishing
        agent_ctx = AgentContext(
            stream=stream,
            redis_client=redis_client,
            run_id=run_id,
            sk=sk,
            agent_name=AGENT_NAME,
        )

        # 1. Extract URLs via @tool
        extract_result_json = await extract_urls.ainvoke({
            "cross_agent_data": _serialize_extracted_urls(self._cross_agent_data),
            "context": agent_ctx,
        })
        extract_result = json.loads(extract_result_json)

        if extract_result["count"] == 0:
            await self._publish_progress(redis_client, run_id, "No source URLs found")
            # Publish empty convergence and citation via tools
            await compute_convergence_score.ainvoke({
                "extracted_urls_json": "[]",
                "context": agent_ctx,
            })
            await aggregate_citations.ainvoke({
                "extracted_urls_json": "[]",
                "validations_json": "{}",
                "convergence_groups_json": "{}",
                "context": agent_ctx,
            })
            self._seq = agent_ctx.seq_counter
            return

        # Rebuild serialized extracted URLs for downstream tools
        # (need full association data, not just URL strings)
        extracted_urls_json = json.dumps(self._build_extracted_url_dicts())

        # 2. Validate URLs via @tool
        urls_to_validate = extract_result["urls"]
        total = len(urls_to_validate)
        await self._publish_progress(redis_client, run_id, "Validating source URLs...")

        validate_result_json = await validate_urls.ainvoke({
            "urls_json": json.dumps(urls_to_validate),
            "context": agent_ctx,
        })
        validations = json.loads(validate_result_json)

        await self._publish_progress(
            redis_client, run_id, f"Validated {len(validations)}/{total} URLs"
        )

        # 3. Compute convergence via @tool
        convergence_result_json = await compute_convergence_score.ainvoke({
            "extracted_urls_json": extracted_urls_json,
            "context": agent_ctx,
        })
        convergence_result = json.loads(convergence_result_json)

        # 4. Aggregate citations via @tool
        aggregate_result_json = await aggregate_citations.ainvoke({
            "extracted_urls_json": extracted_urls_json,
            "validations_json": json.dumps(validations),
            "convergence_groups_json": json.dumps(convergence_result["convergence_groups"]),
            "context": agent_ctx,
        })
        aggregate_result = json.loads(aggregate_result_json)

        count = aggregate_result["count"]
        if count > 0:
            await self._publish_progress(
                redis_client, run_id, f"Aggregated {count} source citations"
            )
        else:
            await self._publish_progress(redis_client, run_id, "No source citations found")

        # Sync seq counter from AgentContext to FanoutBase for STOP message
        self._seq = agent_ctx.seq_counter

    def _build_extracted_url_dicts(self) -> list[dict]:
        """Build serializable extracted URL dicts from cross_agent_data.

        Re-runs extraction to get full association data for downstream tools.
        """
        from swarm_reasoning.agents.source_validator.extractor import LinkExtractor

        extractor = LinkExtractor()
        extracted = extractor.extract_urls(self._cross_agent_data)
        return [
            {
                "url": eu.url,
                "associations": [
                    {
                        "agent": a.agent,
                        "observation_code": a.observation_code,
                        "source_name": a.source_name,
                    }
                    for a in eu.associations
                ],
            }
            for eu in extracted
        ]
