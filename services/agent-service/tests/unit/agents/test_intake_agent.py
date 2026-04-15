"""Tests for the intake ReAct agent module (agents/intake/).

Tests cover:
- Module re-exports from __init__.py
- IntakeInput / IntakeOutput TypedDict shapes
- Agent builder (build_intake_agent) graph construction
- Tool definitions: validate_claim, classify_domain, normalize_claim,
  score_check_worthiness, extract_entities
- TOOLS list, AGENT_NAME constant, SYSTEM_PROMPT content
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from swarm_reasoning.agents.intake import (
    IntakeInput,
    IntakeOutput,
    build_intake_agent,
)
from swarm_reasoning.agents.intake.agent import (
    AGENT_NAME,
    SYSTEM_PROMPT,
    TOOLS,
    classify_domain,
    extract_entities,
    normalize_claim,
    score_check_worthiness,
    validate_claim,
)
from swarm_reasoning.agents.intake.models import (
    IntakeInput as ModelsIntakeInput,
)
from swarm_reasoning.agents.intake.models import (
    IntakeOutput as ModelsIntakeOutput,
)

# ---------------------------------------------------------------------------
# Module exports (__init__.py)
# ---------------------------------------------------------------------------


class TestModuleExports:
    """Verify __init__.py re-exports the public API."""

    def test_exports_build_intake_agent(self):
        assert callable(build_intake_agent)

    def test_exports_intake_input(self):
        assert IntakeInput is ModelsIntakeInput

    def test_exports_intake_output(self):
        assert IntakeOutput is ModelsIntakeOutput


# ---------------------------------------------------------------------------
# Models (IntakeInput / IntakeOutput)
# ---------------------------------------------------------------------------


class TestIntakeInput:
    """Tests for IntakeInput TypedDict shape."""

    def test_required_keys(self):
        annotations = IntakeInput.__annotations__
        assert "claim_text" in annotations
        assert "claim_url" in annotations
        assert "submission_date" in annotations

    def test_accepts_valid_input(self):
        inp: IntakeInput = {
            "claim_text": "The rate dropped to 3.5%",
            "claim_url": None,
            "submission_date": None,
        }
        assert inp["claim_text"] == "The rate dropped to 3.5%"
        assert inp["claim_url"] is None
        assert inp["submission_date"] is None

    def test_accepts_full_input(self):
        inp: IntakeInput = {
            "claim_text": "The rate dropped",
            "claim_url": "https://example.com",
            "submission_date": "2024-01-15",
        }
        assert inp["claim_url"] == "https://example.com"
        assert inp["submission_date"] == "2024-01-15"


class TestIntakeOutput:
    """Tests for IntakeOutput TypedDict shape."""

    def test_required_keys(self):
        annotations = IntakeOutput.__annotations__
        expected = {
            "is_check_worthy",
            "normalized_claim",
            "claim_domain",
            "check_worthy_score",
            "entities",
            "errors",
        }
        assert expected == set(annotations.keys())

    def test_accepts_successful_output(self):
        out: IntakeOutput = {
            "is_check_worthy": True,
            "normalized_claim": "the rate dropped to 3.5%",
            "claim_domain": "ECONOMICS",
            "check_worthy_score": 0.85,
            "entities": {
                "persons": [],
                "organizations": ["BLS"],
                "dates": ["2024"],
                "locations": [],
                "statistics": ["3.5%"],
            },
            "errors": [],
        }
        assert out["is_check_worthy"] is True
        assert out["claim_domain"] == "ECONOMICS"

    def test_accepts_rejected_output(self):
        out: IntakeOutput = {
            "is_check_worthy": False,
            "normalized_claim": None,
            "claim_domain": None,
            "check_worthy_score": None,
            "entities": {},
            "errors": ["Claim rejected: CLAIM_TEXT_TOO_SHORT"],
        }
        assert out["is_check_worthy"] is False
        assert len(out["errors"]) == 1


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Tests for module-level constants."""

    def test_agent_name_is_intake(self):
        assert AGENT_NAME == "intake"

    def test_tools_count(self):
        assert len(TOOLS) == 5

    def test_tool_names(self):
        tool_names = {t.name for t in TOOLS}
        expected = {
            "validate_claim",
            "classify_domain",
            "normalize_claim",
            "score_check_worthiness",
            "extract_entities",
        }
        assert tool_names == expected

    def test_system_prompt_mentions_all_steps(self):
        assert "Validate the claim" in SYSTEM_PROMPT
        assert "Classify the domain" in SYSTEM_PROMPT
        assert "Normalize the claim" in SYSTEM_PROMPT
        assert "Score check-worthiness" in SYSTEM_PROMPT
        assert "Extract entities" in SYSTEM_PROMPT

    def test_system_prompt_mentions_tool_names(self):
        assert "validate_claim" in SYSTEM_PROMPT
        assert "classify_domain" in SYSTEM_PROMPT
        assert "normalize_claim" in SYSTEM_PROMPT
        assert "score_check_worthiness" in SYSTEM_PROMPT
        assert "extract_entities" in SYSTEM_PROMPT

    def test_system_prompt_mentions_check_worthy_gate(self):
        assert "NOT check-worthy" in SYSTEM_PROMPT
        assert "skip" in SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# build_intake_agent
