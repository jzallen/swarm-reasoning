"""Tests for the intake ReAct agent module (agents/intake/).

Tests cover:
- Module re-exports from __init__.py
- IntakeInput / IntakeOutput TypedDict shapes
- Agent builder (build_intake_agent) graph construction
- Tool definitions: validate_claim, classify_domain (closure), extract_entities
- CLASSIFY_MODEL constant, AGENT_NAME constant, SYSTEM_PROMPT content
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from swarm_reasoning.agents.intake import (
    IntakeInput,
    IntakeOutput,
    build_intake_agent,
)
from swarm_reasoning.agents.intake.agent import (
    AGENT_NAME,
    CLASSIFY_MODEL,
    ENTITY_MODEL,
    SYSTEM_PROMPT,
    fetch_source_content,
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

    def test_classify_model_constant(self):
        assert CLASSIFY_MODEL == "claude-sonnet-4-6"

    def test_entity_model_constant(self):
        assert ENTITY_MODEL == "claude-haiku-4-5"

    def test_system_prompt_mentions_all_steps(self):
        assert "Validate the claim" in SYSTEM_PROMPT
        assert "Fetch source content" in SYSTEM_PROMPT
        assert "Classify the domain" in SYSTEM_PROMPT
        assert "Extract entities" in SYSTEM_PROMPT

    def test_system_prompt_mentions_tool_names(self):
        assert "validate_claim" in SYSTEM_PROMPT
        assert "fetch_source_content" in SYSTEM_PROMPT
        assert "classify_domain" in SYSTEM_PROMPT
        assert "extract_entities" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# build_intake_agent
# ---------------------------------------------------------------------------


class TestBuildIntakeAgent:
    """Tests for the agent builder function."""

    def test_builds_with_provided_model(self):
        mock_model = MagicMock()
        with patch(
            "swarm_reasoning.agents.intake.agent.create_agent",
        ) as mock_create:
            mock_create.return_value = MagicMock()
            build_intake_agent(model=mock_model)

        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs["model"] is mock_model
        tool_names = {t.name for t in call_kwargs.kwargs["tools"]}
        assert tool_names == {
            "validate_claim",
            "fetch_source_content",
            "classify_domain",
            "extract_entities",
        }
        assert call_kwargs.kwargs["prompt"] == SYSTEM_PROMPT
        assert call_kwargs.kwargs["name"] == AGENT_NAME

    def test_builds_with_default_model(self):
        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
            patch(
                "swarm_reasoning.agents.intake.agent.create_agent",
            ) as mock_create,
            patch(
                "swarm_reasoning.agents.intake.agent.ChatAnthropic",
            ) as mock_chat,
        ):
            mock_chat.return_value = MagicMock()
            mock_create.return_value = MagicMock()
            build_intake_agent()

        # ChatAnthropic called 3 times: classify_model, entity_model, orchestrator
        assert mock_chat.call_count == 3
        # Verify orchestrator model call
        orchestrator_call = mock_chat.call_args_list[2]
        assert orchestrator_call.kwargs == {
            "model": "claude-sonnet-4-6",
            "max_tokens": 1024,
            "temperature": 0,
            "api_key": "test-key",
        }
        mock_create.assert_called_once()

    def test_raises_without_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            from swarm_reasoning.temporal.errors import MissingApiKeyError

            with pytest.raises(MissingApiKeyError):
                build_intake_agent()

    def test_response_format_is_intake_output(self):
        mock_model = MagicMock()
        with patch(
            "swarm_reasoning.agents.intake.agent.create_agent",
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
    """Tests for the classify_domain LangChain tool (closure-based).

    classify_domain is defined inside build_intake_agent() and closes over
    a ChatAnthropic model instance. Tests build the agent, extract the tool,
    and invoke it with mocked model and stream writer.
    """

    @staticmethod
    def _make_mock_model(text: str) -> AsyncMock:
        """Create a mock ChatAnthropic that returns an AIMessage with the given text."""
        mock_response = MagicMock()
        mock_response.content = text
        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        return mock_model

    @staticmethod
    def _get_classify_tool(mock_classify_model):
        """Build the agent with a mocked classify model and extract classify_domain."""
        with (
            patch(
                "swarm_reasoning.agents.intake.agent.ChatAnthropic",
                return_value=mock_classify_model,
            ),
            patch(
                "swarm_reasoning.agents.intake.agent.create_agent",
            ) as mock_create,
        ):
            mock_create.return_value = MagicMock()
            build_intake_agent(model=MagicMock())
            tools = mock_create.call_args.kwargs["tools"]
            return next(t for t in tools if t.name == "classify_domain")

    @pytest.mark.asyncio
    async def test_known_domain(self):
        mock_model = self._make_mock_model("HEALTHCARE")
        classify_tool = self._get_classify_tool(mock_model)

        mock_writer = MagicMock()
        with patch(
            "swarm_reasoning.agents.intake.agent.get_stream_writer",
            return_value=mock_writer,
        ):
            result = await classify_tool.ainvoke(
                {"claim_text": "Vaccines prevent disease"},
            )
        assert result["domain"] == "HEALTHCARE"
        mock_writer.assert_called_once_with(
            {"type": "progress", "message": "Domain classified: HEALTHCARE"},
        )

    @pytest.mark.asyncio
    async def test_falls_back_to_other(self):
        mock_model = self._make_mock_model("UNKNOWN_DOMAIN")
        classify_tool = self._get_classify_tool(mock_model)

        mock_writer = MagicMock()
        with patch(
            "swarm_reasoning.agents.intake.agent.get_stream_writer",
            return_value=mock_writer,
        ):
            result = await classify_tool.ainvoke(
                {"claim_text": "Something vague"},
            )
        assert result["domain"] == "OTHER"

    @pytest.mark.asyncio
    async def test_retries_on_error(self):
        mock_success = MagicMock()
        mock_success.content = "ECONOMICS"
        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(
            side_effect=[
                Exception("API connection error"),
                mock_success,
            ],
        )
        classify_tool = self._get_classify_tool(mock_model)

        mock_writer = MagicMock()
        with patch(
            "swarm_reasoning.agents.intake.agent.get_stream_writer",
            return_value=mock_writer,
        ):
            result = await classify_tool.ainvoke(
                {"claim_text": "GDP grew 3%"},
            )
        assert result["domain"] == "ECONOMICS"

    @pytest.mark.asyncio
    async def test_forwards_config_to_model(self):
        mock_model = self._make_mock_model("SCIENCE")
        classify_tool = self._get_classify_tool(mock_model)

        mock_writer = MagicMock()
        config = {"callbacks": [MagicMock()]}
        with patch(
            "swarm_reasoning.agents.intake.agent.get_stream_writer",
            return_value=mock_writer,
        ):
            result = await classify_tool.ainvoke(
                {"claim_text": "Climate change is real"},
                config=config,
            )
        assert result["domain"] == "SCIENCE"
        # Verify config was forwarded to the model
        call_kwargs = mock_model.ainvoke.call_args.kwargs
        assert "config" in call_kwargs


# ---------------------------------------------------------------------------
# Tool: fetch_source_content
# ---------------------------------------------------------------------------


class TestFetchSourceContentTool:
    """Tests for the fetch_source_content LangChain tool."""

    @pytest.mark.asyncio
    async def test_success(self):
        from swarm_reasoning.agents.intake.tools.fetch_content import FetchResult

        mock_result = FetchResult(
            url="https://example.com/article",
            title="Test Article",
            date="2024-01-15",
            text="Article body text",
            word_count=3,
            extraction_method="trafilatura",
        )
        mock_writer = MagicMock()
        with (
            patch(
                "swarm_reasoning.agents.intake.agent._fetch_content",
                return_value=mock_result,
            ),
            patch(
                "swarm_reasoning.agents.intake.agent.get_stream_writer",
                return_value=mock_writer,
            ),
        ):
            result = await fetch_source_content.ainvoke(
                {"url": "https://example.com/article"},
            )
        assert result["success"] is True
        assert result["title"] == "Test Article"
        assert result["word_count"] == 3
        assert mock_writer.call_count == 2
        mock_writer.assert_any_call(
            {"type": "progress", "message": "Fetching article content..."},
        )
        mock_writer.assert_any_call(
            {"type": "progress", "message": "Content extracted: 3 words"},
        )

    @pytest.mark.asyncio
    async def test_fetch_error(self):
        from swarm_reasoning.agents.intake.tools.fetch_content import FetchError

        mock_writer = MagicMock()
        with (
            patch(
                "swarm_reasoning.agents.intake.agent._fetch_content",
                side_effect=FetchError("FETCH_TIMEOUT"),
            ),
            patch(
                "swarm_reasoning.agents.intake.agent.get_stream_writer",
                return_value=mock_writer,
            ),
        ):
            result = await fetch_source_content.ainvoke(
                {"url": "https://example.com/slow"},
            )
        assert result["success"] is False
        assert result["error"] == "FETCH_TIMEOUT"
        assert mock_writer.call_count == 2
        mock_writer.assert_any_call(
            {"type": "progress", "message": "Fetching article content..."},
        )
        mock_writer.assert_any_call(
            {"type": "progress", "message": "Fetch error: FETCH_TIMEOUT"},
        )


# ---------------------------------------------------------------------------
# Tool: extract_entities
# ---------------------------------------------------------------------------


class TestExtractEntitiesTool:
    """Tests for the extract_entities LangChain tool (closure-based).

    extract_entities is defined inside build_intake_agent() and closes over
    a ChatAnthropic model instance. Tests build the agent, extract the tool,
    and invoke it with mocked model and stream writer.
    """

    @staticmethod
    def _make_mock_model(text: str) -> AsyncMock:
        """Create a mock ChatAnthropic that returns an AIMessage with the given text."""
        mock_response = MagicMock()
        mock_response.content = text
        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(return_value=mock_response)
        return mock_model

    @staticmethod
    def _get_entity_tool(mock_entity_model):
        """Build the agent with a mocked entity model and extract extract_entities."""
        mock_classify_model = MagicMock()
        with (
            patch(
                "swarm_reasoning.agents.intake.agent.ChatAnthropic",
                side_effect=[mock_classify_model, mock_entity_model],
            ),
            patch(
                "swarm_reasoning.agents.intake.agent.create_agent",
            ) as mock_create,
        ):
            mock_create.return_value = MagicMock()
            build_intake_agent(model=MagicMock())
            tools = mock_create.call_args.kwargs["tools"]
            return next(t for t in tools if t.name == "extract_entities")

    @pytest.mark.asyncio
    async def test_extracts_entities(self):
        import json

        entities_json = json.dumps(
            {
                "persons": ["Joe Biden"],
                "organizations": ["CDC"],
                "dates": ["20240115"],
                "locations": ["Washington"],
                "statistics": ["3.5%"],
            }
        )
        mock_model = self._make_mock_model(entities_json)
        entity_tool = self._get_entity_tool(mock_model)

        mock_writer = MagicMock()
        with patch(
            "swarm_reasoning.agents.intake.agent.get_stream_writer",
            return_value=mock_writer,
        ):
            result = await entity_tool.ainvoke(
                {"claim_text": "biden announced at the cdc"},
            )
        assert result["persons"] == ["Joe Biden"]
        assert result["organizations"] == ["CDC"]
        assert result["dates"] == ["20240115"]
        assert result["locations"] == ["Washington"]
        assert result["statistics"] == ["3.5%"]
        mock_writer.assert_called_once_with(
            {"type": "progress", "message": "Entities extracted: 5 found"},
        )

    @pytest.mark.asyncio
    async def test_empty_entities(self):
        import json

        entities_json = json.dumps(
            {
                "persons": [],
                "organizations": [],
                "dates": [],
                "locations": [],
                "statistics": [],
            }
        )
        mock_model = self._make_mock_model(entities_json)
        entity_tool = self._get_entity_tool(mock_model)

        mock_writer = MagicMock()
        with patch(
            "swarm_reasoning.agents.intake.agent.get_stream_writer",
            return_value=mock_writer,
        ):
            result = await entity_tool.ainvoke(
                {"claim_text": "nothing here"},
            )
        assert all(v == [] for v in result.values())
        mock_writer.assert_called_once_with(
            {"type": "progress", "message": "Entities extracted: 0 found"},
        )

    @pytest.mark.asyncio
    async def test_falls_back_on_invalid_json(self):
        mock_model = self._make_mock_model("not valid json at all")
        entity_tool = self._get_entity_tool(mock_model)

        mock_writer = MagicMock()
        with patch(
            "swarm_reasoning.agents.intake.agent.get_stream_writer",
            return_value=mock_writer,
        ):
            result = await entity_tool.ainvoke(
                {"claim_text": "some claim"},
            )
        assert all(v == [] for v in result.values())

    @pytest.mark.asyncio
    async def test_falls_back_on_llm_error(self):
        mock_model = AsyncMock()
        mock_model.ainvoke = AsyncMock(side_effect=Exception("API error"))
        entity_tool = self._get_entity_tool(mock_model)

        mock_writer = MagicMock()
        with patch(
            "swarm_reasoning.agents.intake.agent.get_stream_writer",
            return_value=mock_writer,
        ):
            result = await entity_tool.ainvoke(
                {"claim_text": "some claim"},
            )
        assert all(v == [] for v in result.values())

    @pytest.mark.asyncio
    async def test_forwards_config_to_model(self):
        import json

        entities_json = json.dumps(
            {
                "persons": ["Obama"],
                "organizations": [],
                "dates": [],
                "locations": [],
                "statistics": [],
            }
        )
        mock_model = self._make_mock_model(entities_json)
        entity_tool = self._get_entity_tool(mock_model)

        mock_writer = MagicMock()
        config = {"callbacks": [MagicMock()]}
        with patch(
            "swarm_reasoning.agents.intake.agent.get_stream_writer",
            return_value=mock_writer,
        ):
            result = await entity_tool.ainvoke(
                {"claim_text": "Obama signed the bill"},
                config=config,
            )
        assert result["persons"] == ["Obama"]
        # Verify config was forwarded to the model
        call_kwargs = mock_model.ainvoke.call_args.kwargs
        assert "config" in call_kwargs
