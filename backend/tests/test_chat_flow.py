from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from backend.graphs.chat_graph import run_chat


@pytest.mark.asyncio
async def test_chat():
    mock_llm = AsyncMock()
    mock_llm.ainvoke.side_effect = [
        AIMessage(content='{"intent": "general", "entities": []}'),
        AIMessage(content="Spaced repetition is a learning technique."),
    ]

    mock_neo4j = AsyncMock()
    mock_neo4j.execute_query.return_value = []

    mock_pg = AsyncMock()
    mock_pg.execute_query.return_value = []

    with patch("backend.graphs.chat_graph.get_chat_model", return_value=mock_llm), \
         patch("backend.graphs.chat_graph.get_neo4j_client", new_callable=AsyncMock, return_value=mock_neo4j), \
         patch("backend.graphs.chat_graph.get_postgres_client", new_callable=AsyncMock, return_value=mock_pg):
        response = await run_chat(
            user_id="test_user_001",
            message="What is Spaced Repetition?",
        )

    assert "response" in response
    assert "Spaced repetition" in response["response"]
