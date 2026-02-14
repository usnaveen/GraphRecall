"""
V2 Ingest Router - LangGraph-powered note ingestion.

This router uses the new LangGraph StateGraph workflow for ingestion,
following modern LangGraph 1.0.7 patterns with:
- Conditional edges for overlap detection
- Human-in-the-loop interrupts for concept review
- PostgresSaver for production persistence
"""

from typing import Optional

import asyncio
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from backend.auth.middleware import get_current_user
from backend.agents.scanner_agent import ScannerAgent
from backend.db.postgres_client import get_postgres_client
from backend.services.community_service import CommunityService

from backend.graphs.ingestion_graph import (
    run_ingestion,
    resume_ingestion,
    get_ingestion_status,
)

logger = structlog.get_logger()
scanner_agent = ScannerAgent()

router = APIRouter(prefix="/api/v2", tags=["V2 Ingestion"])


async def _recompute_communities(user_id: str) -> None:
    """Recompute communities in the background after ingestion.

    Runs Louvain detection, persists results, and generates LLM summaries.
    Errors are logged but never propagated (fire-and-forget task).
    """
    try:
        service = CommunityService()
        communities = await service.compute_communities(user_id)
        await service.persist_communities(user_id, communities)
        await service.generate_community_summaries(user_id)
        logger.info(
            "Background community recompute complete",
            user_id=user_id,
            num_communities=len(communities),
        )
    except Exception as e:
        logger.error("Background community recompute failed", user_id=user_id, error=str(e))


# ============================================================================
# Request/Response Models
# ============================================================================


class IngestRequest(BaseModel):
    """Request body for note ingestion."""

    content: str
    title: Optional[str] = None
    skip_review: bool = False  # If True, auto-approve concepts
    resource_type: Optional[str] = None  # e.g. "book", "notes", "article"


class IngestResponse(BaseModel):
    """Response from note ingestion."""

    note_id: Optional[str] = None
    concepts: list[dict] = []
    concept_ids: list[Optional[str]] = []  # Allow None values (filtered on output)
    flashcard_ids: list[str] = []
    synthesis_decisions: Optional[list[dict]] = None
    processing_metadata: Optional[dict] = None  # Geekout facts for UI
    status: str  # "completed", "awaiting_review", "error"
    thread_id: str  # For resuming workflow
    error: Optional[str] = None


class ResumeRequest(BaseModel):
    """Request to resume ingestion after user review."""
    
    approved_concepts: list[dict]  # User-approved/modified concepts
    cancelled: bool = False


class StatusResponse(BaseModel):
    """Current status of an ingestion workflow."""
    
    status: str  # "processing", "awaiting_review", "completed", "error", "not_found"
    thread_id: str
    note_id: Optional[str] = None
    next_step: Optional[str] = None
    concepts: list[dict] = []
    synthesis_decisions: Optional[list[dict]] = None
    error: Optional[str] = None


# ============================================================================
# Endpoints
# ============================================================================


