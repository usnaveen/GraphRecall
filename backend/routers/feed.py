"""Feed Router - Active Recall Feed Endpoints."""

import json
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
            overdue=sr_stats.get("overdue", 0),
        )
        
    except Exception as e:
        logger.error("Feed: Error getting stats", error=str(e))
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


# ============================================================================
# Topic Quiz Generation
# ============================================================================


class TopicQuizRequest(BaseModel):
    """Request for generating a quiz on a topic."""
    user_id: str = "00000000-0000-0000-0000-000000000001"
    num_questions: int = 5
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
    
    1. Searches for resources linked to the topic
    2. If insufficient resources, uses web research to create notes
    3. Generates MCQ questions from the content
    4. Returns quiz questions
    
    Use this from the Graph view to quiz yourself on any topic.
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        
        research_agent = WebResearchAgent(neo4j_client, pg_client)
        
        # Step 1: Check if we have enough resources
        user_id = str(current_user["id"])
        research_result = await research_agent.research_topic(
            topic=topic_name,
            user_id=user_id,
            force=request.force_research,
        )
        
        # Step 2: Gather content for quiz generation
        content_parts = []
        
        # Get notes related to topic
        notes_query = """
        SELECT title, content_text, resource_type
        FROM notes
        WHERE user_id = :user_id
          AND (content_text ILIKE :topic_pattern OR title ILIKE :topic_pattern)
        LIMIT 5
        """
        
        notes = await pg_client.execute_query(
            notes_query,
            {"user_id": request.user_id, "topic_pattern": f"%{topic_name}%"}
        )
        
        for note in notes:
            content_parts.append(note.get("content_text", "")[:2000])
        
        # Get concept definitions from Neo4j
        concepts = await neo4j_client.execute_query(
            """
            MATCH (c:Concept)
            WHERE toLower(c.name) CONTAINS toLower($topic)
            RETURN c.name as name, c.definition as definition
            LIMIT 5
            """,
            {"topic": topic_name}
        )
        
        for concept in concepts:
            if concept.get("definition"):
                content_parts.append(f"{concept['name']}: {concept['definition']}")
        
        # Add research summary if available
        if research_result.get("researched") and research_result.get("summary"):
            content_parts.append(research_result["summary"])
            content_parts.extend(research_result.get("key_points", []))
        
        if not content_parts or len(content_parts) < 2:
            # Fallback: Content insufficient, trigger deep research
            logger.info("generate_topic_quiz: Content insufficient, forcing research", topic=topic_name)
            
            research_result = await research_agent.research_topic(
                topic=topic_name,
                user_id=user_id,
                force=True, # Force research since we need content
            )
            
            if research_result.get("summary"):
                content_parts.append(research_result["summary"])
                content_parts.extend(research_result.get("key_points", []))
            else:
                 # Last resort fallback if research fails
                 content_parts.append(f"Generate general knowledge questions about {topic_name}.")
        
        # Step 3: Generate quiz questions using LLM (Gemini)
        llm = get_chat_model(temperature=0.5)
        
        content_text = "\n\n".join(content_parts)
        
        prompt = f"""Generate {request.num_questions} multiple choice quiz questions about {topic_name}.

CONTENT TO USE:
{content_text[:4000]}

Return JSON:
{{
    "questions": [
        {{
            "question": "What is...?",
            "options": ["Option A", "Option B", "Option C", "Option D"],
            "correct_answer": "Option A",
            "explanation": "Brief explanation of why this is correct"
        }}
    ]
}}

Rules:
1. Questions should test understanding, not just memorization
2. Make wrong options plausible but clearly incorrect
3. Keep explanations concise
4. Base questions ONLY on the provided content"""
        
        response = await llm.ainvoke(prompt)
        content = response.content.strip()
        
        # Handle markdown code blocks
        if content.startswith("```json"):
            content = content.split("```json")[1].split("```")[0].strip()
        elif content.startswith("```"):
            content = content.split("```")[1].split("```")[0].strip()
        
        data = json.loads(content)
        questions = data.get("questions", [])
        
        logger.info(
            "generate_topic_quiz",
            topic=topic_name,
            num_questions=len(questions),
            researched=research_result.get("researched", False),
        )
        
        return {
            "topic": topic_name,
            "questions": questions,
            "num_questions": len(questions),
            "sources_used": len(content_parts),
            "researched": research_result.get("researched", False),
            "research_note_id": research_result.get("note_id"),
        }
        
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.error("Quiz generation: JSON parse error", error=str(e))
        raise HTTPException(status_code=500, detail="Failed to generate quiz questions")
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
        logger.error("Get resources: Error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

