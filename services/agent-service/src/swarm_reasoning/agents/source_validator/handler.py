"""Source-validator agent handler — URL validation, convergence, citation aggregation.

Phase 2b agent: scans upstream agent streams for cited URLs, validates via HTTP HEAD
with redirect/soft-404 detection, computes source convergence score, and publishes
an aggregated citation list for the synthesizer.
"""

from __future__ import annotations

import logging

import redis.asyncio as aioredis

from swarm_reasoning.activities.run_agent import AgentActivityInput, AgentActivityResult
from swarm_reasoning.agents.fanout_base import ClaimContext, FanoutBase
from swarm_reasoning.agents.source_validator.aggregator import CitationAggregator
from swarm_reasoning.agents.source_validator.convergence import ConvergenceAnalyzer
from swarm_reasoning.agents.source_validator.extractor import LinkExtractor
from swarm_reasoning.agents.source_validator.validator import UrlValidator
from swarm_reasoning.config import RedisConfig
from swarm_reasoning.models.observation import ObservationCode, ValueType
from swarm_reasoning.stream.base import ReasoningStream

logger = logging.getLogger(__name__)

AGENT_NAME = "source-validator"


class SourceValidatorHandler(FanoutBase):
    """Orchestrates link extraction, URL validation, convergence, and citation aggregation."""

    AGENT_NAME = AGENT_NAME

    def __init__(self, redis_config: RedisConfig | None = None) -> None:
        super().__init__(redis_config)
        self._extractor = LinkExtractor()
        self._validator = UrlValidator()
        self._convergence = ConvergenceAnalyzer()
        self._aggregator = CitationAggregator(self._convergence)
        self._cross_agent_data: dict = {}

    def _primary_code(self) -> ObservationCode:
        return ObservationCode.SOURCE_CONVERGENCE_SCORE

    def _primary_value_type(self) -> ValueType:
        return ValueType.NM

    def _timeout_value(self) -> str:
        return "0.0"

    async def run(self, input: AgentActivityInput) -> AgentActivityResult:
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
        # 1. Extract URLs from cross-agent data
        extracted = self._extractor.extract_urls(self._cross_agent_data)

        if not extracted:
            await self._publish_progress(redis_client, run_id, "No source URLs found")
            # Publish empty results
            await self._publish_obs(
                stream,
                sk,
                run_id,
                code=ObservationCode.SOURCE_CONVERGENCE_SCORE,
                value="0.0",
                value_type=ValueType.NM,
                units="score",
                reference_range="0.0-1.0",
            )
            await self._publish_obs(
                stream,
                sk,
                run_id,
                code=ObservationCode.CITATION_LIST,
                value=CitationAggregator.to_citation_list_json([]),
                value_type=ValueType.TX,
            )
            return

        # Publish SOURCE_EXTRACTED_URL for each unique URL
        for eu in extracted:
            await self._publish_obs(
                stream,
                sk,
                run_id,
                code=ObservationCode.SOURCE_EXTRACTED_URL,
                value=eu.url,
                value_type=ValueType.ST,
            )

        # 2. Validate URLs concurrently
        urls_to_validate = [eu.url for eu in extracted]
        total = len(urls_to_validate)
        await self._publish_progress(redis_client, run_id, "Validating source URLs...")

        validations = await self._validator.validate_all(urls_to_validate)

        # Publish SOURCE_VALIDATION_STATUS for each URL
        for url, result in validations.items():
            await self._publish_obs(
                stream,
                sk,
                run_id,
                code=ObservationCode.SOURCE_VALIDATION_STATUS,
                value=result.status.to_cwe(),
                value_type=ValueType.CWE,
            )

        await self._publish_progress(
            redis_client, run_id, f"Validated {len(validations)}/{total} URLs"
        )

        # 3. Compute source convergence
        score = self._convergence.compute_convergence_score(extracted)
        convergence_groups = self._convergence.get_convergence_groups(extracted)

        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.SOURCE_CONVERGENCE_SCORE,
            value=str(score),
            value_type=ValueType.NM,
            units="score",
            reference_range="0.0-1.0",
        )

        # 4. Aggregate citations
        citations = self._aggregator.aggregate(extracted, validations, convergence_groups)
        json_str = CitationAggregator.to_citation_list_json(citations)

        await self._publish_obs(
            stream,
            sk,
            run_id,
            code=ObservationCode.CITATION_LIST,
            value=json_str,
            value_type=ValueType.TX,
        )

        count = len(citations)
        if count > 0:
            await self._publish_progress(
                redis_client, run_id, f"Aggregated {count} source citations"
            )
        else:
            await self._publish_progress(redis_client, run_id, "No source citations found")


# Agent registry integration
_HANDLER: SourceValidatorHandler | None = None


def get_handler() -> SourceValidatorHandler:
    global _HANDLER
    if _HANDLER is None:
        _HANDLER = SourceValidatorHandler()
    return _HANDLER
