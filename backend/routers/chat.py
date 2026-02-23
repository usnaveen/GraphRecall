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
        # Use existing conversation ID as thread_id for multi-turn persistence
        thread_id = request.conversation_id or str(uuid.uuid4())

        # Execute the graph
        result = await run_chat(
            user_id=str(current_user["id"]),
            message=request.message,
            thread_id=thread_id,
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
        user_id = str(current_user["id"])

        suggestions = []

        # Get some recent concepts
        recent_concepts = await neo4j_client.execute_query(
            """
            MATCH (c:Concept {user_id: $user_id})
            RETURN c.name as name, c.domain as domain
            ORDER BY c.created_at DESC
            LIMIT 5
            """,
            {"user_id": user_id},
        )

        for concept in recent_concepts:
            suggestions.append(f"Explain {concept['name']}")

        # Get concepts with prerequisites
        complex_concepts = await neo4j_client.execute_query(
            """
            MATCH (c:Concept {user_id: $user_id})<-[:PREREQUISITE_OF]-(prereq:Concept {user_id: $user_id})
            WITH c, count(prereq) as prereq_count
            WHERE prereq_count > 0
            RETURN c.name as name
            ORDER BY prereq_count DESC
            LIMIT 3
            """,
            {"user_id": user_id},
        )

        for concept in complex_concepts:
            suggestions.append(f"What should I learn before {concept['name']}?")

        # Get related concept pairs for comparison
        related_pairs = await neo4j_client.execute_query(
            """
            MATCH (c1:Concept {user_id: $user_id})-[:RELATED_TO]-(c2:Concept {user_id: $user_id})
            WHERE c1.name < c2.name
            RETURN c1.name as concept1, c2.name as concept2
            LIMIT 3
            """,
            {"user_id": user_id},
        )
        
        for pair in related_pairs:
            suggestions.append(f"Compare {pair['concept1']} and {pair['concept2']}")
        
        # Add some generic suggestions
        suggestions.extend([
            "What topics should I review today?",
            "Summarize my notes on [topic]",
            "Show me images related to...",
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

        # Serialize UUID/datetime fields for JSON
        messages = [
            {
                "id": str(m["id"]),
                "role": m["role"],
                "content": m["content"],
                "sources_json": m.get("sources_json") or [],
                "created_at": str(m.get("created_at", "")),
            }
            for m in messages_result
        ]

        conv = conv_result[0]
        return {
            "conversation": {
                "id": str(conv["id"]),
                "title": conv.get("title") or "New Chat",
                "created_at": str(conv.get("created_at", "")),
                "updated_at": str(conv.get("updated_at", "")),
            },
            "messages": messages,
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
        await pg_client.execute_update(
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
        await pg_client.execute_update(
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


class CreateCardRequest(BaseModel):
    """Request to create a quiz or concept card from a chat message."""
    output_type: str = "quiz"  # "quiz" or "concept_card"
    topic: Optional[str] = None


@router.post("/messages/{message_id}/create-card")
async def create_card_from_message(
    message_id: str,
    request: CreateCardRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Create a quiz question or concept card from a chat message.

    output_type:
      - "quiz": generates an MCQ from the message content
      - "concept_card": generates a flashcard from the message content

    Returns the created item so the frontend can prepend it to the feed.
    """
    try:
        pg_client = await get_postgres_client()
        user_id = str(current_user["id"])

        # Get the message content
        message = await pg_client.execute_query(
            """
            SELECT cm.content, cm.role, cc.title as conversation_title
            FROM chat_messages cm
            JOIN chat_conversations cc ON cc.id = cm.conversation_id
            WHERE cm.id = :message_id AND cc.user_id = :user_id
            """,
            {"message_id": message_id, "user_id": user_id},
        )

        if not message:
            raise HTTPException(status_code=404, detail="Message not found")

        msg = message[0]
        content = msg.get("content", "")
        topic = request.topic or msg.get("conversation_title") or "Chat Response"

        from backend.agents.content_generator import ContentGeneratorAgent
        generator = ContentGeneratorAgent()

        item_id = str(uuid.uuid4())

        if request.output_type == "concept_card":
            # Generate a flashcard
            cards = await generator.generate_flashcards(
                concept_name=topic,
                concept_definition=content[:3000],
                related_concepts=[],
                num_cards=1,
            )
            if not cards:
                raise HTTPException(status_code=500, detail="Failed to generate flashcard")

            card = cards[0]
            front = card.get("front") or card.get("term") or topic
            back = card.get("back") or card.get("definition") or content[:500]

            await pg_client.execute_insert(
                """
                INSERT INTO flashcards (id, user_id, concept_id, front_content, back_content, created_at, source)
                VALUES (:id, :uid, NULL, :front, :back, NOW(), 'chat_message')
                RETURNING id
                """,
                {"id": item_id, "uid": user_id, "front": front, "back": back},
            )

            return {
                "id": item_id,
                "type": "flashcard",
                "front_content": front,
                "back_content": back,
                "topic": topic,
                "source": "chat_message",
            }

        else:
            # Generate MCQ
            mcq = await generator.generate_mcq(
                concept_name=topic,
                concept_definition=content[:3000],
                related_concepts=[],
                difficulty=5,
            )

            options_json = json.dumps([
                {"id": opt.id, "text": opt.text, "is_correct": opt.is_correct}
                for opt in mcq.options
            ])
            correct = next((o.text for o in mcq.options if o.is_correct), "")

            await pg_client.execute_insert(
                """
                INSERT INTO quizzes (id, user_id, concept_id, question_text, question_type,
                                     options_json, correct_answer, explanation, created_at, source)
                VALUES (:id, :uid, NULL, :q_text, 'mcq', :opts, :correct, :exp, NOW(), 'chat_message')
                RETURNING id
                """,
                {
                    "id": item_id,
                    "uid": user_id,
                    "q_text": mcq.question,
                    "opts": options_json,
                    "correct": correct,
                    "exp": mcq.explanation,
                },
            )

            return {
                "id": item_id,
                "type": "quiz",
                "question_text": mcq.question,
                "question_type": "mcq",
                "options": [
                    {"id": o.id, "text": o.text, "is_correct": o.is_correct}
                    for o in mcq.options
                ],
                "correct_answer": correct,
                "explanation": mcq.explanation,
                "topic": topic,
                "source": "chat_message",
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Chat: Error creating card from message", error=str(e))
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
        
        # Create note content
        transcript = f"# {conv_title}\n\n"
        for msg in messages:
            role = "**You**" if msg["role"] == "user" else "**Assistant**"
            transcript += f"{role}: {msg['content']}\n\n"
        
        # Use centralized Ingestion Workflow
        # This triggers: Extraction -> Synthesis (Review) -> Linking -> Flashcards -> Quizzes
        from backend.graphs.ingestion_graph import run_ingestion
        
        ingest_result = await run_ingestion(
            content=transcript,
            title=conv_title,
            user_id=user_id,
            skip_review=False, # User wants to review concepts
        )
        
        note_id = ingest_result.get("note_id")
        
        # Mark conversation as saved to knowledge
        summary = f"Conversation with {len(messages)} messages about {conv_title}"
        await pg_client.execute_update(
            """
            UPDATE chat_conversations 
            SET is_saved_to_knowledge = TRUE, summary = :summary
            WHERE id = :id
            """,
            {"id": conversation_id, "summary": summary}
        )
        
        logger.info(
            "add_conversation_to_knowledge: Handed off to ingestion graph",
            conversation_id=conversation_id,
            note_id=note_id,
            status=ingest_result.get("status")
        )
        
        return {
            "note_id": note_id,
            "conversation_id": conversation_id,
            "title": conv_title,
            "message_count": len(messages),
            "status": ingest_result.get("status", "processing"),
            "concepts_found": len(ingest_result.get("concepts", [])),
            "awaiting_review": ingest_result.get("status") == "awaiting_review"
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
                "title": row["title"] or "New Chat",
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "is_saved_to_knowledge": row.get("is_saved_to_knowledge", False),
                "summary": row.get("summary"),
                "last_message": ((row.get("last_message") or "")[:100] + "..."),
                "message_count": row.get("message_count") or 0,
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
        
        await pg_client.execute_update(
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
            pg_client = await get_postgres_client()
            user_id = str(current_user["id"])

            # Resolve or create conversation
            conversation_id = request.conversation_id
            if conversation_id:
                conv_check = await pg_client.execute_query(
                    "SELECT id FROM chat_conversations WHERE id = :id AND user_id = :user_id",
                    {"id": conversation_id, "user_id": user_id},
                )
                if not conv_check:
                    conversation_id = None

            if not conversation_id:
                title = (request.message[:60] + "...") if len(request.message) > 60 else request.message
                conversation_id = await pg_client.execute_insert(
                    """
                    INSERT INTO chat_conversations (user_id, title)
                    VALUES (:user_id, :title)
                    RETURNING id
                    """,
                    {"user_id": user_id, "title": title or "New Conversation"},
                )
            if not conversation_id:
                raise RuntimeError("Failed to create conversation")

            thread_id = conversation_id or str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}

            # Save user message immediately
            await pg_client.execute_insert(
                """
                INSERT INTO chat_messages (conversation_id, role, content)
                VALUES (:conversation_id, 'user', :content)
                RETURNING id
                """,
                {"conversation_id": conversation_id, "content": request.message},
            )

            initial_state: ChatState = {
                "messages": [HumanMessage(content=request.message)],
                "user_id": user_id,
                "focused_source_ids": getattr(request, 'source_ids', None) or [],  # Source-scoped filtering
                "graph_context": {},
                "rag_context": [],
            }
            
            # Streaming Loop using astream_events (LangGraph 1.0+)
            # Using version="v2" for standard event format
            full_content = ""

            async for event in chat_graph.astream_events(initial_state, config, version="v2"):
                
                kind = event["event"]
                
                # Stream partial tokens from the LLM
                if kind == "on_chat_model_stream":
                    tags = event.get("tags", [])
                    content = event["data"]["chunk"].content
                    if not content:
                        continue
                        
                    # Only append to main message content if it's the final response
                    if "final_response" in tags:
                        full_content += content
                        yield f"data: {json.dumps({'type': 'chunk', 'content': content})}\n\n"
                    else:
                        # Otherwise, send as a status update (keeps the "loading" feel but clean)
                        # This avoids the "JSON in message" problem
                        yield f"data: {json.dumps({'type': 'status', 'content': 'Analyzing intent...'})}\n\n"
                
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

            # Inject images that weren't streamed (post-processing added them after streaming)
            # The generate_response_node may have appended images to the response content
            # but those weren't part of the streaming tokens. Check and send them.
            final_messages = values.get("messages", [])
            if final_messages:
                last_msg = final_messages[-1]
                final_content = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)
                # If the final content has more than what was streamed, send the extra
                if len(final_content) > len(full_content) and full_content:
                    extra_content = final_content[len(full_content):]
                    if extra_content.strip():
                        yield f"data: {json.dumps({'type': 'chunk', 'content': extra_content})}\n\n"
                        full_content = final_content

            # Fix: Ensure UUIDs are strings for JSON serialization
            def json_safe(obj):
                if isinstance(obj, uuid.UUID):
                    return str(obj)
                return obj

            # Persist assistant message
            assistant_message_id = await pg_client.execute_insert(
                """
                INSERT INTO chat_messages (conversation_id, role, content, sources_json)
                VALUES (:conversation_id, 'assistant', :content, :sources)
                RETURNING id
                """,
                {
                    "conversation_id": conversation_id,
                    "content": full_content,
                    "sources": json.dumps(sources),
                },
            )

            # Update conversation timestamp
            await pg_client.execute_update(
                """
                UPDATE chat_conversations
                SET updated_at = NOW()
                WHERE id = :conversation_id
                """,
                {"conversation_id": conversation_id},
            )

            # Send final event with metadata
            metadata = values.get("metadata", {})
            final_data = {
                'type': 'done',
                'sources': sources,
                'related_concepts': related_concepts,
                'metadata': metadata,
                'message_id': assistant_message_id,
                'conversation_id': conversation_id,
            }
            yield f"data: {json.dumps(final_data, default=json_safe)}\n\n"
            
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
