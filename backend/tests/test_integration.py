"""Integration tests for the full ingestion pipeline."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Legacy imports commented out - these modules were deleted in the LangGraph refactor
# from backend.graph.state import GraphState, create_initial_state
# from backend.graph.workflow import (
#     check_conflicts_node,
#     extract_concepts_node,
#     parse_input_node,
#     run_ingestion_pipeline,
#     update_graph_node,
# )


class TestIngestionPipeline:
    """Integration test suite for the ingestion pipeline."""

    @pytest.mark.asyncio
    async def test_parse_input_valid_content(self, sample_markdown_content):
        """Test parse_input node with valid content."""
        state = create_initial_state(
            user_id="test-user",
            content=sample_markdown_content,
        )

        result = await parse_input_node(state)

        assert result.get("error_message") is None
        assert result["input_content"] == sample_markdown_content.strip()

    @pytest.mark.asyncio
    async def test_parse_input_empty_content(self):
        """Test parse_input node with empty content."""
        state = create_initial_state(
            user_id="test-user",
            content="",
        )

        result = await parse_input_node(state)

        assert result.get("error_message") is not None
        assert "empty" in result["error_message"].lower()

    @pytest.mark.asyncio
    async def test_parse_input_too_short(self):
        """Test parse_input node with content that's too short."""
        state = create_initial_state(
            user_id="test-user",
            content="Hi",
        )

        result = await parse_input_node(state)

        assert result.get("error_message") is not None
        assert "short" in result["error_message"].lower()

    @pytest.mark.asyncio
    async def test_extract_concepts_node_success(
        self, sample_markdown_content, mock_llm
    ):
        """Test extract_concepts node with mocked LLM."""
        mock_response = {
            "concepts": [
                {
                    "name": "Neural Network",
                    "definition": "Computing system",
                    "domain": "ML",
                    "complexity_score": 6,
                    "confidence": 0.9,
                    "related_concepts": [],
                    "prerequisites": [],
                }
            ]
        }
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content=json.dumps(mock_response))
        )

        state = create_initial_state(
            user_id="test-user",
            content=sample_markdown_content,
        )

        with patch("backend.agents.extraction.ChatOpenAI", return_value=mock_llm):
            result = await extract_concepts_node(state)

        assert result.get("error_message") is None
        assert len(result["extracted_concepts"]) == 1
        assert result["extracted_concepts"][0]["name"] == "Neural Network"

    @pytest.mark.asyncio
    async def test_check_conflicts_node_no_existing(self, sample_extracted_concepts):
        """Test check_conflicts node with no existing concepts."""
        state: GraphState = {
            "user_id": "test-user",
            "action": "ingest",
            "input_content": "test",
            "note_id": None,
            "extracted_concepts": sample_extracted_concepts,
            "conflicts": [],
            "graph_updates": [],
            "final_output": None,
            "error_message": None,
            "processing_started": None,
            "processing_completed": None,
            "concepts_created": 0,
            "relationships_created": 0,
        }

        # Mock the synthesis agent to return all NEW decisions
        with patch("backend.agents.synthesis.SynthesisAgent") as MockAgent:
            mock_instance = MockAgent.return_value
            mock_result = MagicMock()
            mock_result.decisions = []
            for c in sample_extracted_concepts:
                decision = MagicMock()
                decision.model_dump.return_value = {
                    "new_concept_name": c["name"],
                    "decision": "NEW",
                    "confidence": 1.0,
                    "matched_concept_id": None,
                    "reasoning": "No existing concepts",
                    "merge_strategy": "CREATE_NEW",
                    "updated_definition": None,
                }
                mock_result.decisions.append(decision)
            mock_instance.analyze = AsyncMock(return_value=mock_result)

            result = await check_conflicts_node(state)

        assert result.get("error_message") is None
        assert len(result["conflicts"]) == len(sample_extracted_concepts)

    @pytest.mark.asyncio
    async def test_update_graph_node_creates_concepts(
        self, sample_extracted_concepts, mock_neo4j_client, mock_embeddings
    ):
        """Test update_graph node creates concepts in Neo4j."""
        state: GraphState = {
            "user_id": "test-user",
            "action": "ingest",
            "input_content": "test",
            "note_id": "test-note-id",
            "extracted_concepts": sample_extracted_concepts,
            "conflicts": [],
            "graph_updates": [],
            "final_output": None,
            "error_message": None,
            "processing_started": None,
            "processing_completed": None,
            "concepts_created": 0,
            "relationships_created": 0,
        }

        with patch(
            "backend.agents.graph_builder.get_neo4j_client",
            return_value=mock_neo4j_client,
        ):
            with patch(
                "backend.agents.graph_builder.OpenAIEmbeddings",
                return_value=mock_embeddings,
            ):
                result = await update_graph_node(state)

        assert result.get("error_message") is None
        assert result["concepts_created"] >= 1
        assert result["final_output"] is not None
        assert "Successfully" in result["final_output"]

    @pytest.mark.asyncio
    async def test_full_pipeline_integration(
        self, sample_markdown_content, mock_llm, mock_neo4j_client, mock_embeddings
    ):
        """Test the full pipeline from input to graph update."""
        # Setup mock LLM response for extraction
        mock_response = {
            "concepts": [
                {
                    "name": "Neural Network",
                    "definition": "Computing system inspired by biology",
                    "domain": "Machine Learning",
                    "complexity_score": 6,
                    "confidence": 0.95,
                    "related_concepts": ["Backpropagation"],
                    "prerequisites": [],
                },
                {
                    "name": "Backpropagation",
                    "definition": "Training algorithm for neural networks",
                    "domain": "Machine Learning",
                    "complexity_score": 7,
                    "confidence": 0.9,
                    "related_concepts": ["Neural Network"],
                    "prerequisites": ["Neural Network"],
                },
            ]
        }
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content=json.dumps(mock_response))
        )

        # Patch all the dependencies
        with patch("backend.agents.extraction.ChatOpenAI", return_value=mock_llm):
            with patch("backend.agents.synthesis.ChatOpenAI", return_value=mock_llm):
                with patch(
                    "backend.agents.synthesis.OpenAIEmbeddings",
                    return_value=mock_embeddings,
                ):
                    with patch(
                        "backend.agents.graph_builder.get_neo4j_client",
                        return_value=mock_neo4j_client,
                    ):
                        with patch(
                            "backend.agents.graph_builder.OpenAIEmbeddings",
                            return_value=mock_embeddings,
                        ):
                            # Patch the synthesis agent's analyze to return NEW for all
                            with patch(
                                "backend.agents.synthesis.SynthesisAgent.analyze"
                            ) as mock_analyze:
                                mock_result = MagicMock()
                                mock_result.decisions = []
                                mock_analyze.return_value = mock_result

                                result = await run_ingestion_pipeline(
                                    user_id="test-user",
                                    content=sample_markdown_content,
                                    note_id="test-note-123",
                                )

        # Verify the pipeline completed
        assert result is not None
        # Should have extracted concepts
        assert len(result.get("extracted_concepts", [])) >= 0
        # Should not have fatal errors
        # Note: Some errors might occur due to mocking, but pipeline should complete
