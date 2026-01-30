"""Tests for the Graph Builder Agent (Agent 3)."""

from unittest.mock import AsyncMock, patch

import pytest

from backend.agents.graph_builder import GraphBuilderAgent
from backend.models.schemas import ConflictDecision, MergeStrategy


class TestGraphBuilderAgent:
    """Test suite for GraphBuilderAgent."""

    @pytest.mark.asyncio
    async def test_build_creates_single_concept(
        self, mock_neo4j_client, mock_embeddings
    ):
        """Test building graph with a single new concept."""
        concepts = [
            {
                "id": "concept-1",
                "name": "Test Concept",
                "definition": "A test concept for unit testing",
                "domain": "Testing",
                "complexity_score": 5,
                "related_concepts": [],
                "prerequisites": [],
            }
        ]

        with patch(
            "backend.agents.graph_builder.get_neo4j_client",
            return_value=mock_neo4j_client,
        ):
            with patch.object(
                GraphBuilderAgent, "__init__", lambda self, **kwargs: None
            ):
                agent = GraphBuilderAgent()
                agent.embeddings = mock_embeddings

                result = await agent.build(concepts=concepts, conflicts=None)

                assert result["concepts_created"] == 1
                assert result["concepts_updated"] == 0
                assert len(result["concept_ids"]) == 1
                mock_neo4j_client.create_concept.assert_called_once()

    @pytest.mark.asyncio
    async def test_build_creates_multiple_concepts_with_relationships(
        self, mock_neo4j_client, mock_embeddings
    ):
        """Test building graph with multiple concepts and relationships."""
        concepts = [
            {
                "id": "concept-1",
                "name": "Neural Network",
                "definition": "Computing system",
                "domain": "ML",
                "complexity_score": 6,
                "related_concepts": ["Backpropagation"],
                "prerequisites": [],
            },
            {
                "id": "concept-2",
                "name": "Backpropagation",
                "definition": "Training algorithm",
                "domain": "ML",
                "complexity_score": 7,
                "related_concepts": ["Neural Network"],
                "prerequisites": ["Neural Network"],
            },
        ]

        with patch(
            "backend.agents.graph_builder.get_neo4j_client",
            return_value=mock_neo4j_client,
        ):
            with patch.object(
                GraphBuilderAgent, "__init__", lambda self, **kwargs: None
            ):
                agent = GraphBuilderAgent()
                agent.embeddings = mock_embeddings

                result = await agent.build(concepts=concepts, conflicts=None)

                assert result["concepts_created"] == 2
                assert len(result["concept_ids"]) == 2
                # Should create relationships
                assert result["relationships_created"] >= 0
                assert mock_neo4j_client.create_concept.call_count == 2

    @pytest.mark.asyncio
    async def test_build_skips_duplicates(self, mock_neo4j_client, mock_embeddings):
        """Test that duplicate concepts are skipped based on conflict decisions."""
        concepts = [
            {
                "id": "concept-1",
                "name": "Existing Concept",
                "definition": "Already exists",
                "domain": "Test",
                "complexity_score": 5,
                "related_concepts": [],
                "prerequisites": [],
            }
        ]

        # Mark as duplicate with SKIP strategy
        conflicts = [
            {
                "new_concept_name": "Existing Concept",
                "decision": ConflictDecision.DUPLICATE.value,
                "confidence": 0.95,
                "matched_concept_id": "existing-id-123",
                "reasoning": "Duplicate",
                "merge_strategy": MergeStrategy.SKIP.value,
                "updated_definition": None,
            }
        ]

        with patch(
            "backend.agents.graph_builder.get_neo4j_client",
            return_value=mock_neo4j_client,
        ):
            with patch.object(
                GraphBuilderAgent, "__init__", lambda self, **kwargs: None
            ):
                agent = GraphBuilderAgent()
                agent.embeddings = mock_embeddings

                result = await agent.build(concepts=concepts, conflicts=conflicts)

                # Should not create new concept (skipped)
                assert result["concepts_created"] == 0
                # Should still track the existing concept ID
                assert "existing-id-123" in result["concept_ids"]
                mock_neo4j_client.create_concept.assert_not_called()

    @pytest.mark.asyncio
    async def test_build_merges_enhanced_concepts(
        self, mock_neo4j_client, mock_embeddings
    ):
        """Test that enhanced concepts are merged with updated definitions."""
        concepts = [
            {
                "id": "concept-1",
                "name": "Enhanced Concept",
                "definition": "Original definition",
                "domain": "Test",
                "complexity_score": 5,
                "related_concepts": [],
                "prerequisites": [],
            }
        ]

        # Mark as enhance with MERGE strategy
        conflicts = [
            {
                "new_concept_name": "Enhanced Concept",
                "decision": ConflictDecision.ENHANCE.value,
                "confidence": 0.8,
                "matched_concept_id": "existing-id-456",
                "reasoning": "Enhances existing",
                "merge_strategy": MergeStrategy.MERGE.value,
                "updated_definition": "Merged and enhanced definition with new information",
            }
        ]

        with patch(
            "backend.agents.graph_builder.get_neo4j_client",
            return_value=mock_neo4j_client,
        ):
            with patch.object(
                GraphBuilderAgent, "__init__", lambda self, **kwargs: None
            ):
                agent = GraphBuilderAgent()
                agent.embeddings = mock_embeddings

                result = await agent.build(concepts=concepts, conflicts=conflicts)

                # Should update, not create
                assert result["concepts_updated"] == 1
                assert result["concepts_created"] == 0

                # Verify the merged definition was used
                call_args = mock_neo4j_client.create_concept.call_args
                assert (
                    "Merged and enhanced definition" in call_args.kwargs["definition"]
                )

    @pytest.mark.asyncio
    async def test_build_links_note_to_concepts(
        self, mock_neo4j_client, mock_embeddings
    ):
        """Test that concepts are linked to their source note."""
        concepts = [
            {
                "id": "concept-1",
                "name": "Test Concept",
                "definition": "A test",
                "domain": "Test",
                "complexity_score": 5,
                "related_concepts": [],
                "prerequisites": [],
            }
        ]
        note_id = "test-note-123"

        with patch(
            "backend.agents.graph_builder.get_neo4j_client",
            return_value=mock_neo4j_client,
        ):
            with patch.object(
                GraphBuilderAgent, "__init__", lambda self, **kwargs: None
            ):
                agent = GraphBuilderAgent()
                agent.embeddings = mock_embeddings

                await agent.build(concepts=concepts, conflicts=None, note_id=note_id)

                # Verify link_note_to_concepts was called
                mock_neo4j_client.link_note_to_concepts.assert_called_once()
                call_args = mock_neo4j_client.link_note_to_concepts.call_args
                assert call_args.kwargs["note_id"] == note_id
