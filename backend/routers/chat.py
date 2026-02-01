"""Chat Router - GraphRAG Assistant Endpoints."""

import json
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from backend.auth.middleware import get_current_user

from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.models.feed_schemas import ChatMessage, ChatRequest, ChatResponse
# Refactor: Use new LangGraph workflow instead of legacy agent
from backend.graphs.chat_graph import chat_graph, run_chat, ChatState
from langchain_core.messages import HumanMessage

logger = structlog.get_logger()


router = APIRouter(prefix="/api/chat", tags=["Chat Assistant"])


class QuickChatRequest(BaseModel):
    """Simple chat request without conversation history."""
    
    message: str
    user_id: str


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
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
        # Refactor: Use LangGraph run_chat
        
        # Use existing conversation ID as thread_id if provided
        thread_id = None
        if request.conversation_history:
            # Note: The frontend sends history as a list, but for LangGraph we rely on 
            # server-side persistence via checkpointer. Ideally, frontend should send thread_id.
            # For this refactor, we'll treat a new proper request with thread_id in header
            # but getting it from request for now if we mock it.
            pass

        # Execute the graph
        result = await run_chat(
            user_id=str(current_user["id"]),
            message=request.message,
            thread_id=str(uuid.uuid4()) # Create new thread for single turn if no ID
        )
        
        return ChatResponse(
            response=result["response"],
            sources=result["sources"],
            related_concepts=result["related_concepts"]
        )
        
    except Exception as e:
        logger.error("Chat: Error processing message", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quick", response_model=ChatResponse)
async def quick_chat(
    request: QuickChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Quick chat without conversation history.
    
    Simplified endpoint for single-turn questions.
    """
    try:
        # Refactor: Use LangGraph run_chat
        result = await run_chat(
            user_id=str(current_user["id"]),
            message=request.message,
            thread_id=str(uuid.uuid4())
        )
        
        return ChatResponse(
            response=result["response"],
            sources=result["sources"],
            related_concepts=result["related_concepts"]
        )
        
    except Exception as e:
        logger.error("Chat: Error processing quick message", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/suggestions")
async def get_chat_suggestions(
    current_user: dict = Depends(get_current_user),
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
    current_user: dict = Depends(get_current_user),
    limit: int = Query(default=20, le=50),
):
    """List recent chat conversations."""
    try:
        pg_client = await get_postgres_client()
        
        user_id = str(current_user["id"])
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
async def get_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get a specific conversation with all messages."""
    try:
        pg_client = await get_postgres_client()
        
        user_id = str(current_user["id"])
        # Get conversation
        conv_result = await pg_client.execute_query(
            """
            SELECT id, user_id, title, created_at, updated_at
            FROM chat_conversations
            WHERE id = :conversation_id AND user_id = :user_id
            """,
            {"conversation_id": conversation_id, "user_id": user_id},
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
    current_user: dict = Depends(get_current_user),
    title: Optional[str] = None,
):
    """Create a new chat conversation."""
    try:
        pg_client = await get_postgres_client()
        
        user_id = str(current_user["id"])
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
    current_user: dict = Depends(get_current_user),
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
        
        user_id = str(current_user["id"])
        
        # Verify conversation ownership
        conv_check = await pg_client.execute_query(
            "SELECT id FROM chat_conversations WHERE id = :id AND user_id = :user_id",
            {"id": conversation_id, "user_id": user_id}
        )
        if not conv_check:
            raise HTTPException(status_code=404, detail="Conversation not found")

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
        
        # Process with LangGraph
        result = await run_chat(
            user_id=user_id,
            message=message,
            thread_id=conversation_id  # Use conversation_id as thread_id for persistence
        )
        
        response_text = result["response"]
        sources = result.get("sources", [])
        
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
                "content": response_text,
                "sources": json.dumps(sources),
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
        
        # Return compatible response format
        return ChatResponse(
            response=response_text,
            sources=sources or [],
            related_concepts=result.get("related_concepts", [])
        )
        
    except Exception as e:
        logger.error("Chat: Error adding message", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Save Message for Quiz & Add to Knowledge Base
# ============================================================================


class SaveMessageRequest(BaseModel):
    """Request to save a message for quiz generation."""
    topic: Optional[str] = None


@router.post("/messages/{message_id}/save")
async def save_message_for_quiz(
    message_id: str,
    request: SaveMessageRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Save a chat response for future quiz generation.
    
    Use this when long-pressing a message in the chat UI.
    The saved content can be used to generate quiz questions.
    """
    try:
        pg_client = await get_postgres_client()
        
        user_id = str(current_user["id"])
        # Get the message content and verify ownership via join
        message = await pg_client.execute_query(
            """
            SELECT cm.content, cm.role, cc.title as conversation_title
            FROM chat_messages cm
            JOIN chat_conversations cc ON cc.id = cm.conversation_id
            WHERE cm.id = :message_id AND cc.user_id = :user_id
            """,
            {"message_id": message_id, "user_id": user_id}
        )
        
        if not message:
            raise HTTPException(status_code=404, detail="Message not found")
        
        msg = message[0]
        
        # Mark as saved in chat_messages
        await pg_client.execute_query(
            "UPDATE chat_messages SET is_saved_for_quiz = TRUE WHERE id = :message_id",
            {"message_id": message_id}
        )
        
        # Create saved_response entry
        saved_id = str(uuid.uuid4())
        topic = request.topic or msg.get("conversation_title") or "Chat Response"
        
        await pg_client.execute_insert(
            """
            INSERT INTO saved_responses (id, user_id, message_id, topic, content)
            VALUES (:id, :user_id, :message_id, :topic, :content)
            """,
            {
                "id": saved_id,
                "user_id": user_id,
                "message_id": message_id,
                "topic": topic,
                "content": msg.get("content", ""),
            }
        )
        
        logger.info("save_message_for_quiz", message_id=message_id, saved_id=saved_id)
        
        return {
            "saved_id": saved_id,
            "message_id": message_id,
            "topic": topic,
            "status": "saved",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Chat: Error saving message", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


class AddToKnowledgeRequest(BaseModel):
    """Request to add conversation to knowledge base."""
    title: Optional[str] = None


@router.post("/conversations/{conversation_id}/to-knowledge")
async def add_conversation_to_knowledge(
    conversation_id: str,
    request: AddToKnowledgeRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Add a chat conversation to the knowledge base.
    
    This:
    1. Summarizes the conversation
    2. Creates a note with resource_type='chat_conversation'
    3. Extracts and links key concepts
    4. Marks the conversation as saved
    
    Use this from the three-dot menu in the chat UI.
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        user_id = str(current_user["id"])
        
        # Get conversation messages and verify ownership
        messages = await pg_client.execute_query(
            """
            SELECT cm.role, cm.content, cm.created_at
            FROM chat_messages cm
            JOIN chat_conversations cc ON cc.id = cm.conversation_id
            WHERE cm.conversation_id = :conversation_id AND cc.user_id = :user_id
            ORDER BY cm.created_at ASC
            """,
            {"conversation_id": conversation_id, "user_id": user_id}
        )
        
        if not messages:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Get conversation details
        conv = await pg_client.execute_query(
            "SELECT title FROM chat_conversations WHERE id = :id",
            {"id": conversation_id}
        )
        
        conv_title = request.title or (conv[0].get("title") if conv else "Chat Conversation")
        
        # Build conversation transcript
        transcript = f"# {conv_title}\n\n"
        for msg in messages:
            role = "**You**" if msg["role"] == "user" else "**Assistant**"
            transcript += f"{role}: {msg['content']}\n\n"
        
        # Create note
        note_id = str(uuid.uuid4())
        
        await pg_client.execute_insert(
            """
            INSERT INTO notes (id, user_id, title, content_text, resource_type, content_type)
            VALUES (:id, :user_id, :title, :content_text, :resource_type, :content_type)
            """,
            {
                "id": note_id,
                "user_id": user_id,
                "title": conv_title,
                "content_text": transcript,
                "resource_type": "chat_conversation",
                "content_type": "markdown",
            }
        )
        
        # Mark conversation as saved
        summary = f"Conversation with {len(messages)} messages about {conv_title}"
        
        await pg_client.execute_query(
            """
            UPDATE chat_conversations 
            SET is_saved_to_knowledge = TRUE, summary = :summary
            WHERE id = :id
            """,
            {"id": conversation_id, "summary": summary}
        )
        
        # Extract key topics for Neo4j linking (simple keyword extraction)
        from backend.config.llm import get_chat_model
        
        try:
            llm = get_chat_model(temperature=0)
            
            # Quick topic extraction
            resp = await llm.ainvoke(
                f"Extract 3-5 key topic names from this conversation. Return only comma-separated topic names:\n\n{transcript[:2000]}"
            )
            topics = [t.strip() for t in resp.content.split(",")][:5]
            
            # Link to concepts in Neo4j
            for topic in topics:
                await neo4j_client.execute_query(
                    """
                    MATCH (c:Concept)
                    WHERE toLower(c.name) CONTAINS toLower($topic)
                    MERGE (n:NoteSource {id: $note_id})
                    SET n.note_id = $note_id, n.summary = $summary
                    MERGE (n)-[:EXPLAINS {relevance: 0.7}]->(c)
                    """,
                    {"note_id": note_id, "topic": topic, "summary": summary}
                )
        except Exception as topic_err:
            logger.warning("Topic extraction failed (optional)", error=str(topic_err))
        
        logger.info(
            "add_conversation_to_knowledge",
            conversation_id=conversation_id,
            note_id=note_id,
        )
        
        return {
            "note_id": note_id,
            "conversation_id": conversation_id,
            "title": conv_title,
            "message_count": len(messages),
            "status": "saved_to_knowledge",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Chat: Error adding to knowledge", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Chat History
# ============================================================================


@router.get("/history")
async def get_chat_history(
    current_user: dict = Depends(get_current_user),
    limit: int = Query(default=20, le=50),
):
    """
    Get recent chat conversations with preview.
    """
    try:
        pg_client = await get_postgres_client()
        
        user_id = str(current_user["id"])
        result = await pg_client.execute_query(
            """
            SELECT 
                c.id,
                c.title,
                c.created_at,
                c.updated_at,
                c.is_saved_to_knowledge,
                c.summary,
                (SELECT content FROM chat_messages 
                 WHERE conversation_id = c.id 
                 ORDER BY created_at DESC LIMIT 1) as last_message,
                (SELECT COUNT(*) FROM chat_messages WHERE conversation_id = c.id) as message_count
            FROM chat_conversations c
            WHERE c.user_id = :user_id
            ORDER BY c.updated_at DESC
            LIMIT :limit
            """,
            {"user_id": user_id, "limit": limit}
        )
        
        conversations = [
            {
                "id": str(row["id"]),
                "title": row["title"],
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "is_saved_to_knowledge": row["is_saved_to_knowledge"],
                "summary": row.get("summary"),
                "last_message": row.get("last_message", "")[:100] + "...",
                "message_count": row.get("message_count", 0),
            }
            for row in result
        ]
        
        return {"conversations": conversations, "total": len(conversations)}
        
    except Exception as e:
        logger.error("Chat: Error getting history", error=str(e))
        return {"conversations": [], "total": 0}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a chat conversation and all its messages."""
    try:
        user_id = str(current_user["id"])
        pg_client = await get_postgres_client()
        
        await pg_client.execute_query(
            "DELETE FROM chat_conversations WHERE id = :id AND user_id = :user_id",
            {"id": conversation_id, "user_id": user_id}
        )
        
        return {"status": "deleted", "conversation_id": conversation_id}
        
    except Exception as e:
        logger.error("Chat: Error deleting conversation", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Streaming Chat (SSE)
# ============================================================================


@router.post("/stream")
async def stream_chat(
    request: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Stream chat responses using Server-Sent Events.
    
    The response is streamed in chunks as the AI generates it,
    providing a more responsive user experience.
    """
    async def generate():
        try:
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}
            
            user_id = str(current_user["id"])
            initial_state: ChatState = {
                "messages": [HumanMessage(content=request.message)],
                "user_id": user_id,
                "graph_context": {},
                "rag_context": [],
            }
            
            # Streaming Loop using astream_events (LangGraph 1.0+)
            # Using version="v2" for standard event format
            async for event in chat_graph.astream_events(initial_state, config, version="v2"):
                
                kind = event["event"]
                
                # Stream partial tokens from the LLM
                if kind == "on_chat_model_stream":
                    content = event["data"]["chunk"].content
                    if content:
                        yield f"data: {json.dumps({'type': 'chunk', 'content': content})}\n\n"
                
                # Notify about tool usage (searching graph/notes)
                elif kind == "on_tool_start":
                    yield f"data: {json.dumps({'type': 'status', 'content': f'Using tool: {event['name']}...'})}\n\n"
                    
                # Monitor node transitions (for debug/UI)
                elif kind == "on_chain_start" and event["name"] in ["analyze_query", "get_context", "generate_response"]:
                    yield f"data: {json.dumps({'type': 'status', 'content': f'Step: {event['name']}...'})}\n\n"

            # Get final state for metadata
            final_state = await chat_graph.aget_state(config)
            values = final_state.values
            
            related_concepts = values.get("related_concepts", [])
            sources = values.get("sources", [])
            
            # Send final event with metadata
            yield f"data: {json.dumps({'type': 'done', 'sources': sources, 'related_concepts': related_concepts})}\n\n"
            
        except Exception as e:
            logger.error("Stream chat: Error", error=str(e))
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
    
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

