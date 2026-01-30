"""Review Router - Human-in-the-Loop Concept Review Endpoints."""

from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.models.feed_schemas import (
    ConceptReviewApproval,
    ConceptReviewItem,
    ConceptReviewSession,
)
from backend.services.concept_review import ConceptReviewService
from backend.graph.workflow import run_ingestion_pipeline

logger = structlog.get_logger()

router = APIRouter(prefix="/api/review", tags=["Concept Review"])


class IngestWithReviewRequest(BaseModel):
    """Request for ingestion with human review."""
    
    content: str
    user_id: str = "00000000-0000-0000-0000-000000000001"
    source_url: Optional[str] = None
    skip_review: bool = False  # If True, auto-approve (old behavior)


class IngestWithReviewResponse(BaseModel):
    """Response for ingestion with review."""
    
    note_id: str
    session_id: Optional[str] = None  # Present if review required
    concepts_count: int
    status: str  # "pending_review", "auto_approved", "error"
    message: str


@router.post("/ingest", response_model=IngestWithReviewResponse)
async def ingest_with_review(request: IngestWithReviewRequest):
    """
    Ingest a note with human-in-the-loop concept review.
    
    This is the new ingestion flow:
    1. Save note to database
    2. Extract concepts using AI
    3. Check for conflicts/duplicates
    4. Return concepts for user review (instead of auto-committing)
    
    User can then review, modify, and approve concepts via /api/review/{session_id}/approve
    
    Set skip_review=True to use the old auto-approve behavior.
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        # Save the note first
        note_id = await pg_client.execute_insert(
            """
            INSERT INTO notes (user_id, content_text, content_type, source_url)
            VALUES (:user_id, :content, 'markdown', :source_url)
            RETURNING id
            """,
            {
                "user_id": request.user_id,
                "content": request.content,
                "source_url": request.source_url,
            },
        )
        
        if not note_id:
            raise HTTPException(status_code=500, detail="Failed to save note")
        
        # If skip_review, use old behavior
        if request.skip_review:
            result = await run_ingestion_pipeline(
                user_id=request.user_id,
                content=request.content,
                note_id=note_id,
            )
            
            return IngestWithReviewResponse(
                note_id=note_id,
                session_id=None,
                concepts_count=result.get("concepts_created", 0),
                status="auto_approved",
                message=f"Created {result.get('concepts_created', 0)} concepts automatically",
            )
        
        # Run extraction and synthesis without graph building
        from backend.agents.extraction import ExtractionAgent
        from backend.agents.synthesis import SynthesisAgent
        
        # Extract concepts
        extraction_agent = ExtractionAgent()
        extraction_result = await extraction_agent.extract(request.content)
        
        extracted_concepts = [
            {
                "id": f"concept-{i}-{hash(c.name) % 10000}",
                "name": c.name,
                "definition": c.definition,
                "domain": c.domain,
                "complexity_score": c.complexity_score,
                "confidence": c.confidence,
                "related_concepts": c.related_concepts,
                "prerequisites": c.prerequisites,
            }
            for i, c in enumerate(extraction_result.concepts)
        ]
        
        if not extracted_concepts:
            return IngestWithReviewResponse(
                note_id=note_id,
                session_id=None,
                concepts_count=0,
                status="no_concepts",
                message="No concepts were extracted from the content",
            )
        
        # Check for conflicts
        synthesis_agent = SynthesisAgent()
        synthesis_result = await synthesis_agent.analyze(extracted_concepts)
        conflicts = [c.model_dump() for c in synthesis_result.decisions]
        
        # Create review session
        review_service = ConceptReviewService(pg_client, neo4j_client)
        session = await review_service.create_review_session(
            user_id=request.user_id,
            note_id=note_id,
            original_content=request.content,
            extracted_concepts=extracted_concepts,
            conflicts=conflicts,
        )
        
        logger.info(
            "Review: Created review session",
            session_id=session.session_id,
            concepts_count=len(extracted_concepts),
        )
        
        return IngestWithReviewResponse(
            note_id=note_id,
            session_id=session.session_id,
            concepts_count=len(extracted_concepts),
            status="pending_review",
            message=f"Found {len(extracted_concepts)} concepts. Please review before adding to knowledge graph.",
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Review: Ingestion error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions")
async def list_pending_sessions(
    user_id: str = Query(default="00000000-0000-0000-0000-000000000001"),
):
    """
    List all pending review sessions for a user.
    
    Returns sessions that are:
    - Status: pending
    - Not expired
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        review_service = ConceptReviewService(pg_client, neo4j_client)
        sessions = await review_service.get_pending_sessions(user_id)
        
        return {
            "sessions": [
                {
                    "session_id": s.session_id,
                    "note_id": s.note_id,
                    "concepts_count": len(s.concepts),
                    "created_at": s.created_at.isoformat(),
                    "expires_at": s.expires_at.isoformat(),
                }
                for s in sessions
            ],
            "total": len(sessions),
        }
        
    except Exception as e:
        logger.error("Review: Error listing sessions", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}", response_model=ConceptReviewSession)
