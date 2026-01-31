"""Feed Router - Active Recall Feed Endpoints."""

from typing import Optional

import structlog
from fastapi import APIRouter, HTTPException, Query

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

logger = structlog.get_logger()

router = APIRouter(prefix="/api/feed", tags=["Feed"])


@router.get("", response_model=FeedResponse)
async def get_feed(
    user_id: str = Query(
        default="00000000-0000-0000-0000-000000000001",
        description="User ID",
    ),
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
            user_id=user_id,
            max_items=max_items,
            item_types=parsed_types,
            domains=parsed_domains,
        )
        
        return await feed_service.get_feed(request)
        
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
    user_id: str = Query(default="00000000-0000-0000-0000-000000000001"),
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
            user_id=user_id,
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
    user_id: str = Query(default="00000000-0000-0000-0000-000000000001"),
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
        
        # Get various stats
        sr_stats = await sr_service.get_user_stats(user_id)
        streak = await feed_service.get_user_streak(user_id)
        completed_today = await feed_service.get_completed_today(user_id)
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
        except:
            pass
        
        # Get note count
        total_notes = 0
        try:
            result = await pg_client.execute_query(
                "SELECT COUNT(*) as count FROM notes WHERE user_id = :user_id",
                {"user_id": user_id},
            )
            if result:
                total_notes = result[0].get("count", 0)
        except:
            pass
        
        # Calculate domain progress (placeholder - would need more data)
        domain_progress = {domain: 0.5 for domain in domains}  # 50% as placeholder
        
        return UserStats(
            user_id=user_id,
            total_concepts=total_concepts,
            total_notes=total_notes,
            total_reviews=sr_stats.get("total_reviews", 0),
            streak_days=streak,
            accuracy_rate=sr_stats.get("average_mastery", 0),
            domain_progress=domain_progress,
            due_today=sr_stats.get("due_today", 0),
            completed_today=completed_today,
            overdue=sr_stats.get("overdue", 0),
        )
        
    except Exception as e:
        logger.error("Feed: Error getting stats", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/due-count")
async def get_due_count(
    user_id: str = Query(default="00000000-0000-0000-0000-000000000001"),
):
    """Get quick count of items due for review."""
    try:
        pg_client = await get_postgres_client()
        sr_service = SpacedRepetitionService(pg_client)
        
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
    user_id: str = Query(default="00000000-0000-0000-0000-000000000001"),
):
    """Toggle like status for a feed item (flashcard or quiz)."""
    try:
        pg_client = await get_postgres_client()
        table = "flashcards" if item_type == "flashcard" else "quizzes"
        
        # Toggle the boolean
        await pg_client.execute_query(
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
    user_id: str = Query(default="00000000-0000-0000-0000-000000000001"),
):
    """Toggle save status for a feed item (flashcard or quiz)."""
    try:
        pg_client = await get_postgres_client()
        table = "flashcards" if item_type == "flashcard" else "quizzes"
        
        # Toggle the boolean
        await pg_client.execute_query(
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
