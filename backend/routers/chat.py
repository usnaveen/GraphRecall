"""Chat Router - GraphRAG Assistant Endpoints."""

import json
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

import structlog

from backend.graphs.thread_ids import chat_thread_id
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from backend.auth.middleware import get_current_user
from backend.services.followups import suggest_followups, suggestion_click_meta
from backend.services.quota import require_quota

from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.models.feed_schemas import ChatMessage, ChatRequest, ChatResponse
# Refactor: Use new LangGraph workflow instead of legacy agent
from backend.services.output_guard import StreamingImageGuard, allowed_image_urls
from backend.graphs.chat_graph import chat_graph, run_chat, ChatState
from backend.telemetry import elapsed_ms, now, record
from langchain_core.messages import HumanMessage

logger = structlog.get_logger()



def message_meta(related_concepts: list, metadata: dict) -> dict:
    """The part of a chat answer's grounding worth keeping: concept names and a retrieval summary.
    No scores, document text or internal stats."""
    names = []
    for c in related_concepts or []:
        name = c.get("name") if isinstance(c, dict) else c
        if isinstance(name, str) and name.strip() and name not in names:
            names.append(name.strip())
    md = metadata or {}
    out = {
        "related_concepts": names[:12],
        "retrieval": {
            "intent": md.get("intent"),
            "documents": md.get("documents_retrieved"),
            "concepts": md.get("nodes_retrieved"),
            "entities": [e for e in (md.get("entities") or []) if isinstance(e, str)][:8],
        },
    }
    # Which prompt version, model and reranker produced the answer, and why the guard decided as it
    # did: what you need to trace a quality change back to a release.
    generation = {
        "prompt_version": md.get("prompt_version"),
        "model": md.get("model"),
        "learner_state_used": md.get("learner_state_used"),
        "reranker": (md.get("rerank_stats") or {}).get("method"),
        "grounding": (md.get("grounding") or {}).get("reason"),
    }
    outcomes = answer_outcomes(md)
    if outcomes:
        generation["outcomes"] = outcomes
    if any(v is not None for v in generation.values()):
        out["generation"] = generation
    return out


def answer_outcomes(md: dict) -> list[str]:
    """Failure taxonomy for one answer, from its own metadata (no extra work at request time):

    no_retrieval        neither notes nor concepts were found
    abstained           the grounding guard judged the context insufficient or off-topic
    citations_stripped  the model cited sources it was not given, and they were removed
    reranker_fallback   the lexical reranker ran instead of the cross-encoder
    cache_hit           served from the answer cache
    """
    md = md or {}
    grounding = md.get("grounding") or {}
    rerank = (md.get("rerank_stats") or {}).get("method")
    tags = []
    if md.get("documents_retrieved") == 0 and md.get("nodes_retrieved") == 0:
        tags.append("no_retrieval")
    if grounding.get("should_abstain"):
        tags.append("abstained")
    if grounding.get("invalid_refs"):
        tags.append("citations_stripped")
    if rerank and rerank != "onnx_cross_encoder":
        tags.append("reranker_fallback")
    if md.get("cache_hit"):
        tags.append("cache_hit")
    return tags

router = APIRouter(prefix="/api/chat", tags=["Chat Assistant"])


class QuickChatRequest(BaseModel):
    """Simple chat request without conversation history."""
    
    message: str
    user_id: str



def finalize_stream_text(streamed: str, final: str) -> tuple[list[dict], str]:
    """Events to send after the token stream, and the text to save.

    - nothing was streamed (cache hit, quiz short-circuit): send the final text as one chunk;
    - the final text continues the stream (figures appended): send only the tail;
    - the final text differs (invalid citations removed after streaming): send one "replace" event,
      so the client shows and the database stores the same cleaned text.
    """
    if not final:
        return [], streamed
    if not streamed:
        return [{"type": "chunk", "content": final}], final
    if final == streamed:
        return [], streamed
    if final.startswith(streamed):
        tail = final[len(streamed):]
        return ([{"type": "chunk", "content": tail}] if tail.strip() else []), final
    return [{"type": "replace", "content": final}], final

