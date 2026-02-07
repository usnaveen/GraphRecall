"""Feed Router - Active Recall Feed Endpoints."""

import json
import uuid
import random
import asyncio
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from backend.auth.middleware import get_current_user
from backend.config.llm import get_chat_model

from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.models.feed_schemas import (
    DifficultyLevel,
    FeedFilterRequest,
    FeedItemType,
    FeedResponse,
    ReviewResult,
    UserStats,
)
from backend.services.feed_service import FeedService
from backend.services.spaced_repetition import SpacedRepetitionService
from backend.agents.research_agent import WebResearchAgent

logger = structlog.get_logger()


router = APIRouter(prefix="/api/feed", tags=["Feed"])


@router.get("", response_model=FeedResponse)
async def get_feed(
    current_user: dict = Depends(get_current_user),
    max_items: int = Query(default=20, le=50),
    item_types: Optional[str] = Query(
        default=None,
        description="Comma-separated item types: flashcard,mcq,fill_blank,concept_showcase",
    ),
    domains: Optional[str] = Query(
        default=None,
        description="Comma-separated domains to filter",
    ),
):
    """
    Get the user's active recall feed.
    
    Returns a personalized mix of:
    - Due items based on spaced repetition
    - MCQs, flashcards, fill-in-blank questions
    - Concept showcases
    - User uploads (screenshots, infographics)
    
    Items are sorted by priority (overdue items first).
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        feed_service = FeedService(pg_client, neo4j_client)
        
        # Parse item types
        parsed_types = None
        if item_types:
            try:
                parsed_types = [FeedItemType(t.strip()) for t in item_types.split(",")]
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Invalid item type: {e}")
        
        # Parse domains
        parsed_domains = None
        if domains:
            parsed_domains = [d.strip() for d in domains.split(",")]
        
        request = FeedFilterRequest(
            user_id=str(current_user["id"]),
            max_items=max_items,
            item_types=parsed_types,
            domains=parsed_domains,
        )
        
        response = await feed_service.get_feed(request)
        
        # Inject Daily Goal & Trigger Pre-gen Buffer
        response.daily_goal = await feed_service.get_daily_goal(request.user_id)
        asyncio.create_task(feed_service.ensure_weekly_buffer(request.user_id))
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Feed: Error getting feed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/review")
async def record_review(
    item_id: str,
    item_type: str,
    difficulty: DifficultyLevel,
    current_user: dict = Depends(get_current_user),
    response_time_ms: Optional[int] = None,
):
    """
    Record a review for a feed item.
    
    This updates the spaced repetition data and calculates
    the next review date.
    
    Difficulty levels:
    - again: Complete failure, reset to beginning
    - hard: Correct but difficult
    - good: Correct with some hesitation
    - easy: Perfect recall
    """
    try:
        pg_client = await get_postgres_client()
        sr_service = SpacedRepetitionService(pg_client)
        
        review = ReviewResult(
            item_id=item_id,
            item_type=item_type,
            user_id=str(current_user["id"]),
            difficulty=difficulty,
            response_time_ms=response_time_ms,
        )
        
        updated_data = await sr_service.record_review(review)
        
        return {
            "status": "recorded",
            "next_review": updated_data.next_review.isoformat(),
            "new_interval_days": updated_data.interval,
            "easiness_factor": updated_data.easiness_factor,
            "streak": updated_data.correct_streak,
        }
        
    except Exception as e:
        logger.error("Feed: Error recording review", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", response_model=UserStats)
async def get_user_stats(
    current_user: dict = Depends(get_current_user),
):
    """
    Get user's learning statistics.
    
    Includes:
    - Total concepts and notes
    - Streak days
    - Accuracy rate
    - Due items today
    - Progress by domain
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        feed_service = FeedService(pg_client, neo4j_client)
        sr_service = SpacedRepetitionService(pg_client)
        
        user_id = str(current_user["id"])
        
        # Get various stats
        sr_stats = await sr_service.get_user_stats(user_id)
        streak = await feed_service.get_user_streak(user_id)
        completed_today = await feed_service.get_completed_today(user_id)
        daily_goal = await feed_service.get_daily_goal(user_id)
        domains = await feed_service.get_user_domains(user_id)
        
        # Get concept count from Neo4j
        total_concepts = 0
        try:
            result = await neo4j_client.execute_query(
                "MATCH (c:Concept) RETURN count(c) as count",
                {},
            )
            if result:
                total_concepts = result[0].get("count", 0)
        except Exception as e:
            logger.warning("Failed to get concept count", error=str(e))
        
        # Get note count
        total_notes = 0
        try:
            result = await pg_client.execute_query(
                "SELECT COUNT(*) as count FROM notes WHERE user_id = :user_id",
                {"user_id": user_id},
            )
            if result:
                total_notes = result[0].get("count", 0)
        except Exception as e:
            logger.warning("Failed to get note count", error=str(e))
        
        # Get domain mastery and daily activity
        domain_progress = await feed_service.get_domain_mastery(user_id)
        daily_activity = await feed_service.get_daily_activity(user_id)
        
        return UserStats(
            user_id=user_id,
            total_concepts=total_concepts,
            total_notes=total_notes,
            total_reviews=sr_stats.get("total_reviews", 0),
            streak_days=streak,
            accuracy_rate=sr_stats.get("average_mastery", 0),
            domain_progress=domain_progress,
            daily_activity=daily_activity,
            due_today=sr_stats.get("due_today", 0),
            completed_today=completed_today,
            daily_goal=daily_goal,
            overdue=sr_stats.get("overdue", 0),
        )
        
    except Exception as e:
        logger.error("Feed: Error getting stats", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/quizzes")
async def get_quiz_history(
    current_user: dict = Depends(get_current_user),
):
    """Get history of quizzes created for the user."""
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        feed_service = FeedService(pg_client, neo4j_client)
        
        quizzes = await feed_service.get_user_quizzes(str(current_user["id"]))
        
        # Helper to fetch concept names for grouping
        # This is a bit expensive but necessary for "grouped by topic"
        # We collect unique concept_ids
        concept_ids = list(set(q["concept_id"] for q in quizzes if q.get("concept_id")))
        
        concept_map = {}
        if concept_ids:
             # Neo4j query
             query = "MATCH (c:Concept) WHERE c.id IN $ids RETURN c.id as id, c.name as name"
             result = await neo4j_client.execute_query(query, {"ids": concept_ids})
             for row in result:
                 concept_map[row["id"]] = row["name"]
        
        # Annotate quizzes
        for q in quizzes:
            q["topic"] = concept_map.get(q["concept_id"], "General Knowledge")
            
        return {"quizzes": quizzes}
        
    except Exception as e:
        logger.error("Feed: Error getting quiz history", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/due-count")
async def get_due_count(
    current_user: dict = Depends(get_current_user),
):
    """Get quick count of items due for review."""
    try:
        pg_client = await get_postgres_client()
        sr_service = SpacedRepetitionService(pg_client)
        
        user_id = str(current_user["id"])
        stats = await sr_service.get_user_stats(user_id)
        
        return {
            "due_today": stats.get("due_today", 0),
            "overdue": stats.get("overdue", 0),
            "total": stats.get("due_today", 0) + stats.get("overdue", 0),
        }
        
    except Exception as e:
        logger.error("Feed: Error getting due count", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/{item_id}/like")
async def toggle_like(
    item_id: str,
    item_type: str,
    current_user: dict = Depends(get_current_user),
):
    """Toggle like status for a feed item (flashcard or quiz)."""
    try:
        pg_client = await get_postgres_client()
        user_id = str(current_user["id"])
        if item_type == "flashcard":
            table = "flashcards"
        elif item_type in ["mcq", "fill_blank", "quiz"]:
            table = "quizzes"
        else:
            raise HTTPException(status_code=400, detail=f"Invalid item_type: {item_type}")
        
        # Toggle the boolean
        await pg_client.execute_update(
            f"UPDATE {table} SET is_liked = NOT is_liked WHERE id = :item_id AND user_id = :user_id",
            {"item_id": item_id, "user_id": user_id}
        )
        
        # Return new status
        result = await pg_client.execute_query(
            f"SELECT is_liked FROM {table} WHERE id = :item_id AND user_id = :user_id",
            {"item_id": item_id, "user_id": user_id}
        )
        
        return {"id": item_id, "is_liked": result[0]["is_liked"] if result else False}
        
    except Exception as e:
        logger.error("Feed: Error toggling like", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{item_id}/save")
async def toggle_save(
    item_id: str,
    item_type: str,
    current_user: dict = Depends(get_current_user),
):
    """Toggle save status for a feed item (flashcard or quiz)."""
    try:
        pg_client = await get_postgres_client()
        user_id = str(current_user["id"])
        if item_type == "flashcard":
            table = "flashcards"
        elif item_type in ["mcq", "fill_blank", "quiz"]:
            table = "quizzes"
        else:
            raise HTTPException(status_code=400, detail=f"Invalid item_type: {item_type}")
        
        # Toggle the boolean
        await pg_client.execute_update(
            f"UPDATE {table} SET is_saved = NOT is_saved WHERE id = :item_id AND user_id = :user_id",
            {"item_id": item_id, "user_id": user_id}
        )
        
        # Return new status
        result = await pg_client.execute_query(
            f"SELECT is_saved FROM {table} WHERE id = :item_id AND user_id = :user_id",
            {"item_id": item_id, "user_id": user_id}
        )
        
        return {"id": item_id, "is_saved": result[0]["is_saved"] if result else False}
        
    except Exception as e:
        logger.error("Feed: Error toggling save", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Topic Quiz Generation
# ============================================================================


class TopicQuizRequest(BaseModel):
    """Request for generating a quiz on a topic."""
    user_id: str = "00000000-0000-0000-0000-000000000001"
    # Target pool size (internal preference, user doesn't specify)
    target_pool_size: int = 20
    force_research: bool = False


class QuizQuestion(BaseModel):
    """A single quiz question."""
    question: str
    options: list[str]
    correct_answer: str
    explanation: str


@router.post("/quiz/topic/{topic_name}")
async def generate_topic_quiz(
    topic_name: str,
    request: TopicQuizRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Generate a quiz on a specific topic.
    
    Delegates to FeedService for batch generation.
    Returns a subset of questions for immediate practice.
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        user_id = str(current_user["id"])
        
        feed_service = FeedService(pg_client, neo4j_client)
        
        return await feed_service.generate_quiz_batch(
            topic_name=topic_name,
            user_id=user_id,
            target_size=request.target_pool_size,
            force_research=request.force_research,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Quiz generation: Error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/resources/{concept_name}")
async def get_resources_for_concept(
    concept_name: str,
    current_user: dict = Depends(get_current_user),
    resource_type: Optional[str] = Query(default=None),
):
    """
    Get all resources linked to a concept.
    
    Usage: "Pull my resources for cross entropy"
    
    Returns notes, saved responses, and concept definitions
    related to the specified concept name.
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        user_id = str(current_user["id"])
        resources = []
        
        # Get notes
        notes_query = """
        SELECT id, title, content_text, resource_type, source_url, created_at
        FROM notes
        WHERE user_id = :user_id
          AND (content_text ILIKE :pattern OR title ILIKE :pattern)
        """
        params = {
            "user_id": user_id,
            "pattern": f"%{concept_name}%",
        }
        
        if resource_type:
            notes_query += " AND resource_type = :resource_type"
            params["resource_type"] = resource_type
        
        notes_query += " ORDER BY created_at DESC LIMIT 20"
        
        notes = await pg_client.execute_query(notes_query, params)
        
        for note in notes:
            resources.append({
                "type": "note",
                "id": str(note.get("id")),
                "title": note.get("title") or "Untitled",
                "preview": note.get("content_text", "")[:200] + "...",
                "resource_type": note.get("resource_type"),
                "source_url": note.get("source_url"),
                "created_at": str(note.get("created_at")),
            })
        
        # Get saved responses
        saved_query = """
        SELECT sr.id, sr.topic, sr.content, sr.created_at
        FROM saved_responses sr
        WHERE sr.user_id = :user_id
          AND (sr.content ILIKE :pattern OR sr.topic ILIKE :pattern)
        ORDER BY sr.created_at DESC
        LIMIT 10
        """
        
        try:
            saved = await pg_client.execute_query(
                saved_query,
                {"user_id": user_id, "pattern": f"%{concept_name}%"}
            )
            
            for s in saved:
                resources.append({
                    "type": "saved_response",
                    "id": str(s.get("id")),
                    "title": s.get("topic") or "Saved Response",
                    "preview": s.get("content", "")[:200] + "...",
                    "created_at": str(s.get("created_at")),
                })
        except Exception as e:
            logger.debug("saved_responses table not available", error=str(e))
        
        # Get concepts from Neo4j
        concepts_query = """
        MATCH (c:Concept)
        WHERE toLower(c.name) CONTAINS toLower($name)
        OPTIONAL MATCH (n:NoteSource)-[:EXPLAINS]->(c)
        RETURN c.id as id, c.name as name, c.definition as definition,
               c.domain as domain, collect(n.id) as linked_notes
        LIMIT 10
        """
        
        concepts = await neo4j_client.execute_query(
            concepts_query,
            {"name": concept_name}
        )
        
        for concept in concepts:
            resources.append({
                "type": "concept",
                "id": concept.get("id"),
                "title": concept.get("name"),
                "preview": concept.get("definition") or "No definition",
                "domain": concept.get("domain"),
                "linked_notes": concept.get("linked_notes", []),
            })
        
        logger.info(
            "get_resources_for_concept",
            concept=concept_name,
            num_resources=len(resources),
        )
        
        return {
            "concept": concept_name,
            "resources": resources,
            "total": len(resources),
        }
        
    except Exception as e:
        logger.error("Feed: Error getting resources", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/schedule")
async def get_active_recall_schedule(
    current_user: dict = Depends(get_current_user),
    days: int = Query(default=30, le=60),
):
    """
    Get upcoming review schedule for the calendar.
    Returns counts of items due per day.
    """
    try:
        pg_client = await get_postgres_client()
        sr_service = SpacedRepetitionService(pg_client)
        
        return await sr_service.get_upcoming_schedule(str(current_user["id"]), days)
        
    except Exception as e:
        logger.error("Feed: Error getting schedule", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
