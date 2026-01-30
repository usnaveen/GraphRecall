"""Chat Router - GraphRAG Assistant Endpoints."""

from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.models.feed_schemas import ChatMessage, ChatRequest, ChatResponse
from backend.agents.graphrag_chat import GraphRAGAgent

logger = structlog.get_logger()

router = APIRouter(prefix="/api/chat", tags=["Chat Assistant"])


class QuickChatRequest(BaseModel):
    """Simple chat request without conversation history."""
    
    message: str
    user_id: str = "00000000-0000-0000-0000-000000000001"


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Chat with the GraphRAG assistant.
    
    The assistant:
    1. Analyzes your question to understand intent
    2. Searches your knowledge graph for relevant concepts
    3. Retrieves related notes using semantic search
    4. Generates a helpful response using all context
    
    Features:
    - Explains concepts from your notes
    - Compares related concepts
    - Suggests learning paths
    - Quizzes you on topics
    - Finds specific information in your notes
    
    Include conversation_history for multi-turn conversations.
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        chat_agent = GraphRAGAgent(neo4j_client, pg_client)
        
        response = await chat_agent.chat(
            user_id=request.user_id,
            message=request.message,
            conversation_history=request.conversation_history,
        )
        
        return response
        
    except Exception as e:
        logger.error("Chat: Error processing message", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quick", response_model=ChatResponse)
async def quick_chat(request: QuickChatRequest):
    """
    Quick chat without conversation history.
    
    Simplified endpoint for single-turn questions.
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        chat_agent = GraphRAGAgent(neo4j_client, pg_client)
        
        response = await chat_agent.chat(
            user_id=request.user_id,
            message=request.message,
            conversation_history=[],
        )
        
        return response
        
    except Exception as e:
        logger.error("Chat: Error processing quick message", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/suggestions")
async def get_chat_suggestions(
    user_id: str = Query(default="00000000-0000-0000-0000-000000000001"),
):
    """
    Get suggested questions based on user's knowledge graph.
    
    Returns questions like:
    - "Explain [recent concept]"
    - "Compare [concept A] and [concept B]"
    - "What should I learn before [complex concept]?"
    """
    try:
        neo4j_client = await get_neo4j_client()
        
        suggestions = []
        
        # Get some recent concepts
        recent_concepts = await neo4j_client.execute_query(
            """
            MATCH (c:Concept)
            RETURN c.name as name, c.domain as domain
            ORDER BY c.created_at DESC
            LIMIT 5
            """,
            {},
        )
        
        for concept in recent_concepts:
            suggestions.append(f"Explain {concept['name']}")
        
        # Get concepts with prerequisites
        complex_concepts = await neo4j_client.execute_query(
            """
            MATCH (c:Concept)<-[:PREREQUISITE_OF]-(prereq:Concept)
            WITH c, count(prereq) as prereq_count
            WHERE prereq_count > 0
            RETURN c.name as name
            ORDER BY prereq_count DESC
            LIMIT 3
            """,
            {},
        )
        
        for concept in complex_concepts:
            suggestions.append(f"What should I learn before {concept['name']}?")
        
        # Get related concept pairs for comparison
        related_pairs = await neo4j_client.execute_query(
            """
            MATCH (c1:Concept)-[:RELATED_TO]-(c2:Concept)
            WHERE c1.name < c2.name
            RETURN c1.name as concept1, c2.name as concept2
            LIMIT 3
            """,
            {},
        )
        
        for pair in related_pairs:
            suggestions.append(f"Compare {pair['concept1']} and {pair['concept2']}")
        
        # Add some generic suggestions
        suggestions.extend([
            "What topics should I review today?",
            "Summarize my notes on [topic]",
            "Quiz me on my weakest concepts",
        ])
        
        return {"suggestions": suggestions[:10]}
        
    except Exception as e:
        logger.error("Chat: Error getting suggestions", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# Conversation persistence endpoints

@router.get("/conversations")
async def list_conversations(
    user_id: str = Query(default="00000000-0000-0000-0000-000000000001"),
    limit: int = Query(default=20, le=50),
):
    """List recent chat conversations."""
    try:
        pg_client = await get_postgres_client()
        
        result = await pg_client.execute_query(
            """
            SELECT 
                id,
                title,
                created_at,
                updated_at,
                (SELECT COUNT(*) FROM chat_messages WHERE conversation_id = c.id) as message_count
            FROM chat_conversations c
            WHERE user_id = :user_id
            ORDER BY updated_at DESC
            LIMIT :limit
            """,
            {"user_id": user_id, "limit": limit},
        )
        
        return {"conversations": result}
        
    except Exception as e:
        logger.error("Chat: Error listing conversations", error=str(e))
        # Return empty list if table doesn't exist yet
        return {"conversations": []}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all messages."""
    try:
        pg_client = await get_postgres_client()
        
        # Get conversation
        conv_result = await pg_client.execute_query(
            """
            SELECT id, user_id, title, created_at, updated_at
            FROM chat_conversations
            WHERE id = :conversation_id
            """,
            {"conversation_id": conversation_id},
        )
        
        if not conv_result:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Get messages
        messages_result = await pg_client.execute_query(
            """
            SELECT id, role, content, sources_json, created_at
            FROM chat_messages
            WHERE conversation_id = :conversation_id
            ORDER BY created_at ASC
            """,
            {"conversation_id": conversation_id},
        )
        
        return {
            "conversation": conv_result[0],
            "messages": messages_result,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Chat: Error getting conversation", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations")
async def create_conversation(
    user_id: str = Query(default="00000000-0000-0000-0000-000000000001"),
    title: Optional[str] = None,
):
    """Create a new chat conversation."""
    try:
        pg_client = await get_postgres_client()
        
        conversation_id = await pg_client.execute_insert(
            """
            INSERT INTO chat_conversations (user_id, title)
            VALUES (:user_id, :title)
            RETURNING id
            """,
            {"user_id": user_id, "title": title or "New Conversation"},
        )
        
        return {
            "conversation_id": conversation_id,
            "title": title or "New Conversation",
        }
        
    except Exception as e:
        logger.error("Chat: Error creating conversation", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/conversations/{conversation_id}/messages")
async def add_message_to_conversation(
    conversation_id: str,
    message: str,
    user_id: str = Query(default="00000000-0000-0000-0000-000000000001"),
):
    """
    Add a message to a conversation and get AI response.
    
    This:
    1. Loads conversation history
    2. Processes the new message with GraphRAG
    3. Saves both user message and AI response
    4. Returns the AI response
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        # Get existing messages
        existing_messages = await pg_client.execute_query(
            """
            SELECT role, content
            FROM chat_messages
            WHERE conversation_id = :conversation_id
            ORDER BY created_at ASC
            """,
            {"conversation_id": conversation_id},
        )
        
        history = [
            ChatMessage(role=m["role"], content=m["content"])
            for m in existing_messages
        ]
        
        # Process with GraphRAG
        chat_agent = GraphRAGAgent(neo4j_client, pg_client)
        response = await chat_agent.chat(
            user_id=user_id,
            message=message,
            conversation_history=history,
        )
        
        # Save user message
        await pg_client.execute_insert(
            """
            INSERT INTO chat_messages (conversation_id, role, content)
            VALUES (:conversation_id, 'user', :content)
            RETURNING id
            """,
            {"conversation_id": conversation_id, "content": message},
        )
        
        # Save assistant message
        import json
        await pg_client.execute_insert(
            """
            INSERT INTO chat_messages (conversation_id, role, content, sources_json)
            VALUES (:conversation_id, 'assistant', :content, :sources)
            RETURNING id
            """,
            {
                "conversation_id": conversation_id,
                "content": response.response,
                "sources": json.dumps(response.sources),
            },
        )
        
        # Update conversation timestamp
        await pg_client.execute_insert(
            """
            UPDATE chat_conversations
            SET updated_at = NOW()
            WHERE id = :conversation_id
            """,
            {"conversation_id": conversation_id},
        )
        
        return response
        
    except Exception as e:
        logger.error("Chat: Error adding message", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
