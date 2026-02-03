"""FastAPI application for GraphRecall."""

import time
from contextlib import asynccontextmanager
from typing import Optional
from uuid import UUID, uuid4

import structlog
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from backend.auth.middleware import get_current_user

from backend.db.neo4j_client import (
    Neo4jClient,
    close_neo4j_client,
    get_neo4j_client,
)
from backend.db.postgres_client import (
    PostgresClient,
    close_postgres_client,
    get_postgres_client,
)
from backend.graphs import run_ingestion
from backend.models.schemas import (
    ConceptResponse,
    GraphResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    Note,
    NoteCreate,
)

# Import new routers with debug logging
try:
    from backend.routers.feed import router as feed_router
    from backend.routers.review import router as review_router
    from backend.routers.chat import router as chat_router
    from backend.routers.graph3d import router as graph3d_router
    from backend.routers.uploads import router as uploads_router
    from backend.routers.ingest_v2 import router as ingest_v2_router
    from backend.routers.auth import router as auth_router
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"CRITICAL: Failed to import routers: {e}")
    # We re-raise so the app still crashes, but after printing the error
    raise e

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ]
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown."""
    # Startup
    logger.info("Starting GraphRecall API")
    
    try:
        # Initialize database clients
        pg_client = await get_postgres_client()
        
        # Fix missing columns BEFORE running init.sql (which creates indexes)
        try:
            logger.info("Applying schema fixes...")
            async with pg_client.session() as session:
                # 1. Notes table fixes
                await session.execute(text(
                    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS resource_type VARCHAR(50) DEFAULT 'notes'"
                ))
                await session.execute(text(
                    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS content_hash TEXT"
                ))
                await session.execute(text(
                    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS summary TEXT"
                ))
                
                # 2. Proficiency scores fixes (SM2 metadata)
                await session.execute(text(
                    "ALTER TABLE proficiency_scores ADD COLUMN IF NOT EXISTS easiness_factor DECIMAL(3,2) DEFAULT 2.5"
                ))
                await session.execute(text(
                    "ALTER TABLE proficiency_scores ADD COLUMN IF NOT EXISTS interval_days INTEGER DEFAULT 1"
                ))
                await session.execute(text(
                    "ALTER TABLE proficiency_scores ADD COLUMN IF NOT EXISTS repetition_count INTEGER DEFAULT 0"
                ))
                await session.execute(text(
                    "ALTER TABLE proficiency_scores ADD COLUMN IF NOT EXISTS total_reviews INTEGER DEFAULT 0"
                ))
                await session.execute(text(
                    "ALTER TABLE proficiency_scores ADD COLUMN IF NOT EXISTS correct_streak INTEGER DEFAULT 0"
                ))
                # Fix name mismatch: ensure next_review_due is the primary column, 
                # but also support next_review if legacy code uses it.
                await session.execute(text(
                    "ALTER TABLE proficiency_scores ADD COLUMN IF NOT EXISTS next_review_due TIMESTAMP WITH TIME ZONE"
                ))
                
                await session.commit()

            logger.info("Schema fixes applied (resource_type, content_hash, SM2 metadata)")

        except Exception as e:
            logger.warning("Schema fixes skipped", error=str(e))
        
        await pg_client.initialize_schema()
        await get_neo4j_client()
        logger.info("Database connections established")
    except Exception as e:
        logger.error("Failed to initialize databases", error=str(e))
        # Continue anyway - databases might come up later

    yield

    # Shutdown
    logger.info("Shutting down GraphRecall API")
    await close_postgres_client()
    await close_neo4j_client()


app = FastAPI(
    title="GraphRecall API",
    description="Lifetime Active Recall Learning System with Knowledge Graph",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware for frontend
# In production with allow_credentials=True, we cannot use ["*"].
# We must specify the exact origins.
import os
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
origins = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://graph-recall.vercel.app",  # Explicit Vercel URL
    frontend_url,
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register new routers
app.include_router(feed_router)      # /api/feed - Active recall feed
app.include_router(review_router)    # /api/review - Human-in-the-loop concept review
app.include_router(chat_router)      # /api/chat - GraphRAG assistant
app.include_router(graph3d_router)   # /api/graph3d - 3D visualization data
app.include_router(uploads_router)   # /api/uploads - User screenshots/infographics
app.include_router(ingest_v2_router) # /api/v2 - LangGraph-powered ingestion
app.include_router(auth_router)      # /auth - Google authentication


# ============================================================================
# Health Check Endpoints
# ============================================================================


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Check the health of the API and its dependencies."""
    try:
        pg_client = await get_postgres_client()
        pg_health = await pg_client.health_check()
    except Exception as e:
        pg_health = {"status": "unhealthy", "error": str(e)}

    try:
        neo4j_client = await get_neo4j_client()
        neo4j_health = await neo4j_client.health_check()
    except Exception as e:
        neo4j_health = {"status": "unhealthy", "error": str(e)}

    overall_status = "healthy"
    if pg_health.get("status") != "healthy" or neo4j_health.get("status") != "healthy":
        overall_status = "degraded"

    return HealthResponse(
        status=overall_status,
        postgres=pg_health,
        neo4j=neo4j_health,
        version="0.1.0",
    )


