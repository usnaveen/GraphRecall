"""Feed Router - Active Recall Feed Endpoints."""

import json
import uuid
import random
import asyncio
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
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
        user_settings = (current_user.get("settings_json") or {})
        if isinstance(user_settings, str):
            user_settings = json.loads(user_settings)
        algorithm = user_settings.get("sr_algorithm", "sm2")
        sr_service = SpacedRepetitionService(pg_client, algorithm=algorithm)

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
                "MATCH (c:Concept {user_id: $user_id}) RETURN count(c) as count",
                {"user_id": user_id},
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


@router.get("/saved")
async def get_saved_items(
    current_user: dict = Depends(get_current_user),
):
    """Get all saved quizzes and flashcards for the user."""
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        user_id = str(current_user["id"])

        # Fetch saved quizzes
        saved_quizzes = await pg_client.execute_query(
            """
            SELECT id, question_text, question_type, options_json, correct_answer, explanation, concept_id, source_url, created_at
            FROM quizzes
            WHERE user_id = :uid AND is_saved = TRUE
            ORDER BY created_at DESC
            """,
            {"uid": user_id},
        )

        # Fetch saved flashcards
        saved_flashcards = await pg_client.execute_query(
            """
            SELECT id, front_content, back_content, concept_id, created_at
            FROM flashcards
            WHERE user_id = :uid AND is_saved = TRUE
            ORDER BY created_at DESC
            """,
            {"uid": user_id},
        )

        # Resolve concept names from Neo4j
        concept_ids = list(
            set(
                q.get("concept_id")
                for q in (saved_quizzes + saved_flashcards)
                if q.get("concept_id")
            )
        )
        concept_map = {}
        if concept_ids:
            try:
                result = await neo4j_client.execute_query(
                    "MATCH (c:Concept) WHERE c.id IN $ids RETURN c.id as id, c.name as name",
                    {"ids": concept_ids},
                )
                for row in result:
                    concept_map[row["id"]] = row["name"]
            except Exception:
                pass

        items = []

        for q in saved_quizzes:
            opts = q.get("options_json")
            if isinstance(opts, str):
                opts = json.loads(opts)
            items.append({
                "id": q["id"],
                "type": q.get("question_type", "mcq"),
                "question_text": q["question_text"],
                "options": opts or [],
                "correct_answer": q.get("correct_answer", ""),
                "explanation": q.get("explanation", ""),
                "topic": concept_map.get(q.get("concept_id"), "General"),
                "source_url": q.get("source_url", ""),
                "created_at": str(q.get("created_at", "")),
                "item_category": "quiz",
            })

        for f in saved_flashcards:
            items.append({
                "id": f["id"],
                "type": "flashcard",
                "front_content": f["front_content"],
                "back_content": f["back_content"],
                "topic": concept_map.get(f.get("concept_id"), "General"),
                "created_at": str(f.get("created_at", "")),
                "item_category": "flashcard",
            })

        return {"items": items, "total": len(items)}

    except Exception as e:
        logger.error("Feed: Error getting saved items", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/quizzes")
async def get_quiz_history(
    current_user: dict = Depends(get_current_user),
):
    """Get history of quizzes AND flashcards created for the user."""
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        feed_service = FeedService(pg_client, neo4j_client)
        user_id = str(current_user["id"])

        quizzes = await feed_service.get_user_quizzes(user_id)

        # Also fetch flashcards
        flashcards = []
        try:
            flashcards = await pg_client.execute_query(
                """
                SELECT id, front_content, back_content, concept_id, created_at
                FROM flashcards
                WHERE user_id = :uid
                ORDER BY created_at DESC
                LIMIT 50
                """,
                {"uid": user_id},
            )
        except Exception as e:
            logger.warning("Failed to fetch flashcards for history", error=str(e))

        # Collect all concept IDs
        concept_ids = list(set(
            q.get("concept_id") for q in (quizzes + flashcards) if q.get("concept_id")
        ))

        concept_map = {}
        if concept_ids:
            query = "MATCH (c:Concept) WHERE c.id IN $ids RETURN c.id as id, c.name as name"
            result = await neo4j_client.execute_query(query, {"ids": concept_ids})
            for row in result:
                concept_map[row["id"]] = row["name"]

        # Annotate quizzes with topic
        for q in quizzes:
            q["topic"] = concept_map.get(q.get("concept_id"), "General Knowledge")

        # Convert flashcards to quiz-compatible format
        flashcard_items = []
        for f in flashcards:
            flashcard_items.append({
                "id": f["id"],
                "question_text": f.get("front_content", ""),
                "question_type": "flashcard",
                "options": [],
                "correct_answer": f.get("back_content", ""),
                "explanation": "",
                "concept_id": f.get("concept_id"),
                "topic": concept_map.get(f.get("concept_id"), "General Knowledge"),
                "created_at": str(f.get("created_at", "")),
                "front_content": f.get("front_content", ""),
                "back_content": f.get("back_content", ""),
            })

        # Merge and sort by created_at desc
        all_items = quizzes + flashcard_items
        all_items.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)

        return {"quizzes": all_items}

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
        
        return await feed_service.generate_content_batch(
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


@router.post("/quiz/topic/{topic_name}/stream")
async def generate_topic_quiz_stream(
    topic_name: str,
    request: TopicQuizRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Generate a quiz on a topic with SSE streaming status updates.

    Streams events:
      - type: status  → progress updates (searching notes, web search, generating)
      - type: done    → final result with questions array
      - type: error   → error details
    """
    user_id = str(current_user["id"])

    async def event_stream():
        import json as _json

        def sse(data: dict) -> str:
            return f"data: {_json.dumps(data)}\n\n"

        try:
            pg_client = await get_postgres_client()
            neo4j_client = await get_neo4j_client()
            feed_service = FeedService(pg_client, neo4j_client)

            # Step 1: Resolve concept
            yield sse({"type": "status", "content": "🔍 Searching your knowledge graph..."})
            concept_id = None
            concept_def = ""
            try:
                concept_res = await neo4j_client.execute_query(
                    "MATCH (c:Concept) WHERE toLower(c.name) = toLower($name) RETURN c.id as id, c.definition as def LIMIT 1",
                    {"name": topic_name},
                )
                if concept_res:
                    concept_id = concept_res[0]["id"]
                    concept_def = concept_res[0].get("def") or ""
                    yield sse({"type": "status", "content": f"📚 Found concept: {topic_name}"})
                else:
                    yield sse({"type": "status", "content": f"🌐 Topic not in your graph yet — searching the web..."})
            except Exception:
                pass

            # Step 2: Check for existing quiz questions in DB
            yield sse({"type": "status", "content": "📋 Checking for existing questions..."})
            existing_questions = []
            try:
                existing = await pg_client.execute_query(
                    """
                    SELECT id, question_text, question_type, options_json, correct_answer, explanation, source_url
                    FROM quizzes
                    WHERE user_id = :uid
                      AND (concept_id = :cid OR LOWER(question_text) LIKE :topic_pattern)
                    ORDER BY created_at DESC
                    LIMIT 30
                    """,
                    {
                        "uid": user_id,
                        "cid": concept_id or "__none__",
                        "topic_pattern": f"%{topic_name.lower()}%",
                    },
                )
                for q in existing:
                    opts = q.get("options_json")
                    if isinstance(opts, str):
                        opts = _json.loads(opts)
                    existing_questions.append({
                        "id": q["id"],
                        "question": q["question_text"],
                        "question_type": q.get("question_type", "mcq"),
                        "options": opts or [],
                        "correct_answer": q.get("correct_answer", ""),
                        "explanation": q.get("explanation", ""),
                        "source_url": q.get("source_url", ""),
                        "source": "notes",
                    })
            except Exception as e:
                logger.warning("Quiz stream: error fetching existing", error=str(e))

            if existing_questions:
                yield sse({"type": "status", "content": f"✅ Found {len(existing_questions)} existing questions from your notes"})

            # Step 3: Web research via Tavily
            yield sse({"type": "status", "content": "🌐 Searching the web for quiz material..."})
            research_result = {}
            try:
                from backend.agents.research_agent import WebResearchAgent
                research_agent = WebResearchAgent(neo4j_client, pg_client)
                research_result = await research_agent.research_topic(
                    topic=topic_name,
                    user_id=user_id,
                    force=request.force_research,
                )
                if research_result.get("summary"):
                    yield sse({"type": "status", "content": "📝 Web research complete — synthesising material..."})
                else:
                    yield sse({"type": "status", "content": "📝 Using available resources..."})
            except Exception as e:
                logger.warning("Quiz stream: research failed", error=str(e))
                yield sse({"type": "status", "content": "⚠️ Web search unavailable — using local resources"})

            # Step 4: Generate new questions
            need_new = max(0, request.target_pool_size - len(existing_questions))
            new_questions = []

            if need_new > 0:
                yield sse({"type": "status", "content": f"🧠 Generating {need_new} new questions..."})
                try:
                    content_text = concept_def + "\n" + (research_result.get("summary") or "")
                    new_items = await feed_service.content_generator.generate_mixed_batch(
                        topic=topic_name,
                        definition=content_text[:6000],
                        count=need_new,
                    )

                    for item in new_items:
                        itype = item.get("type")
                        content = item.get("content")
                        if not content:
                            continue

                        item_id = str(uuid.uuid4())

                        # Only return quiz-type items (MCQ, fill_blank, code_challenge)
                        if itype in ["mcq", "fill_blank", "code_challenge"]:
                            try:
                                await pg_client.execute_update(
                                    """
                                    INSERT INTO quizzes (id, user_id, concept_id, question_text, question_type,
                                                        options_json, correct_answer, explanation, created_at, source,
                                                        language, initial_code)
                                    VALUES (:id, :uid, :cid, :q_text, :q_type, :opts, :correct, :exp, NOW(), 'batch_gen', :lang, :icode)
                                    """,
                                    {
                                        "id": item_id,
                                        "uid": user_id,
                                        "cid": concept_id,
                                        "q_text": content.get("question") or content.get("instruction") or content.get("sentence"),
                                        "q_type": itype,
                                        "opts": _json.dumps(content.get("options", [])),
                                        "correct": str(content.get("is_correct") or content.get("solution_code") or content.get("answers", [""])[0]),
                                        "exp": content.get("explanation", ""),
                                        "lang": content.get("language"),
                                        "icode": content.get("initial_code"),
                                    },
                                )
                            except Exception as e:
                                logger.warning("Quiz stream: save failed", error=str(e))

                            new_questions.append({
                                "id": item_id,
                                "question": content.get("question") or content.get("instruction") or content.get("sentence") or "",
                                "question_type": itype,
                                "options": content.get("options", []),
                                "correct_answer": str(content.get("is_correct") or content.get("solution_code") or content.get("answers", [""])[0]),
                                "explanation": content.get("explanation", ""),
                                "source": "web",
                            })
                        elif itype == "term_card":
                            # Save flashcards too
                            try:
                                await pg_client.execute_update(
                                    """
                                    INSERT INTO flashcards (id, user_id, concept_id, front_content, back_content, created_at, source)
                                    VALUES (:id, :uid, :cid, :front, :back, NOW(), 'batch_gen')
                                    """,
                                    {
                                        "id": item_id,
                                        "uid": user_id,
                                        "cid": concept_id,
                                        "front": content.get("front"),
                                        "back": content.get("back"),
                                    },
                                )
                            except Exception:
                                pass

                    yield sse({"type": "status", "content": f"✨ Generated {len(new_questions)} new questions"})

                except Exception as e:
                    logger.error("Quiz stream: generation failed", error=str(e))
                    yield sse({"type": "status", "content": "⚠️ Question generation had issues — showing available questions"})

            # Combine: notes-based first, then web-scraped
            all_questions = existing_questions + new_questions
            total = len(all_questions)

            yield sse({
                "type": "done",
                "questions": all_questions,
                "topic": topic_name,
                "total": total,
                "from_notes": len(existing_questions),
                "from_web": len(new_questions),
            })

        except Exception as e:
            logger.error("Quiz stream: Fatal error", error=str(e))
            yield sse({"type": "error", "content": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
    Returns counts of items due per day, plus topic names.
    """
    try:
        pg_client = await get_postgres_client()
        neo4j_client = await get_neo4j_client()
        sr_service = SpacedRepetitionService(pg_client)

        return await sr_service.get_upcoming_schedule_with_topics(
            str(current_user["id"]), neo4j_client, days
        )

    except Exception as e:
        logger.error("Feed: Error getting schedule", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
