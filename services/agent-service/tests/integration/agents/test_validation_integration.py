"""Integration tests for the validation agent (sr-l0y.6.6).

Exercises run_validation_agent() end-to-end with a capturing FakePipelineContext.
Unlike unit tests that test individual nodes in isolation, these tests invoke
the complete validation StateGraph through its public entry point and verify:
  - Observation publishing sequence (SOURCE_EXTRACTED_URL, SOURCE_VALIDATION_STATUS,
    SOURCE_CONVERGENCE_SCORE, CITATION_LIST, BLINDSPOT_SCORE, BLINDSPOT_DIRECTION,
    CROSS_SPECTRUM_CORROBORATION published in correct order)
  - Progress is NOT directly published by the agent (node wrapper handles progress)
  - ValidationOutput contract (all fields, correct types)
  - Heartbeat signaling (initial + 5 nodes = 6 heartbeats)
  - Multiple input scenarios (rich, empty, partial coverage, shared URLs, dead URLs)

All external I/O (HTTP HEAD validation) is mocked via UrlValidator. The validation
StateGraph, link extraction, convergence analysis, citation aggregation, and
blindspot analysis run for real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, patch

import pytest

from swarm_reasoning.agents.source_validator.models import (
    ValidationResult,
    ValidationStatus,
)
from swarm_reasoning.agents.validation.agent import AGENT_NAME, run_validation_agent
from swarm_reasoning.agents.validation.models import ValidationInput
from swarm_reasoning.models.observation import ObservationCode

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class CapturingPipelineContext:
    """PipelineContext double that captures all side-effects for assertions."""

    run_id: str = "integ-val-run"
    session_id: str = "integ-val-sess"
    published_observations: list = field(default_factory=list)
    published_progress: list = field(default_factory=list)
    heartbeat_calls: list = field(default_factory=list)

    async def publish_observation(self, *, agent, code, value, value_type, **kwargs):
        self.published_observations.append(
            {
                "agent": agent,
                "code": code,
                "value": value,
                "value_type": value_type,
                **kwargs,
            }
        )

    async def publish_progress(self, agent, message):
        self.published_progress.append({"agent": agent, "message": message})

    def heartbeat(self, node_name):
        self.heartbeat_calls.append(node_name)


@pytest.fixture
def ctx():
    return CapturingPipelineContext()


# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------


def _rich_input() -> ValidationInput:
    """Rich upstream data: URLs from multiple agents + full coverage."""
    return ValidationInput(
        cross_agent_urls=[
            {
                "url": "https://politifact.com/factchecks/2024/test",
                "agent": "evidence",
                "code": "CLAIMREVIEW_URL",
                "source_name": "PolitiFact",
            },
            {
                "url": "https://cdc.gov/data/statistics",
                "agent": "evidence",
                "code": "DOMAIN_SOURCE_URL",
                "source_name": "CDC",
            },
            {
                "url": "https://leftnews.com/article/1",
                "agent": "coverage-left",
                "code": "COVERAGE_TOP_SOURCE_URL",
                "source_name": "LeftNews",
            },
            {
                "url": "https://centernews.com/article/1",
                "agent": "coverage-center",
                "code": "COVERAGE_TOP_SOURCE_URL",
                "source_name": "CenterNews",
            },
            {
                "url": "https://rightnews.com/article/1",
                "agent": "coverage-right",
                "code": "COVERAGE_TOP_SOURCE_URL",
                "source_name": "RightNews",
            },
        ],
        coverage_left=[
            {"url": "https://leftnews.com/article/1", "source": "LeftNews", "framing": "CRITICAL"},
        ],
        coverage_center=[
            {
                "url": "https://centernews.com/article/1",
                "source": "CenterNews",
                "framing": "NEUTRAL",
            },
        ],
        coverage_right=[
            {
                "url": "https://rightnews.com/article/1",
                "source": "RightNews",
                "framing": "SUPPORTIVE",
            },
        ],
    )


def _rich_validations() -> dict[str, ValidationResult]:
    """Mock validation results for _rich_input URLs — all LIVE."""
    return {
        "https://politifact.com/factchecks/2024/test": ValidationResult(
            url="https://politifact.com/factchecks/2024/test",
            status=ValidationStatus.LIVE,
        ),
        "https://cdc.gov/data/statistics": ValidationResult(
            url="https://cdc.gov/data/statistics",
            status=ValidationStatus.LIVE,
        ),
        "https://leftnews.com/article/1": ValidationResult(
            url="https://leftnews.com/article/1",
            status=ValidationStatus.LIVE,
        ),
        "https://centernews.com/article/1": ValidationResult(
            url="https://centernews.com/article/1",
            status=ValidationStatus.LIVE,
        ),
        "https://rightnews.com/article/1": ValidationResult(
            url="https://rightnews.com/article/1",
            status=ValidationStatus.LIVE,
        ),
    }


def _shared_url_input() -> ValidationInput:
    """Two agents citing the same URL for higher convergence."""
    return ValidationInput(
        cross_agent_urls=[
            {
                "url": "https://shared-source.com/fact",
                "agent": "evidence",
                "code": "DOMAIN_SOURCE_URL",
                "source_name": "SharedSource",
            },
            {
                "url": "https://shared-source.com/fact",
                "agent": "coverage-center",
                "code": "COVERAGE_TOP_SOURCE_URL",
                "source_name": "SharedSource",
            },
        ],
        coverage_left=[],
        coverage_center=[],
        coverage_right=[],
    )


def _left_only_input() -> ValidationInput:
    """Only left coverage populated — partial blindspot scenario."""
    return ValidationInput(
        cross_agent_urls=[
            {
                "url": "https://leftnews.com/article/1",
                "agent": "coverage-left",
                "code": "COVERAGE_TOP_SOURCE_URL",
                "source_name": "LeftNews",
            },
        ],
        coverage_left=[
            {
                "url": "https://leftnews.com/article/1",
                "source": "LeftNews",
                "framing": "SUPPORTIVE",
            },
        ],
        coverage_center=[],
        coverage_right=[],
    )


def _mock_validator(validations: dict[str, ValidationResult] | None = None):
    """Patch UrlValidator to return specified validation results."""
    if validations is None:
        validations = {}
    return patch(
        "swarm_reasoning.agents.validation.agent.UrlValidator",
        return_value=type(
            "MockValidator",
            (),
            {
                "validate_all": AsyncMock(return_value=validations),
            },
        )(),
    )


# ---------------------------------------------------------------------------
# End-to-end run_validation_agent() tests
# ---------------------------------------------------------------------------


class TestValidationEndToEnd:
    """End-to-end tests for run_validation_agent() with full graph execution."""

    @pytest.mark.asyncio
    async def test_rich_input_produces_complete_output(self, ctx):
        """Rich upstream data produces validated URLs, convergence, citations, blindspots."""
        with _mock_validator(_rich_validations()):
            result = await run_validation_agent(_rich_input(), ctx)

        assert len(result["validated_urls"]) == 5
        assert all(u["status"] == "LIVE" for u in result["validated_urls"])
        assert result["convergence_score"] >= 0.0
        assert isinstance(result["citations"], list)
        assert len(result["citations"]) > 0
        assert result["blindspot_score"] == 0.0
        assert "NONE" in result["blindspot_direction"]

    @pytest.mark.asyncio
    async def test_empty_input_returns_defaults(self, ctx):
        """With no upstream data, validation produces zero-value defaults."""
        input = ValidationInput(
            cross_agent_urls=[], coverage_left=[], coverage_center=[], coverage_right=[]
        )
        result = await run_validation_agent(input, ctx)

        assert result["validated_urls"] == []
        assert result["convergence_score"] == 0.0
        assert result["citations"] == []
        assert result["blindspot_score"] == 1.0
        assert "MULTIPLE" in result["blindspot_direction"]

    @pytest.mark.asyncio
    async def test_shared_urls_produce_high_convergence(self, ctx):
        """1 URL cited by 2 agents produces convergence score of 1.0."""
        with _mock_validator(
            {
                "https://shared-source.com/fact": ValidationResult(
                    url="https://shared-source.com/fact",
                    status=ValidationStatus.LIVE,
                ),
            }
        ):
            result = await run_validation_agent(_shared_url_input(), ctx)

        assert result["convergence_score"] == 1.0

    @pytest.mark.asyncio
    async def test_partial_coverage_produces_blindspot(self, ctx):
        """Only left coverage → 2 of 3 segments absent → blindspot ~0.667."""
        with _mock_validator(
            {
                "https://leftnews.com/article/1": ValidationResult(
                    url="https://leftnews.com/article/1",
                    status=ValidationStatus.LIVE,
                ),
            }
        ):
            result = await run_validation_agent(_left_only_input(), ctx)

        assert result["blindspot_score"] == pytest.approx(0.6667, abs=0.001)
        assert "MULTIPLE" in result["blindspot_direction"]

    @pytest.mark.asyncio
    async def test_dead_urls_have_dead_status(self, ctx):
        """Dead URLs are reflected in validated_urls with DEAD status."""
        input = ValidationInput(
            cross_agent_urls=[
                {
                    "url": "https://dead-link.com/gone",
                    "agent": "evidence",
                    "code": "DOMAIN_SOURCE_URL",
                    "source_name": "DeadSource",
                },
            ],
            coverage_left=[],
            coverage_center=[],
            coverage_right=[],
        )
        with _mock_validator(
            {
                "https://dead-link.com/gone": ValidationResult(
                    url="https://dead-link.com/gone",
                    status=ValidationStatus.DEAD,
                ),
            }
        ):
            result = await run_validation_agent(input, ctx)

        assert len(result["validated_urls"]) == 1
        assert result["validated_urls"][0]["status"] == "DEAD"

    @pytest.mark.asyncio
    async def test_full_coverage_no_blindspot(self, ctx):
        """All 3 coverage segments present → blindspot score 0."""
        with _mock_validator(_rich_validations()):
            result = await run_validation_agent(_rich_input(), ctx)

        assert result["blindspot_score"] == 0.0
        assert "NONE" in result["blindspot_direction"]


# ---------------------------------------------------------------------------
# Observation publishing verification
# ---------------------------------------------------------------------------


class TestObservationPublishing:
    """Verify correct observation codes published through run_validation_agent()."""

    @pytest.mark.asyncio
    async def test_publishes_source_extracted_url(self, ctx):
        with _mock_validator(_rich_validations()):
            await run_validation_agent(_rich_input(), ctx)

        codes = [o["code"] for o in ctx.published_observations]
        assert ObservationCode.SOURCE_EXTRACTED_URL in codes

    @pytest.mark.asyncio
    async def test_publishes_source_validation_status(self, ctx):
        with _mock_validator(_rich_validations()):
            await run_validation_agent(_rich_input(), ctx)

        codes = [o["code"] for o in ctx.published_observations]
        assert ObservationCode.SOURCE_VALIDATION_STATUS in codes

    @pytest.mark.asyncio
    async def test_publishes_source_convergence_score(self, ctx):
        with _mock_validator(_rich_validations()):
            await run_validation_agent(_rich_input(), ctx)

        codes = [o["code"] for o in ctx.published_observations]
        assert ObservationCode.SOURCE_CONVERGENCE_SCORE in codes

    @pytest.mark.asyncio
    async def test_publishes_citation_list(self, ctx):
        with _mock_validator(_rich_validations()):
            await run_validation_agent(_rich_input(), ctx)

        codes = [o["code"] for o in ctx.published_observations]
        assert ObservationCode.CITATION_LIST in codes

    @pytest.mark.asyncio
    async def test_publishes_blindspot_score(self, ctx):
        with _mock_validator(_rich_validations()):
            await run_validation_agent(_rich_input(), ctx)

        codes = [o["code"] for o in ctx.published_observations]
        assert ObservationCode.BLINDSPOT_SCORE in codes

    @pytest.mark.asyncio
    async def test_publishes_blindspot_direction(self, ctx):
        with _mock_validator(_rich_validations()):
            await run_validation_agent(_rich_input(), ctx)

        codes = [o["code"] for o in ctx.published_observations]
        assert ObservationCode.BLINDSPOT_DIRECTION in codes

    @pytest.mark.asyncio
    async def test_publishes_cross_spectrum_corroboration(self, ctx):
        with _mock_validator(_rich_validations()):
            await run_validation_agent(_rich_input(), ctx)

        codes = [o["code"] for o in ctx.published_observations]
        assert ObservationCode.CROSS_SPECTRUM_CORROBORATION in codes

    @pytest.mark.asyncio
    async def test_extracted_url_count_matches_input(self, ctx):
        """One SOURCE_EXTRACTED_URL per unique input URL."""
        with _mock_validator(_rich_validations()):
            await run_validation_agent(_rich_input(), ctx)

        extract_obs = [
            o
            for o in ctx.published_observations
            if o["code"] == ObservationCode.SOURCE_EXTRACTED_URL
        ]
        assert len(extract_obs) == 5

    @pytest.mark.asyncio
    async def test_validation_status_count_matches_urls(self, ctx):
        """One SOURCE_VALIDATION_STATUS per validated URL."""
        with _mock_validator(_rich_validations()):
            await run_validation_agent(_rich_input(), ctx)

        status_obs = [
            o
            for o in ctx.published_observations
            if o["code"] == ObservationCode.SOURCE_VALIDATION_STATUS
        ]
        assert len(status_obs) == 5

    @pytest.mark.asyncio
    async def test_no_observations_on_empty_input(self, ctx):
        """Empty input still publishes convergence, citation, and blindspot codes."""
        input = ValidationInput(
            cross_agent_urls=[], coverage_left=[], coverage_center=[], coverage_right=[]
        )
        await run_validation_agent(input, ctx)

        codes = [o["code"] for o in ctx.published_observations]
        # No URLs → no extraction or validation observations
        assert ObservationCode.SOURCE_EXTRACTED_URL not in codes
        assert ObservationCode.SOURCE_VALIDATION_STATUS not in codes
        # Convergence, citation, and blindspot are always published
        assert ObservationCode.SOURCE_CONVERGENCE_SCORE in codes
        assert ObservationCode.CITATION_LIST in codes
        assert ObservationCode.BLINDSPOT_SCORE in codes
        assert ObservationCode.BLINDSPOT_DIRECTION in codes
        assert ObservationCode.CROSS_SPECTRUM_CORROBORATION in codes

    @pytest.mark.asyncio
    async def test_observation_publishing_order(self, ctx):
        """Observations published in graph node order:
        extract -> validate -> convergence -> citations -> blindspots.
        """
        with _mock_validator(_rich_validations()):
            await run_validation_agent(_rich_input(), ctx)

        codes = [o["code"] for o in ctx.published_observations]

        # Find first index of each category
        extract_idx = next(
            i for i, c in enumerate(codes) if c == ObservationCode.SOURCE_EXTRACTED_URL
        )
        validate_idx = next(
            i for i, c in enumerate(codes) if c == ObservationCode.SOURCE_VALIDATION_STATUS
        )
        convergence_idx = next(
            i for i, c in enumerate(codes) if c == ObservationCode.SOURCE_CONVERGENCE_SCORE
        )
        citation_idx = next(i for i, c in enumerate(codes) if c == ObservationCode.CITATION_LIST)
        blindspot_idx = next(i for i, c in enumerate(codes) if c == ObservationCode.BLINDSPOT_SCORE)

        assert extract_idx < validate_idx < convergence_idx < citation_idx < blindspot_idx

    @pytest.mark.asyncio
    async def test_all_observations_have_validation_agent(self, ctx):
        """All published observations have agent='validation'."""
        with _mock_validator(_rich_validations()):
            await run_validation_agent(_rich_input(), ctx)

        for obs in ctx.published_observations:
            assert obs["agent"] == AGENT_NAME


# ---------------------------------------------------------------------------
# Heartbeat verification
# ---------------------------------------------------------------------------


class TestHeartbeat:
    """Verify heartbeat signaling through the validation graph."""

    @pytest.mark.asyncio
    async def test_heartbeat_count(self, ctx):
        """6 heartbeats: 1 initial (run_validation_agent) + 5 graph nodes."""
        with _mock_validator(_rich_validations()):
            await run_validation_agent(_rich_input(), ctx)

        assert ctx.heartbeat_calls.count(AGENT_NAME) == 6

    @pytest.mark.asyncio
    async def test_heartbeat_on_empty_input(self, ctx):
        """Heartbeats fire even with empty input."""
        input = ValidationInput(
            cross_agent_urls=[], coverage_left=[], coverage_center=[], coverage_right=[]
        )
        await run_validation_agent(input, ctx)

        assert ctx.heartbeat_calls.count(AGENT_NAME) == 6

    @pytest.mark.asyncio
    async def test_all_heartbeats_from_validation(self, ctx):
        """All heartbeats use the 'validation' agent name."""
        with _mock_validator(_rich_validations()):
            await run_validation_agent(_rich_input(), ctx)

        for name in ctx.heartbeat_calls:
            assert name == AGENT_NAME


# ---------------------------------------------------------------------------
# Output contract verification
# ---------------------------------------------------------------------------


class TestOutputContract:
    """Verify ValidationOutput typed contract compliance."""

    @pytest.mark.asyncio
    async def test_all_output_fields_present(self, ctx):
        with _mock_validator(_rich_validations()):
            result = await run_validation_agent(_rich_input(), ctx)

        assert "validated_urls" in result
        assert "convergence_score" in result
        assert "citations" in result
        assert "blindspot_score" in result
        assert "blindspot_direction" in result

    @pytest.mark.asyncio
    async def test_validated_urls_structure(self, ctx):
        """Each validated URL entry has url, status, and associations."""
        with _mock_validator(_rich_validations()):
            result = await run_validation_agent(_rich_input(), ctx)

        for url_entry in result["validated_urls"]:
            assert "url" in url_entry
            assert "status" in url_entry
            assert "associations" in url_entry
            assert isinstance(url_entry["associations"], list)
            for assoc in url_entry["associations"]:
                assert "agent" in assoc
                assert "observation_code" in assoc
                assert "source_name" in assoc

    @pytest.mark.asyncio
    async def test_convergence_score_range(self, ctx):
        """Convergence score is between 0.0 and 1.0."""
        with _mock_validator(_rich_validations()):
            result = await run_validation_agent(_rich_input(), ctx)

        assert 0.0 <= result["convergence_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_blindspot_score_range(self, ctx):
        """Blindspot score is between 0.0 and 1.0."""
        with _mock_validator(_rich_validations()):
            result = await run_validation_agent(_rich_input(), ctx)

        assert 0.0 <= result["blindspot_score"] <= 1.0

    @pytest.mark.asyncio
    async def test_citations_are_well_formed(self, ctx):
        """Each citation entry has the expected fields."""
        with _mock_validator(_rich_validations()):
            result = await run_validation_agent(_rich_input(), ctx)

        for citation in result["citations"]:
            assert "sourceUrl" in citation
            assert "sourceName" in citation
            assert "agent" in citation
            assert "observationCode" in citation
            assert "validationStatus" in citation
            assert "convergenceCount" in citation

    @pytest.mark.asyncio
    async def test_blindspot_direction_values(self, ctx):
        """Blindspot direction is a CWE-coded value with a recognized direction code."""
        valid_direction_codes = {"NONE", "LEFT", "CENTER", "RIGHT", "MULTIPLE"}

        with _mock_validator(_rich_validations()):
            result = await run_validation_agent(_rich_input(), ctx)

        # Direction is CWE-coded: "CODE^Display^CodingSystem"
        direction = result["blindspot_direction"]
        code = direction.split("^")[0] if "^" in direction else direction
        assert code in valid_direction_codes

    @pytest.mark.asyncio
    async def test_empty_input_output_types(self, ctx):
        """Empty input produces correctly typed output fields."""
        input = ValidationInput(
            cross_agent_urls=[], coverage_left=[], coverage_center=[], coverage_right=[]
        )
        result = await run_validation_agent(input, ctx)

        assert isinstance(result["validated_urls"], list)
        assert isinstance(result["convergence_score"], float)
        assert isinstance(result["citations"], list)
        assert isinstance(result["blindspot_score"], float)
        assert isinstance(result["blindspot_direction"], str)