@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: dict = Depends(require_quota("chat")),
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
        user_id = str(current_user["id"])
        # Multi-turn: the conversation must be the caller's own (GR-SEC-03), and its checkpoint
        # thread lives in the caller's namespace, so another user's id can't load their history.
        if request.conversation_id:
            pg_client = await get_postgres_client()
            owned = await pg_client.execute_query(
                "SELECT id FROM chat_conversations WHERE id = :id AND user_id = :user_id",
                {"id": request.conversation_id, "user_id": user_id},
            )
            if not owned:
                raise HTTPException(status_code=404, detail="Conversation not found")
        thread_id = chat_thread_id(user_id, request.conversation_id)

        # Execute the graph
        result = await run_chat(
            user_id=user_id,
            message=request.message,
            thread_id=thread_id,
        )
        
        return ChatResponse(
            response=result["response"],
            sources=result["sources"],
            related_concepts=result["related_concepts"]
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Chat: Error processing message", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/quick", response_model=ChatResponse)
async def quick_chat(
    request: QuickChatRequest,
    current_user: dict = Depends(require_quota("chat")),
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
            thread_id=chat_thread_id(str(current_user["id"]))
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
            SELECT id, role, content, sources_json, meta_json, created_at
            FROM chat_messages
            WHERE conversation_id = :conversation_id
              AND conversation_id IN (SELECT id FROM chat_conversations WHERE user_id = :user_id)
            ORDER BY created_at ASC
            """,
            {"conversation_id": conversation_id, "user_id": user_id},
        )

        # Serialize UUID/datetime fields for JSON
        messages = [
            {
                "id": str(m["id"]),
                "role": m["role"],
                "content": m["content"],
                "sources_json": m.get("sources_json") or [],
                "related_concepts": (m.get("meta_json") or {}).get("related_concepts", []),
                "retrieval": (m.get("meta_json") or {}).get("retrieval"),
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
    current_user: dict = Depends(require_quota("chat")),
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
            thread_id=chat_thread_id(user_id, conversation_id),
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
            INSERT INTO chat_messages (conversation_id, role, content, sources_json, meta_json)
            VALUES (:conversation_id, 'assistant', :content, :sources, CAST(:meta AS jsonb))
            RETURNING id
            """,
            {
                "conversation_id": conversation_id,
                "content": response_text,
                "sources": json.dumps(sources),
                "meta": json.dumps(message_meta(result.get("related_concepts", []), result.get("metadata") or {}), default=str),
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
        
        deleted = await pg_client.execute_query(
            "DELETE FROM chat_conversations WHERE id = :id AND user_id = :user_id RETURNING id",
            {"id": conversation_id, "user_id": user_id}
        )
        if deleted:
            # The checkpoint thread holds the full message history and retrieved note text too.
            try:
                from backend.graphs.checkpointer import get_checkpointer

                await get_checkpointer().adelete_thread(chat_thread_id(user_id, conversation_id))
            except Exception as e:  # noqa: BLE001  (best effort; account deletion sweeps the rest)
                logger.warning("Chat: checkpoint thread not deleted", error=str(e))
        
        return {"status": "deleted", "conversation_id": conversation_id}
        
    except Exception as e:
        logger.error("Chat: Error deleting conversation", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Streaming Chat (SSE)
# ============================================================================


# TODO(agent-bridge): "Ask my agent" handoff. When the user taps "ask my agent" (or the
# assistant decides a question needs deep/external analysis), the client should call
# POST /api/agent-bridge/requests with {question, conversation_id, context} and show a
# pending bubble that resolves via GET /api/agent-bridge/requests/{id}/stream. Answers
# arrive asynchronously (minutes). Optionally let the chat graph offer this as a tool.
# SECURITY: agent answers and agent-curated cards are untrusted (they may quote emails or
# web pages containing prompt injections). If they are ever added to this model's context
# (history, RAG, "explain this card"), wrap them with
# backend.agent_bridge.untrusted.agent_answer_for_prompt / wrap_untrusted first.
# Not wired yet: today agent text is only shown to the user, never fed to the chat model.
FEEDBACK_REASONS = ("wrong", "incomplete", "not_my_level", "bad_sources", "too_long", "other")


class AnswerFeedback(BaseModel):
    rating: Literal["up", "down"]
    reason: Optional[Literal["wrong", "incomplete", "not_my_level", "bad_sources", "too_long", "other"]] = None
    comment: Optional[str] = Field(default=None, max_length=500)


@router.post("/messages/{message_id}/feedback")
async def answer_feedback(
    message_id: str,
    body: AnswerFeedback,
    current_user: dict = Depends(get_current_user),
):
    """Thumbs up/down on an assistant answer (the online quality signal). Stored on the message, so
    it sits next to the prompt version, model, reranker and outcomes that produced the answer."""
    pg_client = await get_postgres_client()
    user_id = str(current_user["id"])
    feedback = {"rating": body.rating, "reason": body.reason, "comment": (body.comment or "").strip() or None,
                "at": datetime.now(timezone.utc).isoformat()}
    rows = await pg_client.execute_query(
        """
        UPDATE chat_messages cm
        SET meta_json = COALESCE(cm.meta_json, '{}'::jsonb) || jsonb_build_object('feedback', CAST(:feedback AS jsonb))
        FROM chat_conversations cc
        WHERE cm.id = CAST(:message_id AS uuid) AND cm.role = 'assistant'
          AND cc.id = cm.conversation_id AND cc.user_id = :user_id
        RETURNING cm.id
        """,
        {"message_id": message_id, "user_id": user_id, "feedback": json.dumps(feedback)},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Answer not found")
    return {"status": "recorded", "message_id": message_id, "feedback": feedback}


@router.get("/quality")
async def answer_quality(
    days: int = Query(30, ge=1, le=365),
    current_user: dict = Depends(get_current_user),
):
    """The caller's own answer-quality numbers for the last `days`: thumbs up/down, and how often each
    failure outcome happened, overall and per prompt version (to compare releases)."""
    pg_client = await get_postgres_client()
    rows = await pg_client.execute_query(
        """
        SELECT cm.meta_json
        FROM chat_messages cm
        JOIN chat_conversations cc ON cc.id = cm.conversation_id
        WHERE cc.user_id = :user_id AND cm.role = 'assistant'
          AND cm.created_at >= NOW() - make_interval(days => :days)
        """,
        {"user_id": str(current_user["id"]), "days": days},
    )
    return summarize_quality([r.get("meta_json") for r in rows or []])


def summarize_quality(metas: list) -> dict:
    def blank() -> dict:
        return {"answers": 0, "up": 0, "down": 0, "outcomes": {}}

    overall, by_version = blank(), {}
    for meta in metas:
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except ValueError:
                meta = {}
        meta = meta or {}
        gen = meta.get("generation") or {}
        version = gen.get("prompt_version") or "unversioned"
        for bucket in (overall, by_version.setdefault(version, blank())):
            bucket["answers"] += 1
            rating = (meta.get("feedback") or {}).get("rating")
            if rating in ("up", "down"):
                bucket[rating] += 1
            for tag in gen.get("outcomes") or []:
                bucket["outcomes"][tag] = bucket["outcomes"].get(tag, 0) + 1

    def rates(b: dict) -> dict:
        rated = b["up"] + b["down"]
        return {**b, "thumbs_down_rate": round(b["down"] / rated, 3) if rated else None,
                "outcome_rates": {k: round(v / b["answers"], 3) for k, v in b["outcomes"].items()} if b["answers"] else {}}

    return {"overall": rates(overall), "by_prompt_version": {k: rates(v) for k, v in by_version.items()}}


@router.post("/stream")
async def stream_chat(
    request: ChatRequest,
    current_user: dict = Depends(require_quota("chat")),
):
    """
    Stream chat responses using Server-Sent Events.
    
    The response is streamed in chunks as the AI generates it,
    providing a more responsive user experience.
    """
    async def generate():
        # Timings start after auth (auth.* stages are recorded by the dependency).
        stream_start = now()
        first_token_logged = False
        node_starts: dict[str, float] = {}
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

            thread_id = chat_thread_id(user_id, conversation_id)
            config = {"configurable": {"thread_id": thread_id}}

            # Save user message immediately (with which suggestion it came from, if any).
            click = suggestion_click_meta(getattr(request, "from_suggestion", None))
            await pg_client.execute_insert(
                """
                INSERT INTO chat_messages (conversation_id, role, content, meta_json)
                VALUES (:conversation_id, 'user', :content, CAST(:meta AS jsonb))
                RETURNING id
                """,
                {
                    "conversation_id": conversation_id,
                    "content": request.message,
                    "meta": json.dumps({"from_suggestion": click}) if click else None,
                },
            )
            record("chat.setup_db", elapsed_ms(stream_start))

            initial_state: ChatState = {
                "messages": [HumanMessage(content=request.message)],
                "user_id": user_id,
                "focused_source_ids": getattr(request, 'source_ids', None) or [],  # Source-scoped filtering
                "retrieval_query": request.message,
                "graph_context": {},
                "rag_context": [],
            }
            
            # Streaming Loop using astream_events (LangGraph 1.0+)
            # Using version="v2" for standard event format
            full_content = ""
            # Filters the live token stream: a disallowed image never reaches the client, even briefly.
            image_guard = StreamingImageGuard()

            async for event in chat_graph.astream_events(initial_state, config, version="v2"):
                
                kind = event["event"]
                
                # Stream partial tokens from the LLM
                if kind == "on_chat_model_stream":
                    tags = event.get("tags", [])
                    content = event["data"]["chunk"].text
                    if not content:
                        continue
                        
                    # Only append to main message content if it's the final response
                    if "final_response" in tags:
                        if not first_token_logged:
                            first_token_logged = True
                            record("chat.first_token_after_auth", elapsed_ms(stream_start))
                        safe = image_guard.feed(content)
                        if not safe:
                            continue
                        full_content += safe
                        yield f"data: {json.dumps({'type': 'chunk', 'content': safe})}\n\n"
                    else:
                        # Otherwise, send as a status update (keeps the "loading" feel but clean)
                        # This avoids the "JSON in message" problem
                        yield f"data: {json.dumps({'type': 'status', 'content': 'Analyzing intent...'})}\n\n"
                
                # Notify about tool usage (searching graph/notes)
                elif kind == "on_tool_start":
                    yield f"data: {json.dumps({'type': 'status', 'content': f'Using tool: {event['name']}...'})}\n\n"
                    
                # Monitor node transitions (for debug/UI)
                elif kind == "on_chain_start" and event["name"] in ["analyze_query", "get_context", "generate_response"]:
                    node_starts[event["name"]] = now()
                    yield f"data: {json.dumps({'type': 'status', 'content': f'Step: {event['name']}...'})}\n\n"

                elif kind == "on_chain_end" and event["name"] in node_starts:
                    record(f"chat.node.{event['name']}", elapsed_ms(node_starts.pop(event["name"])))
                    if event["name"] == "get_context":
                        output = (event.get("data") or {}).get("output") or {}
                        image_guard.allowed |= allowed_image_urls(output.get("rag_context") or [])

            tail = image_guard.finish()
            if tail:
                full_content += tail
                yield f"data: {json.dumps({'type': 'chunk', 'content': tail})}\n\n"

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
                if not full_content and final_content and not first_token_logged:
                    first_token_logged = True
                    record("chat.first_token_after_auth", elapsed_ms(stream_start))
                events, full_content = finalize_stream_text(full_content, final_content)
                for ev in events:
                    yield f"data: {json.dumps(ev)}\n\n"

            # Fix: Ensure UUIDs are strings for JSON serialization
            def json_safe(obj):
                if isinstance(obj, uuid.UUID):
                    return str(obj)
                return obj

            # Next questions from the user's own graph around what grounded this answer (no LLM call).
            followups_start = now()
            suggestions = await suggest_followups(user_id, request.message, related_concepts)
            record("chat.followups", elapsed_ms(followups_start))
            meta = message_meta(related_concepts, values.get("metadata") or {})
            if suggestions:
                meta["suggestions"] = suggestions

            persist_start = now()
            # Persist assistant message, with what grounded it (shown again when the thread reopens).
            assistant_message_id = await pg_client.execute_insert(
                """
                INSERT INTO chat_messages (conversation_id, role, content, sources_json, meta_json)
                VALUES (:conversation_id, 'assistant', :content, :sources, CAST(:meta AS jsonb))
                RETURNING id
                """,
                {
                    "conversation_id": conversation_id,
                    "content": full_content,
                    "sources": json.dumps(sources),
                    "meta": json.dumps(meta, default=str),
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
            record("chat.persist", elapsed_ms(persist_start))
            record("chat.stream_total_after_auth", elapsed_ms(stream_start))

            # Send final event with metadata
            metadata = values.get("metadata", {})
            final_data = {
                'type': 'done',
                'sources': sources,
                'related_concepts': related_concepts,
                'metadata': metadata,
                'message_id': assistant_message_id,
                'conversation_id': conversation_id,
                'suggestions': suggestions,
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
