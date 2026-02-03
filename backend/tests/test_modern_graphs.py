"""
Functional Tests for Modern LangGraph Refactor
=============================================

This test suite verifies the functionality of the new LangGraph workflows:
1. Ingestion Graph (HITL)
2. Chat Graph (MessagesState)
3. Quiz Graph (Conditional)
4. Research Graph (ReAct)
5. Supervisor Graph (Orchestrator)

It mocks external dependencies (LLM, Neo4j, Postgres) to focus on graph logic and state transitions.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage, FunctionMessage
from langgraph.graph import StateGraph
from langgraph.types import Command

# --- Mocks for Dependencies ---

@pytest.fixture(autouse=True)
def mock_dependencies():
    """
    Patch dependencies in the target modules where they are used.
    Since modules import these symbols, we must patch them in the module namespaces.
    """
    # Create mock objects
    mock_neo4j_client = AsyncMock()
    mock_neo4j_client.execute_query = AsyncMock(return_value=[])
    mock_neo4j_client.create_concept = AsyncMock(return_value={"c": {"id": "concept-1"}})
    mock_neo4j_client.create_relationship = AsyncMock(return_value={})
    
    mock_pg_client = AsyncMock()
    mock_pg_client.fetch = AsyncMock(return_value=[])
    mock_pg_client.execute = AsyncMock(return_value=None)
    mock_pg_client.execute_insert = AsyncMock(return_value="note-1")
    mock_pg_client.execute_update = AsyncMock(return_value=None)
    mock_pg_client.execute_query = AsyncMock(return_value=[])
    
    mock_llm_instance = AsyncMock()
    mock_llm_instance.ainvoke.return_value = AIMessage(content='{"intent": "general", "entities": []}')

    mock_concept = MagicMock()
    mock_concept.model_dump.return_value = {
        "name": "A",
        "definition": "B",
        "domain": "General",
        "complexity_score": 5,
        "related_concepts": [],
        "prerequisites": [],
    }
    mock_extraction_result = MagicMock()
    mock_extraction_result.concepts = [mock_concept]

    # Patch list
    patches = [
        # Chat Graph
        patch("backend.graphs.chat_graph.get_chat_model", return_value=mock_llm_instance),
        patch("backend.graphs.chat_graph.get_neo4j_client", new_callable=AsyncMock, return_value=mock_neo4j_client),
        patch("backend.graphs.chat_graph.get_postgres_client", new_callable=AsyncMock, return_value=mock_pg_client),
        
        # Ingestion Graph
        # PATCH INSTANCES because they are initialized at module level
        patch("backend.graphs.ingestion_graph.llm_extraction", mock_llm_instance),
        patch("backend.graphs.ingestion_graph.llm_flashcard", mock_llm_instance),
        patch("backend.graphs.ingestion_graph.get_neo4j_client", new_callable=AsyncMock, return_value=mock_neo4j_client),
        patch("backend.graphs.ingestion_graph.get_postgres_client", new_callable=AsyncMock, return_value=mock_pg_client),
        patch("backend.graphs.ingestion_graph.extraction_agent.extract", new_callable=AsyncMock, return_value=mock_extraction_result),
        patch("backend.graphs.ingestion_graph.extraction_agent.extract_with_context", new_callable=AsyncMock, return_value=mock_extraction_result),
        patch("backend.graphs.ingestion_graph.content_generator.generate_mcq_batch", new_callable=AsyncMock, return_value=[]),
        
        # Quiz Graph
        patch("backend.graphs.quiz_graph.get_chat_model", return_value=mock_llm_instance),
        patch("backend.graphs.quiz_graph.get_neo4j_client", new_callable=AsyncMock, return_value=mock_neo4j_client),
        patch("backend.graphs.quiz_graph.get_postgres_client", new_callable=AsyncMock, return_value=mock_pg_client),
        
        # MCP Graph
        patch("backend.graphs.mcp_graph.get_chat_model", return_value=mock_llm_instance),
        
        # Checkpointer (Global)
        patch("backend.graphs.checkpointer.get_checkpointer", return_value=MagicMock())
    ]
    
    # Start all patches
    started = [p.start() for p in patches]
    
    yield {
        "llm": mock_llm_instance,
        "neo4j": mock_neo4j_client,
        "pg": mock_pg_client
    }
    
    # Stop all patches
    for p in reversed(patches):
        p.stop()

# Remove old individual fixtures to avoid confusion
# (The tests need to be updated to use the 'mock_dependencies' fixture)

# --- Import Graphs under test ---
# We use patch.dict to mock sys.modules? No, standard mocking of internal imports is better.
# But since graph construction happens at import time (global variables), we might need to rely on the already imported modules
# or create new instances if the graph creation functions are available.

from backend.graphs.chat_graph import create_chat_graph, ChatState
from backend.graphs.quiz_graph import create_quiz_graph
from backend.graphs.research_graph import research_agent
from backend.graphs.ingestion_graph import create_ingestion_graph, IngestionState
from backend.graphs.supervisor_graph import create_supervisor_graph, SupervisorState
from backend.graphs.mcp_graph import create_mcp_graph

@pytest.mark.asyncio
async def test_chat_graph_flow(mock_dependencies):
    """Verify Chat Graph handles a basic message flow."""
    mocks = mock_dependencies
    
    # Setup specific mock responses
    val1 = AIMessage(content='{"intent": "explain", "entities": ["LangGraph"]}')
    val2 = AIMessage(content="LangGraph is cool.")
    mocks["llm"].ainvoke.side_effect = [val1, val2]
    
    graph = create_chat_graph()
    
    res = await graph.ainvoke({
        "messages": [HumanMessage(content="Explain LangGraph")], 
        "user_id": "test"
    }, config={"configurable": {"thread_id": "1"}})
    
    assert "messages" in res
    assert isinstance(res["messages"][-1], AIMessage)
    # The intent analysis might be skipped or mocked differently depending on graph flow
    # But with our mock, analyze_query_node should return intent=explain
    assert res.get("intent") == "explain"

@pytest.mark.asyncio
async def test_quiz_graph_flow(mock_dependencies):
    """Verify Quiz Graph executes."""
    mocks = mock_dependencies
    # Setup mock for check_sufficiency
    mocks["neo4j"].execute_query.return_value = [{"name": "LangGraph"}]
    mocks["llm"].ainvoke.return_value = AIMessage(content='{"questions": []}')
    
    graph = create_quiz_graph()
    
    res = await graph.ainvoke({
        "topic": "LangGraph",
        "user_id": "test"
    }, config={"configurable": {"thread_id": "2"}})
    
    assert "questions" in res or "messages" in res

@pytest.mark.asyncio
async def test_ingestion_graph_hitl(mock_dependencies):
    """Verify Ingestion Graph handles interrupt flow."""
    mocks = mock_dependencies
    # Mock concept extraction
    mocks["llm"].ainvoke.return_value = AIMessage(content='{"concepts": [{"name": "A", "definition": "B"}]}')
    
    graph = create_ingestion_graph()
    
    res = await graph.ainvoke({
        "raw_content": "Test note",
        "user_id": "test",
        "skip_review": True
    }, config={"configurable": {"thread_id": "3"}})
    
    assert not res.get("awaiting_user_approval")
    assert "created_concept_ids" in res

@pytest.mark.asyncio
async def test_supervisor_routing(mock_dependencies):
    """Verify Supervisor routes correctly."""
    graph = create_supervisor_graph()
    
    # We explicitly patch chat_graph within supervisor_graph module for this test
    with patch("backend.graphs.supervisor_graph.chat_graph") as mock_chat:
        mock_chat.ainvoke = AsyncMock(return_value={"messages": [AIMessage("Pong")]})
        
        res = await graph.ainvoke({
            "request_type": "chat",
            "user_id": "test",
            "payload": {"message": "Hello"}
        })
        
        assert "result" in res
        assert res["result"]["response"] == "Pong"

@pytest.mark.asyncio
async def test_mcp_verification(mock_dependencies):
    """Verify MCP Graph mocks."""
    mocks = mock_dependencies
    mocks["llm"].ainvoke.return_value = AIMessage(content='{"verdict": "verified", "explanation": "It works", "sources": ["context7"]}')
    
    graph = create_mcp_graph()
    
    res = await graph.ainvoke({"claim": "LangGraph is real"})
    
    assert res["verdict"] == "verified"
