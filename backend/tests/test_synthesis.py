"""Tests for the Synthesis Agent (Agent 2)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.synthesis import SynthesisAgent
from backend.models.schemas import ConflictDecision, MergeStrategy, SynthesisResult


class TestSynthesisAgent:
    """Test suite for SynthesisAgent."""

    @pytest.mark.asyncio
    async def test_analyze_new_concepts_no_existing(self, sample_extracted_concepts):
        """Test analysis when there are no existing concepts (all NEW)."""
        with patch.object(SynthesisAgent, "__init__", lambda self, **kwargs: None):
            agent = SynthesisAgent()
            agent.model_name = "gpt-4o-mini"
            agent.similarity_threshold = 0.8

            result = await agent.analyze(
                new_concepts=sample_extracted_concepts,
                existing_concepts=None,
            )

            assert isinstance(result, SynthesisResult)
            assert len(result.decisions) == len(sample_extracted_concepts)

            # All should be marked as NEW since no existing concepts
            for decision in result.decisions:
                assert decision.decision == ConflictDecision.NEW
                assert decision.merge_strategy == MergeStrategy.CREATE_NEW
                assert decision.confidence == 1.0

    @pytest.mark.asyncio
    async def test_analyze_detects_duplicate(
        self, sample_extracted_concepts, mock_llm, mock_embeddings
    ):
        """Test that duplicate concepts are properly detected."""
        # Create an existing concept that matches one of the new ones
        existing_concepts = [
            {
                "id": "existing-1",
                "name": "Neural Network",
                "definition": "Computing systems inspired by biological neural networks",
                "domain": "Machine Learning",
            }
        ]

        # Mock LLM response indicating duplicate
        mock_response = {
            "decisions": [
                {
                    "new_concept_name": "Neural Network",
                    "decision": "DUPLICATE",
                    "confidence": 0.95,
                    "matched_concept_id": "existing-1",
                    "reasoning": "Same concept, same definition",
                    "merge_strategy": "SKIP",
                    "updated_definition": None,
                }
            ]
        }
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content=json.dumps(mock_response))
        )

        with patch.object(SynthesisAgent, "__init__", lambda self, **kwargs: None):
            agent = SynthesisAgent()
            agent.model_name = "gpt-4o-mini"
            agent.llm = mock_llm
            agent.embeddings = mock_embeddings
            agent.similarity_threshold = 0.8
            agent._prompt_template = "Test: {new_concepts} {existing_concepts}"

            # Test with just the Neural Network concept
            result = await agent.analyze(
                new_concepts=[sample_extracted_concepts[0]],
                existing_concepts=existing_concepts,
            )

            assert isinstance(result, SynthesisResult)
            assert len(result.decisions) == 1
            assert result.decisions[0].decision == ConflictDecision.DUPLICATE
            assert result.decisions[0].merge_strategy == MergeStrategy.SKIP

    @pytest.mark.asyncio
    async def test_analyze_handles_error_gracefully(self, sample_extracted_concepts):
        """Test that analysis handles errors and defaults to NEW."""
        existing_concepts = [
            {
                "id": "existing-1",
                "name": "Some Concept",
                "definition": "Some definition",
            }
        ]

        with patch.object(SynthesisAgent, "__init__", lambda self, **kwargs: None):
            agent = SynthesisAgent()
            agent.model_name = "gpt-4o-mini"
            agent.similarity_threshold = 0.8

            # Mock embeddings to raise an error
            agent.embeddings = AsyncMock()
            agent.embeddings.aembed_query = AsyncMock(
                side_effect=Exception("API Error")
            )

            result = await agent.analyze(
                new_concepts=[sample_extracted_concepts[0]],
                existing_concepts=existing_concepts,
            )

            assert isinstance(result, SynthesisResult)
            assert len(result.decisions) == 1
            # Should default to NEW on error
            assert result.decisions[0].decision == ConflictDecision.NEW
            assert result.decisions[0].confidence == 0.5
            assert "error" in result.decisions[0].reasoning.lower()

    @pytest.mark.asyncio
    async def test_cosine_similarity_calculation(self):
        """Test the cosine similarity calculation."""
        with patch.object(SynthesisAgent, "__init__", lambda self, **kwargs: None):
            agent = SynthesisAgent()

            # Identical vectors should have similarity 1.0
            vec1 = [1.0, 0.0, 0.0]
            similarity = agent._cosine_similarity(vec1, vec1)
            assert abs(similarity - 1.0) < 0.001

            # Orthogonal vectors should have similarity 0.0
            vec2 = [0.0, 1.0, 0.0]
            similarity = agent._cosine_similarity(vec1, vec2)
            assert abs(similarity - 0.0) < 0.001

            # Opposite vectors should have similarity -1.0
            vec3 = [-1.0, 0.0, 0.0]
            similarity = agent._cosine_similarity(vec1, vec3)
            assert abs(similarity - (-1.0)) < 0.001

            # Zero vector should return 0.0
            vec_zero = [0.0, 0.0, 0.0]
            similarity = agent._cosine_similarity(vec1, vec_zero)
            assert similarity == 0.0
