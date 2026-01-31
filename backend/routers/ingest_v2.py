"""
V2 Ingest Router - LangGraph-powered note ingestion.

This router uses the new LangGraph StateGraph workflow for ingestion,
following modern LangGraph 1.0.7 patterns with:
- Conditional edges for overlap detection
- Human-in-the-loop interrupts for concept review
- PostgresSaver for production persistence
"""

from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.graphs.ingestion_graph import (
    run_ingestion,
    resume_ingestion,
    get_ingestion_status,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v2", tags=["V2 Ingestion"])


# ============================================================================
# Request/Response Models
# ============================================================================


class IngestRequest(BaseModel):
    """Request body for note ingestion."""
    
    content: str
    title: Optional[str] = None
    user_id: str = "00000000-0000-0000-0000-000000000001"
    skip_review: bool = False  # If True, auto-approve concepts


class IngestResponse(BaseModel):
    """Response from note ingestion."""
    
    note_id: Optional[str] = None
    concepts: list[dict] = []
    concept_ids: list[str] = []
    flashcard_ids: list[str] = []
    synthesis_decisions: Optional[list[dict]] = None
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
async def ingest_note(request: IngestRequest):
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
    logger.info(
        "v2/ingest: Starting ingestion",
        content_length=len(request.content),
        user_id=request.user_id,
        skip_review=request.skip_review,
    )
    
    try:
        result = await run_ingestion(
            content=request.content,
            title=request.title,
            user_id=request.user_id,
            skip_review=request.skip_review,
        )
        
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
        
        return IngestResponse(
            note_id=result.get("note_id"),
            concepts=result.get("concepts", []),
            concept_ids=result.get("concept_ids", []),
            flashcard_ids=result.get("flashcard_ids", []),
            synthesis_decisions=result.get("synthesis_decisions"),
            status=status,
            thread_id=result.get("thread_id", ""),
            error=result.get("error"),
        )
        
    except Exception as e:
        logger.error("v2/ingest: Fatal error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ingest/{thread_id}/status", response_model=StatusResponse)
async def get_status(thread_id: str):
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
        result = await get_ingestion_status(thread_id)
        
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
async def approve_and_resume(thread_id: str, request: ResumeRequest):
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
        result = await resume_ingestion(
            thread_id=thread_id,
            user_approved_concepts=request.approved_concepts,
            user_cancelled=request.cancelled,
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


@router.get("/health")
async def health_check():
    """Health check for the V2 API."""
    return {
        "status": "healthy",
        "version": "2.1",
        "workflow": "langgraph",
        "features": [
            "conditional_edges",
            "human_in_the_loop",
            "postgres_checkpointer",
        ],
    }
