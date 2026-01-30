"""Tests for the Extraction Agent (Agent 1)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.extraction import ExtractionAgent
from backend.models.schemas import ExtractionResult


class TestExtractionAgent:
    """Test suite for ExtractionAgent."""

    @pytest.mark.asyncio
    async def test_extract_happy_path(self, sample_markdown_content, mock_llm):
        """Test successful concept extraction from valid markdown."""
        # Setup mock response
        mock_response = {
            "concepts": [
                {
                    "name": "Neural Network",
                    "definition": "Computing systems inspired by biological neural networks",
                    "domain": "Machine Learning",
                    "complexity_score": 6,
                    "confidence": 0.95,
                    "related_concepts": ["Backpropagation"],
                    "prerequisites": ["Linear Algebra"],
                },
                {
                    "name": "Backpropagation",
                    "definition": "Algorithm to train neural networks",
                    "domain": "Machine Learning",
                    "complexity_score": 7,
                    "confidence": 0.9,
                    "related_concepts": ["Neural Network"],
                    "prerequisites": ["Calculus"],
                },
            ]
        }

        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content=json.dumps(mock_response))
        )

        with patch.object(ExtractionAgent, "__init__", lambda self, **kwargs: None):
            agent = ExtractionAgent()
            agent.model_name = "gpt-3.5-turbo-1106"
            agent.llm = mock_llm
            agent._prompt_template = "Test prompt: {content}"

            result = await agent.extract(sample_markdown_content)

            assert isinstance(result, ExtractionResult)
            assert len(result.concepts) == 2
            assert result.concepts[0].name == "Neural Network"
            assert result.concepts[1].name == "Backpropagation"
            assert result.model_used == "gpt-3.5-turbo-1106"
            assert result.processing_time_ms is not None

    @pytest.mark.asyncio
    async def test_extract_empty_input(self, mock_llm):
        """Test extraction with empty input returns empty concepts."""
        mock_response = {"concepts": []}
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content=json.dumps(mock_response))
        )

        with patch.object(ExtractionAgent, "__init__", lambda self, **kwargs: None):
            agent = ExtractionAgent()
            agent.model_name = "gpt-3.5-turbo-1106"
            agent.llm = mock_llm
            agent._prompt_template = "Test prompt: {content}"

            result = await agent.extract("")

            assert isinstance(result, ExtractionResult)
            assert len(result.concepts) == 0

    @pytest.mark.asyncio
    async def test_extract_malformed_json_error(self, mock_llm):
        """Test extraction handles malformed JSON response."""
        from tenacity import RetryError

        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="This is not valid JSON {{{")
        )

        with patch.object(ExtractionAgent, "__init__", lambda self, **kwargs: None):
            agent = ExtractionAgent()
            agent.model_name = "gpt-3.5-turbo-1106"
            agent.llm = mock_llm
            agent._prompt_template = "Test prompt: {content}"

            # The retry decorator wraps the ValueError in a RetryError
            with pytest.raises(RetryError):
                await agent.extract("Some content")

    @pytest.mark.asyncio
    async def test_extract_with_context(self, sample_markdown_content, mock_llm):
        """Test extraction with existing concept context."""
        mock_response = {
            "concepts": [
                {
                    "name": "Gradient Descent",
                    "definition": "Optimization algorithm",
                    "domain": "Machine Learning",
                    "complexity_score": 6,
                    "confidence": 0.9,
                    "related_concepts": ["Neural Network"],  # Links to existing
                    "prerequisites": [],
                }
            ]
        }
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content=json.dumps(mock_response))
        )

        with patch.object(ExtractionAgent, "__init__", lambda self, **kwargs: None):
            agent = ExtractionAgent()
            agent.model_name = "gpt-3.5-turbo-1106"
            agent.llm = mock_llm
            agent._prompt_template = "Test prompt: {content}"

            existing = ["Neural Network", "Linear Algebra"]
            result = await agent.extract_with_context(
                sample_markdown_content, existing
            )

            assert isinstance(result, ExtractionResult)
            assert len(result.concepts) >= 1
            # Verify the LLM was called with context
            call_args = mock_llm.ainvoke.call_args[0][0]
            assert "Neural Network" in call_args