# ---------------------------------------------------------------------------


class TestBuildIntakeAgent:
    """Tests for the agent builder function."""

    def test_builds_with_provided_model(self):
        mock_model = MagicMock()
        with patch(
            "swarm_reasoning.agents.intake.agent.create_react_agent",
        ) as mock_create:
            mock_create.return_value = MagicMock()
            build_intake_agent(model=mock_model)

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs["model"] is mock_model
        assert call_kwargs.kwargs["tools"] == TOOLS
        assert call_kwargs.kwargs["prompt"] == SYSTEM_PROMPT
        assert call_kwargs.kwargs["name"] == AGENT_NAME

    def test_builds_with_default_model(self):
        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.agents.intake.agent.create_react_agent",
            ) as mock_create,
            patch(
                "swarm_reasoning.agents.intake.agent.ChatAnthropic",
            ) as mock_chat,
        ):
            mock_chat.return_value = MagicMock()
            mock_create.return_value = MagicMock()
            build_intake_agent()

        mock_chat.assert_called_once_with(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            temperature=0,
            api_key="test-key",
        )
        mock_create.assert_called_once()

    def test_raises_without_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            from swarm_reasoning.temporal.errors import MissingApiKeyError

            with pytest.raises(MissingApiKeyError):
                build_intake_agent()

    def test_response_format_is_intake_output(self):
        mock_model = MagicMock()
        with patch(
            "swarm_reasoning.agents.intake.agent.create_react_agent",
        ) as mock_create:
            mock_create.return_value = MagicMock()
            build_intake_agent(model=mock_model)

        assert mock_create.call_args.kwargs["response_format"] is IntakeOutput


# ---------------------------------------------------------------------------
# Tool: validate_claim
# ---------------------------------------------------------------------------


class TestValidateClaimTool:
    """Tests for the validate_claim LangChain tool."""

    @pytest.mark.asyncio
    async def test_valid_claim(self):
        result = await validate_claim.ainvoke(
            {"claim_text": "The unemployment rate is 3.5%"},
        )
        assert result["valid"] is True
        assert result["claim_text"] == "The unemployment rate is 3.5%"
        assert result["source_url"] is None
        assert result["normalized_date"] is None

    @pytest.mark.asyncio
    async def test_valid_claim_with_url_and_date(self):
        result = await validate_claim.ainvoke(
            {
                "claim_text": "The rate dropped",
                "source_url": "https://example.com/article",
                "submission_date": "2024-01-15",
            },
        )
        assert result["valid"] is True
        assert result["source_url"] == "https://example.com/article"
        assert result["normalized_date"] == "20240115"

    @pytest.mark.asyncio
    async def test_rejects_empty_claim(self):
        result = await validate_claim.ainvoke({"claim_text": ""})
        assert result["valid"] is False
        assert result["error"] == "CLAIM_TEXT_EMPTY"

    @pytest.mark.asyncio
    async def test_rejects_short_claim(self):
        result = await validate_claim.ainvoke({"claim_text": "Hi"})
        assert result["valid"] is False
        assert result["error"] == "CLAIM_TEXT_TOO_SHORT"

    @pytest.mark.asyncio
    async def test_rejects_invalid_url(self):
        result = await validate_claim.ainvoke(
            {"claim_text": "A valid claim here", "source_url": "not-a-url"},
        )
        assert result["valid"] is False
        assert result["error"] == "SOURCE_URL_INVALID_FORMAT"

    @pytest.mark.asyncio
    async def test_strips_whitespace(self):
        result = await validate_claim.ainvoke(
            {"claim_text": "  The rate is 3.5%  "},
        )
        assert result["valid"] is True
        assert result["claim_text"] == "The rate is 3.5%"


# ---------------------------------------------------------------------------
# Tool: classify_domain
# ---------------------------------------------------------------------------


class TestClassifyDomainTool:
    """Tests for the classify_domain LangChain tool."""

    @pytest.mark.asyncio
    async def test_known_domain(self):
        with (
            patch(
                "swarm_reasoning.agents.intake.agent._get_anthropic_client",
            ),
            patch(
                "swarm_reasoning.agents.intake.agent.call_claude",
                return_value="HEALTHCARE",
            ),
        ):
            result = await classify_domain.ainvoke(
                {"claim_text": "Vaccines prevent disease"},
            )
        assert result["domain"] == "HEALTHCARE"

    @pytest.mark.asyncio
    async def test_falls_back_to_other(self):
        with (
            patch(
                "swarm_reasoning.agents.intake.agent._get_anthropic_client",
            ),
            patch(
                "swarm_reasoning.agents.intake.agent.call_claude",
                return_value="UNKNOWN_DOMAIN",
            ),
        ):
            result = await classify_domain.ainvoke(
                {"claim_text": "Something vague"},
            )
        assert result["domain"] == "OTHER"

    @pytest.mark.asyncio
    async def test_retries_on_api_error(self):
        import anthropic as anthropic_lib

        with (
            patch(
                "swarm_reasoning.agents.intake.agent._get_anthropic_client",
            ),
            patch(
                "swarm_reasoning.agents.intake.agent.call_claude",
                side_effect=[
                    anthropic_lib.APIConnectionError(request=MagicMock()),
                    "ECONOMICS",
                ],
            ),
        ):
            result = await classify_domain.ainvoke(
                {"claim_text": "GDP grew 3%"},
            )
        assert result["domain"] == "ECONOMICS"