@router.post("/ingest", response_model=IngestResponse)
async def ingest_note(
    request: IngestRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Ingest a note using the LangGraph workflow.
    
    This endpoint uses the StateGraph-based ingestion pipeline:
    1. extract_concepts - LLM extracts key concepts
    2. store_note - Saves note to PostgreSQL
    3. find_related - Finds similar existing concepts
    4. (conditional) - If overlap detected, prepares synthesis decisions
    5. user_review - PAUSES for human approval (unless skip_review=True)
    6. create_concepts - Creates concept nodes in Neo4j
    7. generate_flashcards - Creates flashcards for learning
    
    If overlap is detected and skip_review=False, returns with status="awaiting_review".
    Use the thread_id to check status or resume the workflow.
    """
    user_id = str(current_user["id"])
    logger.info(
        "v2/ingest: Starting ingestion",
        content_length=len(request.content),
        user_id=user_id,
        skip_review=request.skip_review,
    )
    
    try:
        # 1. Check for duplicates
        import hashlib
        content_hash = hashlib.sha256(request.content.encode("utf-8")).hexdigest()
        
        pg_client = await get_postgres_client()
        existing_note = await pg_client.execute_query(
            "SELECT id FROM notes WHERE user_id = :user_id AND content_hash = :hash_val",
            {"user_id": user_id, "hash_val": content_hash}
        )
        
        if existing_note:
            logger.info("v2/ingest: Duplicate detected", note_id=existing_note[0]["id"])
            # Return successfully but point to existing note
            return IngestResponse(
                note_id=existing_note[0]["id"],
                status="completed",
                thread_id="duplicate_skipped",
                error="Duplicate content detected. Note already exists."
            )

        # Wrap in shield to ensure ingestion completes even if client disconnects
        result = await asyncio.shield(run_ingestion(
            content=request.content,
            title=request.title,
            user_id=user_id,
            skip_review=request.skip_review,
            content_hash=content_hash, # Pass hash to save it
            resource_type=request.resource_type,  # Pass through (e.g. "book")
        ))
        
        status = result.get("status", "completed")
        
        if status == "awaiting_review":
            logger.info(
                "v2/ingest: Paused for user review",
                thread_id=result.get("thread_id"),
                num_concepts=len(result.get("concepts", [])),
            )
        elif result.get("error"):
            logger.warning(
                "v2/ingest: Completed with error",
                error=result["error"],
            )
        else:
            logger.info(
                "v2/ingest: Success",
                note_id=result.get("note_id"),
                num_concepts=len(result.get("concept_ids", [])),
                num_flashcards=len(result.get("flashcard_ids", [])),
            )
        
        if status == "completed":
            asyncio.create_task(_recompute_communities(user_id))

        if status == "completed" or (status == "awaiting_review" and result.get("note_id")):
             # Trigger Lazy Quiz Scanner in background
             note_id = result.get("note_id")
             if note_id:
                 asyncio.create_task(scanner_agent.scan_and_save(
                     request.content, 
                     note_id, 
                     user_id
                 ))
        
        return IngestResponse(
            note_id=result.get("note_id"),
            concepts=result.get("concepts", []),
            concept_ids=[c for c in result.get("concept_ids", []) if c is not None],
            flashcard_ids=result.get("flashcard_ids", []),
            synthesis_decisions=result.get("synthesis_decisions"),
            processing_metadata=result.get("processing_metadata"),
            status=status,
            thread_id=result.get("thread_id", ""),
            error=result.get("error"),
        )
        
    except Exception as e:
        logger.error("v2/ingest: Fatal error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# URL Ingestion (Articles/Substack)
# ============================================================================

from backend.graphs.article_graph import process_article_url

class IngestUrlRequest(BaseModel):
    url: str

@router.post("/ingest/url", response_model=IngestResponse)
async def ingest_url(
    request: IngestUrlRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Ingest an article from a URL (e.g. Substack, Medium, Blog).
    
    1. Fetches HTML.
    2. Parses Title/Author/Content using Gemini.
    3. Ingests into Knowledge Graph (auto-approved).
    """
    user_id = str(current_user["id"])
    logger.info("v2/ingest/url: Starting", url=request.url)
    
    try:
        # Run Article Graph
        result = await process_article_url(request.url, user_id=user_id)
        
        if result.get("error"):
             raise HTTPException(status_code=400, detail=result["error"])
             
        ingestion_res = result.get("ingestion_result", {})
        
        # Merge structured metadata
        return IngestResponse(
            note_id=ingestion_res.get("note_id"),
            concepts=ingestion_res.get("concepts", []),
            concept_ids=ingestion_res.get("concept_ids", []),
            flashcard_ids=ingestion_res.get("flashcard_ids", []),
            processing_metadata=ingestion_res.get("processing_metadata"),
            status="completed",
            thread_id=ingestion_res.get("thread_id", ""),
            error=ingestion_res.get("error"),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("v2/ingest/url: Failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ingest/{thread_id}/status", response_model=StatusResponse)
async def get_status(
    thread_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Get the current status of an ingestion workflow.
    
    Use this to check if a workflow is:
    - processing: Still running
    - awaiting_review: Paused for human approval
    - completed: Finished successfully
    - error: Failed with error
    - not_found: Thread ID not found
    """
    try:
        user_id = str(current_user["id"])
        result = await get_ingestion_status(thread_id, user_id=user_id)
        
        return StatusResponse(
            status=result.get("status", "not_found"),
            thread_id=thread_id,
            note_id=result.get("note_id"),
            next_step=result.get("next_step"),
            concepts=result.get("concepts", []),
            synthesis_decisions=result.get("synthesis_decisions"),
            error=result.get("error"),
        )
        
    except Exception as e:
        logger.error("v2/ingest/status: Failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest/{thread_id}/approve", response_model=IngestResponse)
async def approve_and_resume(
    thread_id: str,
    request: ResumeRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Resume ingestion after user has reviewed concepts.
    
    Human-in-the-Loop Flow:
    1. POST /api/v2/ingest -> status="awaiting_review", get thread_id
    2. User reviews concepts and synthesis_decisions
    3. POST /api/v2/ingest/{thread_id}/approve with approved_concepts
    4. Workflow resumes and creates concepts in Neo4j
    
    If cancelled=True, the workflow ends without creating concepts.
    """
    logger.info(
        "v2/ingest/approve: Resuming workflow",
        thread_id=thread_id,
        num_approved=len(request.approved_concepts),
        cancelled=request.cancelled,
    )
    
    try:
        user_id = str(current_user["id"])
        result = await resume_ingestion(
            thread_id=thread_id,
            user_approved_concepts=request.approved_concepts,
            user_cancelled=request.cancelled,
            user_id=user_id,
        )
        
        status = result.get("status", "completed")
        
        if status == "cancelled":
            logger.info("v2/ingest/approve: Workflow cancelled by user")
        else:
            logger.info(
                "v2/ingest/approve: Completed",
                note_id=result.get("note_id"),
                num_concepts=len(result.get("concept_ids", [])),
            )
        
        return IngestResponse(
            note_id=result.get("note_id"),
            concepts=[],  # Concepts already returned in initial response
            concept_ids=result.get("concept_ids", []),
            flashcard_ids=result.get("flashcard_ids", []),
            synthesis_decisions=None,
            status=status,
            thread_id=thread_id,
            error=result.get("error"),
        )
        
    except Exception as e:
        logger.error("v2/ingest/approve: Failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# YouTube Link Storage (no processing, just stored and linked)
# ============================================================================


class IngestYoutubeRequest(BaseModel):
    url: str
    title: Optional[str] = None


@router.post("/ingest/youtube")
async def ingest_youtube_link(
    request: IngestYoutubeRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Store a YouTube link as a note resource (no processing).

    YouTube links are just stored and linked — not processed.
    """
    import uuid
    from datetime import datetime, timezone
    from backend.db.postgres_client import get_postgres_client

    user_id = str(current_user["id"])
    note_id = str(uuid.uuid4())
    title = request.title or f"YouTube: {request.url}"

    try:
        pg_client = await get_postgres_client()
        await pg_client.execute_update(
            """
            INSERT INTO notes (id, user_id, title, content_text, resource_type, source_url, created_at, updated_at)
            VALUES (:id, :user_id, :title, :content_text, :resource_type, :source_url, :created_at, :created_at)
            """,
            {
                "id": note_id,
                "user_id": user_id,
                "title": title,
                "content_text": f"YouTube link: {request.url}",
                "resource_type": "youtube",
                "source_url": request.url,
                "created_at": datetime.now(timezone.utc),
            },
        )

        logger.info("v2/ingest/youtube: Stored", note_id=note_id, url=request.url)

        return {
            "note_id": note_id,
            "status": "stored",
            "resource_type": "youtube",
            "url": request.url,
        }
    except Exception as e:
        logger.error("v2/ingest/youtube: Failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# LLM Chat Transcript Ingestion
# ============================================================================


class IngestChatTranscriptRequest(BaseModel):
    content: str  # Raw pasted transcript (Human: ... AI: ...)
    title: Optional[str] = None


@router.post("/ingest/chat-transcript", response_model=IngestResponse)
async def ingest_chat_transcript(
    request: IngestChatTranscriptRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Ingest an LLM chat transcript.

    Processes human + AI messages, consolidates them, and stores
    them as a note in the knowledge graph.
    """
    user_id = str(current_user["id"])
    logger.info("v2/ingest/chat-transcript: Starting", content_length=len(request.content))

    try:
        # Consolidate the transcript into a structured note
        from backend.config.llm import get_chat_model
        llm = get_chat_model(temperature=0.1)

        consolidation_prompt = f"""Consolidate this LLM chat transcript into a clean knowledge note.

Transcript:
{request.content[:5000]}

Instructions:
1. Extract the KEY INFORMATION discussed (facts, concepts, explanations)
2. Remove conversational filler ("sure!", "great question", etc.)
3. Organize into clear sections with markdown headers
4. Preserve code blocks and technical details
5. Note which points were questions vs answers

Return the consolidated note as clean markdown."""

        response = await llm.ainvoke(consolidation_prompt)
        consolidated = response.content.strip()

        # Now run through standard ingestion with consolidated content
        result = await asyncio.shield(run_ingestion(
            content=consolidated,
            title=request.title or "Chat Transcript Notes",
            user_id=user_id,
            skip_review=True,
        ))

        # Trigger Lazy Quiz Scanner in background
        if result.get("note_id"):
             asyncio.create_task(scanner_agent.scan_and_save(
                 consolidated, 
                 result.get("note_id"), 
                 user_id
             ))

        return IngestResponse(
            note_id=result.get("note_id"),
            concepts=result.get("concepts", []),
            concept_ids=result.get("concept_ids", []),
            flashcard_ids=result.get("flashcard_ids", []),
            processing_metadata=result.get("processing_metadata"),
            status="completed",
            thread_id=result.get("thread_id", ""),
            error=result.get("error"),
        )
    except Exception as e:
        logger.error("v2/ingest/chat-transcript: Failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Health check for the V2 API."""
    return {
        "status": "healthy",
        "version": "2.2",
        "workflow": "langgraph",
        "features": [
            "conditional_edges",
            "human_in_the_loop",
            "postgres_checkpointer",
            "youtube_links",
            "chat_transcript_ingestion",
        ],
    }
