from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from backend.graphs.chat_graph import run_chat, QueryAnalysis


@pytest.mark.asyncio
async def test_chat():
    mock_llm = MagicMock()
    structured = MagicMock()
    structured.ainvoke = AsyncMock(return_value=QueryAnalysis(intent="general", entities=[], needs_search=False))
    mock_llm.with_structured_output.return_value = structured
    
    mock_configured = MagicMock()
    mock_configured.ainvoke = AsyncMock(return_value=AIMessage(content="Spaced repetition is a learning technique."))
    mock_llm.with_config.return_value = mock_configured
    
    mock_llm.ainvoke = AsyncMock(return_value=AIMessage(content="Spaced repetition is a learning technique."))

    mock_neo4j = AsyncMock()
    mock_neo4j.execute_query.return_value = []

    mock_pg = AsyncMock()
    mock_pg.execute_query.return_value = []

    with patch("backend.graphs.chat_graph.get_chat_model", new=lambda *args, **kwargs: mock_llm), \
         patch("backend.graphs.chat_graph.get_neo4j_client", new_callable=AsyncMock, return_value=mock_neo4j), \
         patch("backend.graphs.chat_graph.get_postgres_client", new_callable=AsyncMock, return_value=mock_pg):
        response = await run_chat(
            user_id="test_user_001",
            message="What is Spaced Repetition?",
        )

    assert "response" in response
    assert "Spaced repetition" in response["response"]