# ---------------------------------------------------------------------------
# Tool: normalize_claim
# ---------------------------------------------------------------------------


class TestNormalizeClaimTool:
    """Tests for the normalize_claim LangChain tool."""

    @pytest.mark.asyncio
    async def test_normalizes_text(self):
        result = await normalize_claim.ainvoke(
            {"claim_text": "REPORTEDLY the rate dropped"},
        )
        assert result["normalized"] == "the rate dropped"
        assert "reportedly" in [h.lower() for h in result["hedges_removed"]]

    @pytest.mark.asyncio
    async def test_preserves_simple_text(self):
        result = await normalize_claim.ainvoke(
            {"claim_text": "The rate is 3.5%"},
        )
        assert result["normalized"] == "the rate is 3.5%"
        assert result["hedges_removed"] == []

    @pytest.mark.asyncio
    async def test_returns_pronouns_resolved(self):
        result = await normalize_claim.ainvoke(
            {"claim_text": "The policy changed"},
        )
        assert "pronouns_resolved" in result


# ---------------------------------------------------------------------------
# Tool: score_check_worthiness
# ---------------------------------------------------------------------------


class TestScoreCheckWorthinessTool:
    """Tests for the score_check_worthiness LangChain tool."""

    @pytest.mark.asyncio
    async def test_check_worthy(self):
        with (
            patch(
                "swarm_reasoning.agents.intake.agent._get_anthropic_client",
            ),
            patch(
                "swarm_reasoning.agents.intake.agent.score_claim_text",
            ) as mock_score,
        ):
            mock_score.return_value = MagicMock(
                score=0.85,
                rationale="Strong factual claim",
                proceed=True,
            )
            result = await score_check_worthiness.ainvoke(
                {"normalized_claim": "the rate dropped to 3.5%"},
            )
        assert result["score"] == 0.85
        assert result["is_check_worthy"] is True
        assert result["rationale"] == "Strong factual claim"

    @pytest.mark.asyncio
    async def test_not_check_worthy(self):
        with (
            patch(
                "swarm_reasoning.agents.intake.agent._get_anthropic_client",
            ),
            patch(
                "swarm_reasoning.agents.intake.agent.score_claim_text",
            ) as mock_score,
        ):
            mock_score.return_value = MagicMock(
                score=0.15,
                rationale="Opinion",
                proceed=False,
            )
            result = await score_check_worthiness.ainvoke(
                {"normalized_claim": "i like pizza"},
            )
        assert result["score"] == 0.15
        assert result["is_check_worthy"] is False


# ---------------------------------------------------------------------------
# Tool: extract_entities
# ---------------------------------------------------------------------------


class TestExtractEntitiesTool:
    """Tests for the extract_entities LangChain tool."""

    @pytest.mark.asyncio
    async def test_extracts_entities(self):
        with (
            patch(
                "swarm_reasoning.agents.intake.agent._get_anthropic_client",
            ),
            patch(
                "swarm_reasoning.agents.intake.agent.extract_entities_llm",
            ) as mock_extract,
        ):
            mock_extract.return_value = MagicMock(
                persons=["Joe Biden"],
                organizations=["CDC"],
                dates=["20240115"],
                locations=["Washington"],
                statistics=["3.5%"],
            )
            result = await extract_entities.ainvoke(
                {"claim_text": "biden announced at the cdc"},
            )
        assert result["persons"] == ["Joe Biden"]
        assert result["organizations"] == ["CDC"]
        assert result["dates"] == ["20240115"]
        assert result["locations"] == ["Washington"]
        assert result["statistics"] == ["3.5%"]

    @pytest.mark.asyncio
    async def test_empty_entities(self):
        with (
            patch(
                "swarm_reasoning.agents.intake.agent._get_anthropic_client",
            ),
            patch(
                "swarm_reasoning.agents.intake.agent.extract_entities_llm",
            ) as mock_extract,
        ):
            mock_extract.return_value = MagicMock(
                persons=[],
                organizations=[],
                dates=[],
                locations=[],
                statistics=[],
            )
            result = await extract_entities.ainvoke(
                {"claim_text": "nothing here"},
            )
        assert all(v == [] for v in result.values())