async def get_review_session(session_id: str):
    """
    Get a specific review session with all concepts.
    
    Returns the full session including:
    - All extracted concepts with their metadata
    - Detected conflicts/duplicates
    - Session status and expiration
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        review_service = ConceptReviewService(pg_client, neo4j_client)
        session = await review_service.get_session(session_id)
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found or expired")
        
        return session
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Review: Error getting session", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/sessions/{session_id}")
async def update_review_session(
    session_id: str,
    concepts: list[ConceptReviewItem],
):
    """
    Update concepts in a review session.
    
    Use this to:
    - Modify concept names, definitions, etc.
    - Mark concepts as selected/deselected
    - Add relationships
    
    Changes are saved but not committed until /approve is called.
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        review_service = ConceptReviewService(pg_client, neo4j_client)
        session = await review_service.update_session(session_id, concepts)
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found or expired")
        
        return {
            "status": "updated",
            "session_id": session_id,
            "concepts_count": len(session.concepts),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Review: Error updating session", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/approve")
async def approve_review_session(
    session_id: str,
    approval: ConceptReviewApproval,
):
    """
    Approve a review session and commit concepts to the knowledge graph.
    
    This is the final step in the human-in-the-loop flow:
    1. Takes the user's approved/modified concepts
    2. Creates them in the Neo4j knowledge graph
    3. Creates relationships between concepts
    4. Links concepts to the source note
    
    The approval includes:
    - approved_concepts: Concepts to create (with any modifications)
    - removed_concept_ids: IDs of concepts to skip
    - added_concepts: New concepts manually added by user
    """
    try:
        # Ensure session_id matches
        if approval.session_id != session_id:
            raise HTTPException(
                status_code=400,
                detail="Session ID in URL doesn't match approval body",
            )
        
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        review_service = ConceptReviewService(pg_client, neo4j_client)
        result = await review_service.approve_session(approval)
        
        return {
            "status": "approved",
            "session_id": session_id,
            "concepts_created": result["concepts_created"],
            "relationships_created": result["relationships_created"],
            "message": f"Successfully added {result['concepts_created']} concepts to your knowledge graph",
        }
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Review: Error approving session", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/cancel")
async def cancel_review_session(session_id: str):
    """
    Cancel a review session without creating any concepts.
    
    The note remains in the database but no concepts are added
    to the knowledge graph.
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        review_service = ConceptReviewService(pg_client, neo4j_client)
        success = await review_service.cancel_session(session_id)
        
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        
        return {
            "status": "cancelled",
            "session_id": session_id,
            "message": "Review session cancelled. Note was kept but no concepts were created.",
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Review: Error cancelling session", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sessions/{session_id}/concepts")
async def add_concept_to_session(
    session_id: str,
    concept: ConceptReviewItem,
):
    """
    Add a new concept to an existing review session.
    
    Use this when the user wants to manually add a concept
    that wasn't extracted by the AI.
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        review_service = ConceptReviewService(pg_client, neo4j_client)
        session = await review_service.get_session(session_id)
        
        if not session:
            raise HTTPException(status_code=404, detail="Session not found or expired")
        
        # Add the new concept
        concept.user_modified = True
        session.concepts.append(concept)
        
        # Save
        await review_service.update_session(session_id, session.concepts)
        
        return {
            "status": "added",
            "concept_id": concept.id,
            "session_id": session_id,
            "total_concepts": len(session.concepts),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Review: Error adding concept", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