# ============================================================================
# Note Ingestion Endpoints
# ============================================================================


@app.post("/api/ingest", response_model=IngestResponse, tags=["Ingestion"])
async def ingest_note(
    request: IngestRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Ingest a markdown/text note into the knowledge graph.

    This triggers the full LangGraph pipeline:
    1. Parse and validate input
    2. Extract concepts using Agent 1
    3. Check for conflicts using Agent 2
    4. Update the knowledge graph using Agent 3
    """
    start_time = time.time()

    logger.info(
        "Ingesting note",
        user_id=request.user_id,
        content_length=len(request.content),
    )

    try:
        user_id = str(current_user["id"])
        
        # 1. Check for duplicates
        import hashlib
        content_hash = hashlib.sha256(request.content.encode("utf-8")).hexdigest()
        
        pg_client = await get_postgres_client()
        existing_note = await pg_client.execute_query(
            "SELECT id FROM notes WHERE user_id = :user_id AND (content_hash = :hash_val OR content_text = :content)",
            {"user_id": user_id, "hash_val": content_hash, "content": request.content}
        )
        
        if existing_note:
            note_id = existing_note[0]["id"]
            logger.info("ingest: Duplicate detected", note_id=note_id)
        else:
            # First, save the note to PostgreSQL
            note_id = await pg_client.execute_insert(
                """
                INSERT INTO notes (user_id, content_text, content_type, source_url, content_hash)
                VALUES (:user_id, :content, 'markdown', :source_url, :content_hash)
                RETURNING id
                """,
                {
                    "user_id": user_id,
                    "content": request.content,
                    "source_url": request.source_url,
                    "content_hash": content_hash,
                },
            )

        # ... rest of the function ...
        # Run the ingestion pipeline
        # V2 Migration: Use run_ingestion with skip_review=True to mimic old auto-approve behavior
        result = await run_ingestion(
            content=request.content,
            user_id=user_id,
            title=None, # V1 didn't have title in request
            note_id=note_id,
            skip_review=True, 
        )

        processing_time = (time.time() - start_time) * 1000

        # Check for errors
        if result.get("error_message"):
            logger.error(
                "Ingestion failed",
                note_id=note_id,
                error=result["error_message"],
            )
            return IngestResponse(
                note_id=note_id,
                concepts_extracted=[],
                concepts_created=0,
                relationships_created=0,
                status="error",
                processing_time_ms=processing_time,
            )

        # Extract concept IDs from the result
        concept_ids = [c.get("id", "") for c in result.get("extracted_concepts", [])]

        logger.info(
            "Ingestion complete",
            note_id=note_id,
            concepts_created=result.get("concepts_created", 0),
            processing_time_ms=processing_time,
        )

        return IngestResponse(
            note_id=note_id,
            concepts_extracted=concept_ids,
            concepts_created=result.get("concepts_created", 0),
            relationships_created=result.get("relationships_created", 0),
            status="completed",
            processing_time_ms=processing_time,
        )

    except Exception as e:
        logger.error("Ingestion error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Notes CRUD Endpoints
# ============================================================================


@app.get("/api/notes", tags=["Notes"])
async def list_notes(
    current_user: dict = Depends(get_current_user),
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List all notes for a user."""
    try:
        user_id = str(current_user["id"])
        pg_client = await get_postgres_client()
        notes = await pg_client.execute_query(
            """
            SELECT id, user_id, content_type, content_text, source_url, 
                   created_at, updated_at
            FROM notes
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """,
            {"user_id": user_id, "limit": limit, "offset": offset},
        )

        return {
            "notes": notes,
            "total": len(notes),
            "limit": limit,
            "offset": offset,
        }

    except Exception as e:
        logger.error("Error listing notes", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/notes/{note_id}", tags=["Notes"])
async def get_note(
    note_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get a specific note by ID."""
    try:
        user_id = str(current_user["id"])
        pg_client = await get_postgres_client()
        notes = await pg_client.execute_query(
            """
            SELECT id, user_id, content_type, content_text, source_url,
                   created_at, updated_at
            FROM notes
            WHERE id = :note_id AND user_id = :user_id
            """,
            {"note_id": note_id, "user_id": user_id},
        )

        if not notes:
            raise HTTPException(status_code=404, detail="Note not found")

        return notes[0]


    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting note", note_id=note_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/notes/{note_id}", tags=["Notes"])
async def delete_note(
    note_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a note and its corresponding graph node."""
    try:
        user_id = str(current_user["id"])
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()

        # 1. Delete from Postgres
        # We also need to delete related flashcards/quizzes if cascading isn't set up
        # For now, we'll assume DB constraints handle it or leave them orphaned but harmless
        await pg_client.execute_update(
            "DELETE FROM notes WHERE id = :note_id AND user_id = :user_id",
            {"note_id": note_id, "user_id": user_id}
        )

        # 2. Delete NoteSource node from Neo4j
        # This will also remove the EXPLAINS relationships
        await neo4j_client.execute_query(
            """
            MATCH (n:NoteSource {id: $note_id, user_id: $user_id})
            DETACH DELETE n
            """,
            {"note_id": note_id, "user_id": user_id}
        )

        logger.info("Deleted note", note_id=note_id, user_id=user_id)
        return {"status": "success", "message": "Note deleted"}

    except Exception as e:
        logger.error("Error deleting note", note_id=note_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Knowledge Graph Endpoints
# ============================================================================


@app.get("/api/graph", response_model=GraphResponse, tags=["Graph"])
async def get_knowledge_graph(
    current_user: dict = Depends(get_current_user),
    concept_id: Optional[str] = Query(default=None, description="Filter by concept ID"),
    depth: int = Query(default=2, ge=1, le=5, description="Graph traversal depth"),
):
    """
    Get the knowledge graph for visualization.

    Returns nodes (concepts) and edges (relationships) in a format
    suitable for React Flow or similar graph visualization libraries.
    """
    try:
        user_id = str(current_user["id"])
        neo4j_client = await get_neo4j_client()
        graph_data = await neo4j_client.get_graph_for_user(user_id=user_id, depth=depth)

        return GraphResponse(
            nodes=graph_data["nodes"],
            edges=graph_data["edges"],
            total_concepts=len(graph_data["nodes"]),
            total_relationships=len(graph_data["edges"]),
        )

    except Exception as e:
        logger.error("Error getting graph", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/graph/concept/{concept_id}", tags=["Graph"])
async def get_concept_details(
    concept_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get detailed information about a specific concept."""
    try:
        user_id = str(current_user["id"])
        neo4j_client = await get_neo4j_client()
        concept = await neo4j_client.get_concept(concept_id, user_id=user_id)

        if not concept:
            raise HTTPException(status_code=404, detail="Concept not found")

        # Get related notes
        notes_query = """
        MATCH (n:NoteSource {user_id: $user_id})-[:EXPLAINS]->(c:Concept {id: $concept_id, user_id: $user_id})
        RETURN n.note_id AS note_id
        """
        notes_result = await neo4j_client.execute_query(
            notes_query, {"concept_id": concept_id, "user_id": user_id}
        )
        related_notes = [r["note_id"] for r in notes_result]

        # Get proficiency if available
        pg_client = await get_postgres_client()
        proficiency_result = await pg_client.execute_query(
            """
            SELECT score, last_reviewed
            FROM proficiency_scores
            WHERE concept_id = :concept_id
            LIMIT 1
            """,
            {"concept_id": concept_id},
        )

        proficiency = proficiency_result[0] if proficiency_result else None

        return {
            "concept": concept,
            "related_notes": related_notes,
            "proficiency_score": proficiency["score"] if proficiency else None,
            "last_reviewed": proficiency["last_reviewed"] if proficiency else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting concept", concept_id=concept_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/graph/search", tags=["Graph"])
async def search_concepts(
    query: str = Query(..., min_length=1, description="Search query"),
    current_user: dict = Depends(get_current_user),
    limit: int = Query(default=20, le=50),
):
    """Search for concepts by name."""
    try:
        user_id = str(current_user["id"])
        neo4j_client = await get_neo4j_client()
        concepts = await neo4j_client.get_concepts_by_name(query, user_id=user_id)

        return {
            "concepts": concepts[:limit],
            "total": len(concepts),
        }

    except Exception as e:
        logger.error("Error searching concepts", query=query, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Root endpoint
# ============================================================================


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint with API information."""
    return {
        "name": "GraphRecall API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
