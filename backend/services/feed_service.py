"""Feed Service - Generates the active recall feed for users.

Combines:
- Spaced repetition due items
- Generated content (MCQs, flashcards)
- User uploads (screenshots, infographics)
- Concept showcases
"""

import random
import asyncio
import uuid
import time
from datetime import datetime, timezone
from typing import Optional

import structlog
import json

from backend.models.feed_schemas import (
    FeedItem,
    FeedItemType,
    FeedResponse,
    FeedFilterRequest,
)
from backend.services.spaced_repetition import SpacedRepetitionService

from backend.agents.content_generator import ContentGeneratorAgent
from backend.agents.web_quiz_agent import WebQuizAgent
from backend.agents.research_agent import WebResearchAgent
from backend.config.llm import get_chat_model

logger = structlog.get_logger()


class FeedService:
    """Service for generating user's learning feed."""
    
    def __init__(self, pg_client, neo4j_client):
        self.pg_client = pg_client
        self.neo4j_client = neo4j_client
        self.sr_service = SpacedRepetitionService(pg_client)
        self.content_generator = ContentGeneratorAgent()
        self.web_quiz_agent = WebQuizAgent()
        self.llm_timeout_seconds = 8
        self._embedding_service = None  # Lazy init for dedup

    async def _get_embedding_service(self):
        """Lazy-initialize embedding service for semantic dedup."""
        if self._embedding_service is None:
            from backend.services.ingestion.embedding_service import EmbeddingService
            self._embedding_service = EmbeddingService()
        return self._embedding_service

    async def _is_duplicate_question(
        self, question_text: str, concept_id: str, user_id: str, threshold: float = 0.85
    ) -> bool:
        """
        Check if a question is semantically similar to existing ones.

        Uses embedding cosine similarity to catch paraphrased duplicates
        that ILIKE matching would miss.
        """
        try:
            # Quick text-based check first (cheap)
            existing = await self.pg_client.execute_query(
                """
                SELECT question_text FROM quizzes
                WHERE concept_id = :concept_id AND user_id = :user_id
                LIMIT 20
                """,
                {"concept_id": concept_id, "user_id": user_id},
            )
            if not existing:
                return False

            # Exact match check
            existing_texts = [r["question_text"] for r in existing]
            if question_text.strip().lower() in [t.strip().lower() for t in existing_texts]:
                return True

            # Semantic similarity check via embeddings
            emb_service = await self._get_embedding_service()
            batch_texts = [question_text] + existing_texts
            embeddings = await emb_service.embed_batch(batch_texts)
            if len(embeddings) < 2:
                return False

            query_emb = embeddings[0]
            for existing_emb in embeddings[1:]:
                # Cosine similarity (embeddings are normalized by MRL)
                dot_product = sum(a * b for a, b in zip(query_emb, existing_emb))
                if dot_product > threshold:
                    logger.info(
                        "Semantic dedup: duplicate detected",
                        similarity=round(dot_product, 3),
                        concept_id=concept_id,
                    )
                    return True

            return False
        except Exception as e:
            logger.warning("Semantic dedup check failed", error=str(e))
            return False  # Fail open — allow the question

    async def _get_few_shot_examples(
        self, concept_id: str, user_id: str, limit: int = 2
    ) -> list[dict]:
        """
        Fetch high-quality past MCQs as few-shot examples.

        Retrieves liked/saved questions or recently correct ones to guide generation.
        """
        try:
            rows = await self.pg_client.execute_query(
                """
                SELECT question_text, options_json, explanation
                FROM quizzes
                WHERE user_id = :user_id
                  AND concept_id = :concept_id
                  AND (is_liked = true OR is_saved = true)
                ORDER BY created_at DESC
                LIMIT :limit
                """,
                {"user_id": user_id, "concept_id": concept_id, "limit": limit},
            )
            if not rows:
                # Fallback: any recent question for this concept
                rows = await self.pg_client.execute_query(
                    """
                    SELECT question_text, options_json, explanation
                    FROM quizzes
                    WHERE user_id = :user_id AND concept_id = :concept_id
                    ORDER BY created_at DESC
                    LIMIT :limit
                    """,
                    {"user_id": user_id, "concept_id": concept_id, "limit": limit},
                )

            examples = []
            for row in rows or []:
                options = row.get("options_json")
                if isinstance(options, str):
                    try:
                        options = json.loads(options)
                    except Exception:
                        continue
                examples.append({
                    "question": row["question_text"],
                    "options": options or [],
                    "explanation": row.get("explanation", ""),
                })
            return examples
        except Exception:
            return []

    async def _get_concept_mastery(self, concept_id: str, user_id: str) -> float:
        """Get user's mastery score (0.0-1.0) for a concept."""
        try:
            rows = await self.pg_client.execute_query(
                """
                SELECT score FROM proficiency_scores
                WHERE user_id = :user_id AND concept_id = :concept_id
                LIMIT 1
                """,
                {"user_id": user_id, "concept_id": concept_id},
            )
            if rows:
                return float(rows[0].get("score", 0.0))
        except Exception:
            pass
        return 0.0

    def _basic_concept_showcase(self, concept: dict) -> dict:
        """Fallback concept showcase content without LLM calls."""
        return {
            "concept_name": concept.get("name", "Concept"),
            "definition": concept.get("definition", ""),
            "domain": concept.get("domain", "General"),
            "complexity_score": concept.get("complexity_score", 5),
            "tagline": f"Quick intro to {concept.get('name', 'this concept')}",
            "visual_metaphor": "Think of this as a building block in your knowledge graph.",
            "key_points": [
                concept.get("definition", "")[:120] or "Key idea summary unavailable.",
            ],
            "real_world_example": "Applied when you connect knowledge to real tasks.",
            "connections_note": "Explore prerequisites and related concepts to deepen understanding.",
            "emoji_icon": "📚",
            "prerequisites": concept.get("prerequisites", []),
            "related_concepts": concept.get("related_concepts", []),
        }

    def _basic_mcq_fallback(self, concept: dict) -> dict:
        """Deterministic MCQ fallback when web/LLM generation fails."""
        concept_name = concept.get("name", "this concept")
        definition = (concept.get("definition") or "A core concept in this topic area.").strip()
        truncated_def = definition[:220] + ("..." if len(definition) > 220 else "")

        return {
            "question": f"Which option best describes {concept_name}?",
            "options": [
                {"id": "A", "text": truncated_def, "is_correct": True},
                {"id": "B", "text": f"{concept_name} is unrelated to this domain.", "is_correct": False},
                {"id": "C", "text": f"{concept_name} only applies to hardware setup.", "is_correct": False},
                {"id": "D", "text": f"{concept_name} cannot be learned or practiced.", "is_correct": False},
            ],
            "explanation": f"The best answer aligns with the saved concept definition for {concept_name}.",
            "source": "deterministic_fallback",
        }
    
    async def get_user_streak(self, user_id: str) -> int:
        """Get the user's current streak in days."""
        try:
            # Calculate streak: consecutive days ending today or yesterday
            result = await self.pg_client.execute_query(
                """
                WITH daily_activity AS (
                    SELECT DISTINCT DATE(reviewed_at) as activity_date
                    FROM study_sessions
                    WHERE user_id = :user_id
                    ORDER BY activity_date ASC
                ),
                groups AS (
                    SELECT activity_date,
                           activity_date - (ROW_NUMBER() OVER (ORDER BY activity_date ASC) * INTERVAL '1 day') as grp
                    FROM daily_activity
                ),
                streak_stats AS (
                    SELECT COUNT(*) as streak_days, MAX(activity_date) as last_activity
                    FROM groups
                    GROUP BY grp
                )
                SELECT streak_days
                FROM streak_stats
                WHERE last_activity >= CURRENT_DATE - INTERVAL '1 day'
                ORDER BY last_activity DESC
                LIMIT 1
                """,
                {"user_id": user_id},
            )
            
            if result:
                return result[0].get("streak_days", 0)
            return 0
        except Exception as e:
            logger.warning("FeedService: Error getting streak", error=str(e))
            return 0
    
    async def get_completed_today(self, user_id: str) -> int:
        """Get number of items completed today."""
        try:
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            
            result = await self.pg_client.execute_query(
                """
                SELECT COUNT(*) as count
                FROM study_sessions
                WHERE user_id = :user_id
                  AND reviewed_at >= :today_start
                """,
                {"user_id": user_id, "today_start": today_start},
            )
            
            if result:
                return result[0].get("count", 0)
            return 0
        except Exception as e:
            logger.warning("FeedService: Error getting completed count", error=str(e))
            return 0
    
    async def get_user_domains(self, user_id: str) -> list[str]:
        """Get all domains the user has concepts in."""
        try:
            # Get domains from Neo4j
            domains = await self.neo4j_client.execute_query(
                """
                MATCH (c:Concept {user_id: $user_id})
                RETURN DISTINCT c.domain as domain
                ORDER BY domain
                """,
                {"user_id": user_id},
            )
            return [d["domain"] for d in domains if d.get("domain")]
        except Exception as e:
            logger.warning("FeedService: Error getting domains", error=str(e))
            return []

    async def get_domain_mastery(self, user_id: str) -> dict[str, float]:
        """Calculate mastery percentage (0-100) for each domain."""
        try:
            # 1. Get concept -> domain mapping from Neo4j
            concepts_result = await self.neo4j_client.execute_query(
                """
                MATCH (c:Concept {user_id: $user_id})
                RETURN c.id as id, c.domain as domain
                """,
                {"user_id": user_id},
            )
            
            domain_map = {c["id"]: c.get("domain", "General") for c in concepts_result}
            
            # 2. Get scores from Postgres
            scores_result = await self.pg_client.execute_query(
                """
                SELECT concept_id, score 
                FROM proficiency_scores 
                WHERE user_id = :user_id
                """,
                {"user_id": user_id},
            )
            
            score_map = {row["concept_id"]: row["score"] for row in scores_result}
            
            # 3. Aggregate
            domain_totals = {}  # domain -> [total_score, count]
            
            for concept_id, domain in domain_map.items():
                score = float(score_map.get(concept_id, 0.0))
                if domain not in domain_totals:
                    domain_totals[domain] = [0.0, 0]
                
                domain_totals[domain][0] += score
                domain_totals[domain][1] += 1
            
            # 4. Calculate averages
            mastery = {}
            for domain, (total, count) in domain_totals.items():
                if count > 0:
                    mastery[domain] = round((total / count) * 100, 1)
                else:
                    mastery[domain] = 0.0
                    
            return mastery
            
        except Exception as e:
            logger.error("FeedService: Error calculating domain mastery", error=str(e))
            return {}

    async def get_daily_activity(self, user_id: str, days: int = 90) -> list[dict]:
        """Get daily activity stats for heatmap."""
        try:
            query = """
            SELECT 
                DATE(reviewed_at) as date,
                COUNT(*) as reviews_completed,
                COUNT(DISTINCT concept_id) as concepts_learned,
                0 as notes_added, -- Placeholder, ideally join with notes table
                AVG(CASE WHEN is_correct THEN 1 ELSE 0 END) as accuracy
            FROM study_sessions
            WHERE user_id = :user_id
              AND reviewed_at >= CURRENT_DATE - INTERVAL '90 days'
            GROUP BY DATE(reviewed_at)
            ORDER BY date DESC
            """
            
            result = await self.pg_client.execute_query(query, {"user_id": user_id})
            
            return [
                {
                    "date": row["date"].isoformat(),
                    "reviews_completed": row["reviews_completed"],
                    "concepts_learned": row["concepts_learned"],
                    "notes_added": 0, # TODO: Separate query for notes if needed
                    "accuracy": float(row["accuracy"] or 0),
                }
                for row in result
            ]
            
        except Exception as e:
            logger.error("FeedService: Error getting daily activity", error=str(e))
            return []
    
    async def get_due_concepts(self, user_id: str, limit: int = 20) -> list[dict]:
        """Get concepts that are due for review."""
        try:
            # Get due items from spaced repetition service
            due_items = await self.sr_service.get_due_items(
                user_id=user_id,
                limit=limit,
                include_overdue=True,
            )
            
            # Enrich with concept data from Neo4j
            enriched_concepts = []
            for item in due_items:
                concept_id = item["sm2_data"]["item_id"]
                
                # Get concept details
                concept = await self.neo4j_client.get_concept(concept_id, user_id=user_id)
                if concept:
                    enriched_concepts.append({
                        **concept,
                        **item,
                    })
            
            return enriched_concepts
            
        except Exception as e:
            logger.error("FeedService: Error getting due concepts", error=str(e))
            return []
    
    async def get_user_uploads(
        self,
        user_id: str,
        limit: int = 5,
    ) -> list[dict]:
        """Get user's uploaded content (screenshots, infographics)."""
        try:
            # Query for user uploads that haven't been shown recently
            result = await self.pg_client.execute_query(
                """
                SELECT 
                    id, user_id, upload_type, file_url, thumbnail_url,
                    title, description, linked_concepts, created_at
                FROM user_uploads
                WHERE user_id = :user_id
                ORDER BY RANDOM()
                LIMIT :limit
                """,
                {"user_id": user_id, "limit": limit},
            )
            return result
        except Exception as e:
            logger.warning("FeedService: Error getting user uploads", error=str(e))
            return []

    async def get_user_quizzes(self, user_id: str) -> list[dict]:
        """Get all quizzes generated for the user."""
        try:
            # Fetch quizzes
            quizzes = await self.pg_client.execute_query(
                """
                SELECT id, question_text, question_type, options_json, correct_answer, explanation, created_at, concept_id
                FROM quizzes
                WHERE user_id = :user_id
                ORDER BY created_at DESC
                LIMIT 100
                """,
                {"user_id": user_id}
            )
            
            # Enrich with concept names in bulk (simplified)
            # ... (keep existing)

            # Parse options_json (JSONB columns are auto-deserialized by the driver)
            for q in quizzes:
                raw = q.get("options_json")
                if raw:
                    if isinstance(raw, list):
                        # Already deserialized by JSONB driver
                        q["options"] = raw
                    elif isinstance(raw, str):
                        try:
                            q["options"] = json.loads(raw)
                        except Exception:
                            q["options"] = []
                    else:
                        q["options"] = []
                else:
                    q["options"] = []
            
            # Enrich with concept names from Neo4j in bulk? 
            # For now, we will return list. Frontend can maybe show "General" or we try to fetch names.
            # Doing N+1 queries is bad.
            # But we don't have concept names in Postgres?
            # We can check if `concepts` table exists in Postgres? No, Neo4j is source of truth.
            # We'll return concept_id.
            
            return quizzes
        except Exception as e:
            logger.error("FeedService: Error getting user quizzes", error=str(e))
            return []
    
    async def _get_db_content(
        self,
        concept_id: str,
        item_type: FeedItemType,
        user_id: str,
    ) -> Optional[dict]:
        """Try to fetch existing content from DB."""
        if not concept_id:
            return None
            
        try:
            if item_type == FeedItemType.MCQ:
                # Get random MCQ for this concept
                result = await self.pg_client.execute_query(
                    """
                    SELECT * FROM quizzes 
                    WHERE concept_id = :concept_id 
                      AND user_id = :user_id
                      AND question_type = 'mcq'
                    ORDER BY RANDOM() LIMIT 1
                    """,
                    {"concept_id": concept_id, "user_id": user_id}
                )
                if result:
                    row = result[0]
                    options = json.loads(row["options_json"]) if isinstance(row["options_json"], str) else row["options_json"]
                    return {
                        "question": row["question_text"],
                        "options": options,
                        "explanation": row["explanation"],
                        "id": str(row["id"]),
                        "source_url": row.get("source_url"),
                    }

            elif item_type == FeedItemType.TERM_CARD:
                 # Get random Flashcard
                result = await self.pg_client.execute_query(
                    """
                    SELECT * FROM flashcards
                    WHERE concept_id = :concept_id 
                      AND user_id = :user_id
                    ORDER BY RANDOM() LIMIT 1
                    """,
                    {"concept_id": concept_id, "user_id": user_id}
                )
                if result:
                    row = result[0]
                    return {
                        "front": row["front_content"],
                        "back": row["back_content"],
                        "card_type": "basic", # Simplification
                        "id": str(row["id"]),
                        "source_url": row.get("source_url"),
                    }
                    
        except Exception as e:
            logger.warning("FeedService: DB lookup failed", error=str(e))
            
        return None

    async def _get_from_quiz_candidates(self, topic: str, user_id: str) -> Optional[dict]:
        """Try to fetch a pending quiz candidate for this topic."""
        try:
            # Simple text match for now
            result = await self.pg_client.execute_query(
                """
                SELECT id, chunk_text, difficulty 
                FROM quiz_candidates
                WHERE user_id = :user_id 
                  AND topic ILIKE :topic 
                  AND status = 'pending'
                LIMIT 1
                """,
                {"user_id": user_id, "topic": f"%{topic}%"}
            )
            
            if result:
                row = result[0]
                # Mark as processing/generated
                await self.pg_client.execute_update(
                    "UPDATE quiz_candidates SET status = 'generated' WHERE id = :id",
                    {"id": row["id"]}
                )
                return {
                    "text": row["chunk_text"],
                    "difficulty": float(row.get("difficulty", 0.5))
                }
            return None
        except Exception as e:
            logger.warning("FeedService: Error fetching quiz candidate", error=str(e))
            return None

    async def generate_feed_item(
        self,
        user_id: str,
        concept: dict,
        item_type: FeedItemType,
        allow_llm: bool = True,
    ) -> Optional[FeedItem]:
        """Generate a feed item of the specified type for a concept."""
        try:
            content = None
            
            # 1. Try fetching from DB first
            if item_type in [FeedItemType.MCQ, FeedItemType.TERM_CARD] and concept.get("id"):
                 content = await self._get_db_content(concept.get("id"), item_type, user_id)
                 
            if content:
                logger.info("FeedService: Using persisted content", item_type=item_type, concept_id=concept.get("id"))
                feed_kwargs = {
                    "item_type": item_type,
                    "content": content,
                    "concept_id": concept.get("id"),
                    "concept_name": concept.get("name"),
                    "domain": concept.get("domain"),
                    "due_date": concept.get("sm2_data", {}).get("next_review"),
                    "priority_score": concept.get("priority_score", 1.0),
                }
                if isinstance(content, dict) and content.get("id"):
                    feed_kwargs["id"] = str(content.get("id"))
                return FeedItem(**feed_kwargs)

            if not allow_llm:
                fallback_content = self._basic_concept_showcase(concept)
                return FeedItem(
                    item_type=FeedItemType.CONCEPT_SHOWCASE,
                    content=fallback_content,
                    concept_id=concept.get("id"),
                    concept_name=concept.get("name"),
                    domain=concept.get("domain"),
                    due_date=concept.get("sm2_data", {}).get("next_review"),
                    priority_score=concept.get("priority_score", 0.6),
                )
            
            # 2. Try Web Augmentation (for MCQs only) - DISABLED TO PREVENT VERCEL TIMEOUTS
            web_search_failed = False
            ENABLE_WEB_SEARCH_FALLBACK = False  # Disabled: causes 10s timeout on Vercel
            
            if item_type == FeedItemType.MCQ and not content and ENABLE_WEB_SEARCH_FALLBACK:
                try:
                    # Only search if we really lack content
                    logger.info("FeedService: DB empty, trying Web Search", concept=concept.get("name"))
                    web_mcqs, source_url = await asyncio.wait_for(
                        self.web_quiz_agent.find_quizzes(
                            concept_name=concept.get("name"),
                            domain=concept.get("domain", "General"),
                        ),
                        timeout=self.llm_timeout_seconds,
                    )
                    
                    if web_mcqs:
                         # Save ALL valid web MCQs to DB immediately
                         pg_client = self.pg_client
                         saved_count = 0
                         first_saved_item = None
                         
                         for mcq in web_mcqs:
                             try:
                                q_id = str(uuid.uuid4())
                                await pg_client.execute_update(
                                    """
                                    INSERT INTO quizzes (id, user_id, concept_id, question_text, question_type, 
                                                         options_json, correct_answer, explanation, created_at, source, source_url)
                                    VALUES (:id, :user_id, :concept_id, :question_text, 'mcq',
                                            :options_json, :correct_answer, :explanation, NOW(), 'web_search', :source_url)
                                    """,
                                    {
                                        "id": q_id,
                                        "user_id": user_id,
                                        "concept_id": concept.get("id") or "unknown",
                                        "question_text": mcq.question,
                                        "options_json": json.dumps([o.model_dump() for o in mcq.options]),
                                        "correct_answer": next((o.id for o in mcq.options if o.is_correct), "A"),
                                        "explanation": mcq.explanation,
                                        "source_url": source_url,
                                    }
                                )
                                saved_count += 1
                                if not first_saved_item:
                                    first_saved_item = {
                                        "question": mcq.question,
                                        "options": [o.model_dump() for o in mcq.options],
                                        "explanation": mcq.explanation,
                                        "id": q_id,
                                        "source_url": source_url,
                                    }
                             except Exception as e:
                                 logger.warning("FeedService: Failed to save web MCQ", error=str(e))
                                 
                         if first_saved_item:
                             logger.info("FeedService: Using Web content", items_found=saved_count)
                             feed_kwargs = {
                                "item_type": item_type,
                                "content": first_saved_item,
                                "concept_id": concept.get("id"),
                                "concept_name": concept.get("name"),
                                "domain": concept.get("domain"),
                                "priority_score": concept.get("priority_score", 0.9), # Web content slightly lower than human/generated
                             }
                             if first_saved_item.get("id"):
                                feed_kwargs["id"] = str(first_saved_item.get("id"))
                             return FeedItem(**feed_kwargs)
                except Exception as e:
                    logger.warning("FeedService: Web search failed", error=str(e))
                    web_search_failed = True

            # 3. If no content, generate it
            content = {}
            if item_type == FeedItemType.CONCEPT_SHOWCASE:
                content = await asyncio.wait_for(
                    self.content_generator.generate_concept_showcase(
                        concept_name=concept["name"],
                        concept_definition=concept.get("definition", ""),
                        domain=concept.get("domain", "General"),
                        complexity_score=concept.get("complexity_score", 5),
                        prerequisites=concept.get("prerequisites", []),
                        related_concepts=concept.get("related_concepts", []),
                    ),
                    timeout=self.llm_timeout_seconds,
                )
                
            elif item_type == FeedItemType.MCQ:
                try:
                    # Check for "Lazy Gen" candidates first
                    candidate = await self._get_from_quiz_candidates(concept["name"], user_id)
                    context_append = ""
                    if candidate:
                        logger.info("FeedService: Using Lazy Quiz Candidate", concept=concept["name"])
                        context_append = f"\n\nContext Source: {candidate['text']}"

                    # Fetch mastery + few-shot examples for quality generation
                    concept_id = concept.get("id", "")
                    mastery = await self._get_concept_mastery(concept_id, user_id)
                    few_shots = await self._get_few_shot_examples(concept_id, user_id)

                    mcq = await asyncio.wait_for(
                        self.content_generator.generate_mcq(
                            concept_name=concept["name"],
                            concept_definition=concept.get("definition", "") + context_append,
                            related_concepts=concept.get("related_concepts", []),
                            difficulty=int(concept.get("complexity_score", 5)),
                            mastery_score=mastery,
                            few_shot_examples=few_shots,
                        ),
                        timeout=self.llm_timeout_seconds,
                    )

                    # Semantic deduplication: skip if too similar to existing
                    if concept_id:
                        is_dup = await self._is_duplicate_question(
                            mcq.question, concept_id, user_id
                        )
                        if is_dup:
                            logger.info("FeedService: MCQ is duplicate, regenerating", concept=concept.get("name"))
                            # One retry with higher temperature variation
                            mcq = await asyncio.wait_for(
                                self.content_generator.generate_mcq(
                                    concept_name=concept["name"],
                                    concept_definition=concept.get("definition", "") + context_append,
                                    related_concepts=concept.get("related_concepts", []),
                                    difficulty=int(concept.get("complexity_score", 5)),
                                    mastery_score=mastery,
                                ),
                                timeout=self.llm_timeout_seconds,
                            )

                    content = {
                        "question": mcq.question,
                        "options": [o.model_dump() for o in mcq.options],
                        "explanation": mcq.explanation,
                    }
                    
                    # Save generated MCQ to DB for next time
                    if concept.get("id"):
                         try:
                            q_id = str(uuid.uuid4())
                            await self.pg_client.execute_update(
                                """
                                INSERT INTO quizzes (id, user_id, concept_id, question_text, question_type, 
                                                     options_json, correct_answer, explanation, created_at)
                                VALUES (:id, :user_id, :concept_id, :question_text, 'mcq',
                                        :options_json, :correct_answer, :explanation, NOW())
                                """,
                                {
                                    "id": q_id,
                                    "user_id": user_id,
                                    "concept_id": concept.get("id"),
                                    "question_text": mcq.question,
                                    "options_json": json.dumps(content["options"]),
                                    "correct_answer": next((o.id for o in mcq.options if o.is_correct), "A"),
                                    "explanation": mcq.explanation,
                                }
                            )
                            content["id"] = q_id
                         except Exception as e:
                             logger.warning("FeedService: Failed to save generated MCQ", error=str(e))
                except Exception as e:
                    logger.warning(
                        "FeedService: MCQ generation failed, using deterministic fallback",
                        concept=concept.get("name"),
                        web_search_failed=web_search_failed,
                        error=str(e),
                    )
                    content = self._basic_mcq_fallback(concept)
                
            elif item_type == FeedItemType.FILL_BLANK:
                fill_blank = await asyncio.wait_for(
                    self.content_generator.generate_fill_blank(
                        concept_name=concept["name"],
                        concept_definition=concept.get("definition", ""),
                        difficulty=int(concept.get("complexity_score", 5)),
                    ),
                    timeout=self.llm_timeout_seconds,
                )
                content = {
                    "sentence": fill_blank.sentence,
                    "answers": fill_blank.answers,
                    "hint": fill_blank.hint,
                }
                
            elif item_type == FeedItemType.TERM_CARD:
                flashcards = await asyncio.wait_for(
                    self.content_generator.generate_flashcards(
                        concept_name=concept["name"],
                        concept_definition=concept.get("definition", ""),
                        related_concepts=concept.get("related_concepts", []),
                        num_cards=1,
                    ),
                    timeout=self.llm_timeout_seconds,
                )
                if flashcards:
                    content = flashcards[0]

            elif item_type == FeedItemType.MERMAID_DIAGRAM:
                # Generate a diagram for the concept
                metadata = {}
                if concept.get("related_concepts"):
                    metadata["related"] = concept["related_concepts"]
                
                # Create a mini-graph of concept + neighbors for the diagram
                diagram_concepts = [concept]
                # We would ideally fetch full objects for related concepts here
                # For now using available data
                
                mermaid = await asyncio.wait_for(
                    self.content_generator.generate_mermaid_diagram(
                        concepts=diagram_concepts,
                        diagram_type="mindmap", # Default to mindmap for single concept focus
                        title=f"Map: {concept['name']}",
                    ),
                    timeout=self.llm_timeout_seconds,
                )
                content = {
                    "mermaid_code": mermaid.mermaid_code,
                    "title": mermaid.title,
                    "chart_type": mermaid.diagram_type,
                }
            
            if not content:
                return None

            feed_kwargs = {
                "item_type": item_type,
                "content": content,
                "concept_id": concept.get("id"),
                "concept_name": concept.get("name"),
                "domain": concept.get("domain"),
                "due_date": concept.get("sm2_data", {}).get("next_review"),
                "priority_score": concept.get("priority_score", 1.0),
            }
            if isinstance(content, dict) and content.get("id"):
                feed_kwargs["id"] = str(content.get("id"))

            return FeedItem(**feed_kwargs)

        except Exception as e:
            logger.warning(
                "FeedService: LLM generation failed, using fallback card",
                concept=concept.get("name"),
                item_type=item_type,
                error=str(e),
            )
            # Fallback: return a basic concept showcase card from existing data
            # instead of None, so the feed is never empty for users with concepts
            try:
                return FeedItem(
                    item_type=FeedItemType.CONCEPT_SHOWCASE,
                    content=self._basic_concept_showcase(concept),
                    concept_id=concept.get("id"),
                    concept_name=concept.get("name"),
                    domain=concept.get("domain"),
                    priority_score=concept.get("priority_score", 0.5),
                )
            except Exception as e:
                logger.error("FeedService: Failed to generate feed item", concept_name=concept.get("name"), error=str(e), exc_info=True)
                return None
    
    def _static_cold_start_items(self) -> list[FeedItem]:
        """Return pre-built onboarding items that require no LLM calls."""
        return [
            FeedItem(
                id=str(uuid.uuid4()),
                item_type=FeedItemType.CONCEPT_SHOWCASE,
                content={
                    "concept_name": "Welcome to GraphRecall",
                    "definition": "Your personal knowledge graph for active recall learning.",
                    "domain": "Meta-Learning",
                    "complexity_score": 1,
                    "tagline": "Build your second brain, one concept at a time.",
                    "visual_metaphor": "Think of GraphRecall as a mind map that quizzes you.",
                    "key_points": [
                        "Upload notes, PDFs, or images to extract concepts",
                        "Concepts are linked in a knowledge graph",
                        "Spaced repetition keeps knowledge fresh",
                    ],
                    "real_world_example": "Upload your lecture notes and get flashcards automatically.",
                    "connections_note": "",
                    "emoji_icon": "🧠",
                    "prerequisites": [],
                    "related_concepts": [],
                },
                concept_id="cold_start_welcome",
                concept_name="Welcome to GraphRecall",
                domain="Meta-Learning",
                priority_score=1.0,
            ),
            FeedItem(
                id=str(uuid.uuid4()),
                item_type=FeedItemType.TERM_CARD,
                content={
                    "front": "What learning technique involves testing yourself on material rather than re-reading?",
                    "back": "Active Recall - retrieving information from memory strengthens long-term retention far more than passive review.",
                    "card_type": "basic",
                },
                concept_id="cold_start_active_recall",
                concept_name="Active Recall",
                domain="Meta-Learning",
                priority_score=0.9,
            ),
            FeedItem(
                id=str(uuid.uuid4()),
                item_type=FeedItemType.TERM_CARD,
                content={
                    "front": "What is Spaced Repetition?",
                    "back": "A learning technique that reviews material at increasing intervals. Items you know well are shown less often; items you struggle with appear more frequently.",
                    "card_type": "basic",
                },
                concept_id="cold_start_spaced_rep",
                concept_name="Spaced Repetition",
                domain="Meta-Learning",
                priority_score=0.8,
            ),
            FeedItem(
                id=str(uuid.uuid4()),
                item_type=FeedItemType.TERM_CARD,
                content={
                    "front": "How does a Knowledge Graph help learning?",
                    "back": "A Knowledge Graph connects concepts through relationships, showing prerequisites and related ideas. This mirrors how the brain organizes information -- through associations, not isolation.",
                    "card_type": "application",
                },
                concept_id="cold_start_kg",
                concept_name="Knowledge Graphs",
                domain="Meta-Learning",
                priority_score=0.7,
            ),
        ]

    async def generate_cold_start_feed(self, request: FeedFilterRequest) -> FeedResponse:
        """Generate a cold start feed for new users.

        Uses static pre-built items as a fast fallback, then attempts to
        generate one LLM-powered item. If the LLM fails, the static items
        are returned immediately so the app never blocks on boot.
        """
        feed_items = self._static_cold_start_items()

        # Attempt to generate one dynamic item, but don't block on failure
        try:
            concept = {
                "id": "cold_start_dynamic",
                "name": "Active Recall",
                "definition": "A learning strategy where you actively retrieve information from memory, rather than passively reviewing material.",
                "domain": "Meta-Learning",
                "complexity_score": 3,
                "priority_score": 0.6,
            }
            item = await self.generate_feed_item(request.user_id, concept, FeedItemType.MCQ)
            if item:
                feed_items.append(item)
        except Exception as e:
            logger.warning("FeedService: Cold start dynamic item failed, using static only", error=str(e))

        return FeedResponse(
            items=feed_items,
            total_due_today=len(feed_items),
            completed_today=0,
            streak_days=0,
            domains=["Meta-Learning"],
        )

    async def get_all_user_concepts(self, user_id: str, limit: int = 20) -> list[dict]:
        """Get ALL user concepts from Neo4j (not just spaced-rep due ones).

        This is the fallback when no spaced repetition due items exist
        but the user has concepts in their knowledge graph.
        """
        try:
            concepts = await self.neo4j_client.execute_query(
                """
                MATCH (c:Concept {user_id: $user_id})
                OPTIONAL MATCH (c)-[:RELATED_TO]->(related:Concept {user_id: $user_id})
                WITH c, collect(related.name)[0..5] as related_names
                RETURN {
                    id: c.id,
                    name: c.name,
                    definition: c.definition,
                    domain: c.domain,
                    complexity_score: c.complexity_score,
                    confidence: coalesce(c["confidence"], 0.8),
                    related_concepts: related_names
                } AS concept
                ORDER BY c.created_at DESC
                LIMIT $limit
                """,
                {"user_id": user_id, "limit": limit},
            )
            return [c["concept"] for c in concepts]
        except Exception as e:
            logger.error("FeedService: Error getting all concepts", error=str(e))
            return []

    async def get_feed(
        self,
        request: FeedFilterRequest,
    ) -> FeedResponse:
        """
        Generate the user's learning feed.
        """
        logger.info(
            "FeedService: Generating feed",
            user_id=request.user_id,
            max_items=request.max_items,
        )

        # Get due concepts from spaced repetition
        due_concepts = await self.get_due_concepts(
            user_id=request.user_id,
            limit=request.max_items * 2,
        )

        # If no spaced-rep due items, check if user has ANY concepts
        if not due_concepts:
            all_concepts = await self.get_all_user_concepts(
                user_id=request.user_id,
                limit=request.max_items * 2,
            )

            if all_concepts:
                logger.info(
                    "FeedService: No due items but user has concepts, generating from all concepts",
                    concept_count=len(all_concepts),
                )
                # Use all concepts as if they were due
                due_concepts = all_concepts
            else:
                # Truly new user with no concepts at all
                logger.info("FeedService: Cold start - no concepts found")
                return await self.generate_cold_start_feed(request)
        
        feed_items: list[FeedItem] = []
        
        # Determine if we've hit the daily generation limit before trying to generate new content
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        q_generated_res = await self.pg_client.execute_query(
            """
            SELECT COUNT(*) as cnt 
            FROM quizzes q
            WHERE q.user_id = :uid AND q.created_at >= :today AND q.source = 'batch_gen'
            """,
            {"uid": request.user_id, "today": today_start}
        )
        generated_today = q_generated_res[0]["cnt"] if q_generated_res else 0
        generation_limit_reached = generated_today >= 20
        
        # Filter by domains if specified
        if request.domains:
            due_concepts = [
                c for c in due_concepts
                if c.get("domain") in request.domains
            ]
        
        # Determine content type distribution
        allowed_types = request.item_types or list(FeedItemType)

        # Parallelize generation
        tasks = []
        
        # Limit candidates to prevents spawning too many parallel LLM calls (e.g. max 5)
        candidates = due_concepts[:min(request.max_items, 10)]
        
        # Only attempt new generation if under daily limit
        if not generation_limit_reached:
            for concept in candidates:
                # Randomly select a content type
                possible_types = [
                    t for t in [
                        FeedItemType.CONCEPT_SHOWCASE,
                        FeedItemType.MCQ,
                        FeedItemType.FILL_BLANK,
                        FeedItemType.MCQ,
                        FeedItemType.TERM_CARD, 
                        FeedItemType.MERMAID_DIAGRAM,
                    ]
                    if t in allowed_types
                ]
                
                if not possible_types:
                    continue
                
                item_type = random.choice(possible_types)
                
                tasks.append(
                    asyncio.create_task(
                        self.generate_feed_item(
                            request.user_id,
                            concept,
                            item_type,
                            allow_llm=True, # We control timeout via asyncio.wait
                        )
                    )
                )
            
        if tasks:
            # Wait for tasks with a hard global timeout (6s to safely fit inside Vercel 10s limit)
            done, pending = await asyncio.wait(tasks, timeout=6.0)
            
            for task in done:
                try:
                    res = await task
                    if res:
                        feed_items.append(res)
                except Exception as e:
                    logger.warning("FeedService: Task failed", error=str(e))
            
            # Cancel pending tasks to free resources
            for task in pending:
                task.cancel()
                
            if not feed_items and not due_concepts:
                 # Only if we truly have nothing and no due concepts
                 pass
        
        # Add user uploads if allowed
        if (
            FeedItemType.SCREENSHOT in allowed_types or
            FeedItemType.INFOGRAPHIC in allowed_types
        ):
            uploads = await self.get_user_uploads(
                user_id=request.user_id,
                limit=min(3, request.max_items - len(feed_items)),
            )
            
            for upload in uploads:
                upload_type = FeedItemType(upload.get("upload_type", "screenshot"))
                if upload_type in allowed_types:
                    upload_content = {
                        "file_url": upload.get("file_url"),
                        "thumbnail_url": upload.get("thumbnail_url"),
                        "title": upload.get("title"),
                        "description": upload.get("description"),
                        "linked_concepts": upload.get("linked_concepts") or [],
                    }
                    feed_kwargs = {
                        "item_type": upload_type,
                        "content": upload_content,
                        "concept_id": None,
                        "concept_name": upload.get("title"),
                        "domain": None,
                        "priority_score": 0.5,  # Lower priority than due items
                        "created_at": upload.get("created_at"),
                    }
                    if upload.get("id"):
                        feed_kwargs["id"] = str(upload.get("id"))
                    feed_items.append(FeedItem(**feed_kwargs))
        
        # Sort by priority
        feed_items.sort(key=lambda x: x.priority_score, reverse=True)

        # Inject Demo Transformer Cards at the very top of the feed for demonstration purposes
        demo_items = [
            FeedItem(
                id=f"demo-transformer-mcq-{uuid.uuid4()}",
                item_type=FeedItemType.MCQ,
                concept_id="demo-transformer",
                concept_name="Transformer Architecture",
                domain="Gen AI",
                priority_score=10.0,
                content={
                    "question": "Which mechanism in the Transformer architecture allows it to weigh the importance of different words in a sequence simultaneously?",
                    "options": [
                        "Recurrent Neural Networks (RNNs)",
                        "Self-Attention Mechanism",
                        "Convolutional Layers",
                        "Long Short-Term Memory (LSTM)"
                    ],
                    "correct_answer": "Self-Attention Mechanism",
                    "explanation": "The self-attention mechanism is a core component of the Transformer model, allowing it to evaluate the importance of all words in a sequence relative to one another at the same time, overcoming the sequential processing limitations of RNNs."
                },
                created_at=datetime.utcnow()
            ),
            FeedItem(
                id=f"demo-transformer-flashcard-{uuid.uuid4()}",
                item_type=FeedItemType.TERM_CARD,
                concept_id="demo-attention",
                concept_name="Attention Mechanism",
                domain="Gen AI",
                priority_score=9.5,
                content={
                    "front": "What role do Queries, Keys, and Values play in the Self-Attention mechanism?",
                    "back": "Queries determine what the current token is looking for, Keys represent what each token offers, and Values hold the actual information. The dot product of a Query and a Key determines the attention weight applied to the corresponding Value."
                },
                created_at=datetime.utcnow()
            ),
            FeedItem(
                id=f"demo-transformer-showcase-{uuid.uuid4()}",
                item_type=FeedItemType.CONCEPT_SHOWCASE,
                concept_id="demo-transformer-2",
                concept_name="Transformer Architecture",
                domain="Gen AI",
                priority_score=9.0,
                content={
                    "title": "The Power of Transformers",
                    "description": "Transformers revolutionized NLP by abandoning recurrence entirely in favor of attention mechanisms, enabling massive parallelization during training and leading to LLMs like GPT-4.",
                    "key_points": [
                        "Introduced in 'Attention Is All You Need' (2017)",
                        "Eliminates sequential processing bottlenecks",
                        "Uses multi-head attention to capture different contextual relationships"
                    ]
                },
                created_at=datetime.utcnow()
            )
        ]
        
        # Prepend the demo items to the feed
        feed_items = demo_items + feed_items
        
        # Get metadata
        sr_stats = await self.sr_service.get_user_stats(request.user_id)
        streak = await self.get_user_streak(request.user_id)
        completed_today = await self.get_completed_today(request.user_id)
        domains = await self.get_user_domains(request.user_id)
        
        return FeedResponse(
            items=feed_items[:request.max_items],
            total_due_today=sr_stats.get("due_today", 0),
            completed_today=completed_today,
            streak_days=streak,
            domains=domains,
        )
    
    async def record_interaction(
        self,
        user_id: str,
        item_id: str,
        item_type: str,
        concept_id: Optional[str],
        interaction_type: str,  # "view", "answer", "skip"
        is_correct: Optional[bool] = None,
        response_time_ms: Optional[int] = None,
    ) -> None:
        """
        Record a user interaction with a feed item.
        
        This is used for:
        - Tracking progress
        - Updating spaced repetition data
        - Analytics
        """
        try:
            # Insert into study_sessions
            await self.pg_client.execute_insert(
                """
                INSERT INTO study_sessions
                    (user_id, concept_id, item_type, interaction_type,
                     is_correct, response_time_ms, reviewed_at, session_type)
                VALUES
                    (:user_id, :concept_id, :item_type, :interaction_type,
                     :is_correct, :response_time_ms, NOW(), :session_type)
                RETURNING id
                """,
                {
                    "user_id": user_id,
                    "concept_id": concept_id,
                    "item_type": item_type,
                    "interaction_type": interaction_type,
                    "is_correct": is_correct,
                    "response_time_ms": response_time_ms,
                    "session_type": "flashcard" if item_type == "flashcard" else "quiz",
                },
            )
            
            logger.info(
                "FeedService: Interaction recorded",
                user_id=user_id,
                item_type=item_type,
                is_correct=is_correct,
            )
            
        except Exception as e:
            logger.error(
                "FeedService: Error recording interaction",
                error=str(e),
            )

    async def get_daily_goal(self, user_id: str) -> int:
        """
        Calculate fixed daily goal:
        Goal = (Total Scheduled Due Now) + (Scheduled Items Completed Today)
        Excludes items created Today if they are ad-hoc.
        """
        try:
            # 1. Current Due (SR)
            due_result = await self.sr_service.get_due_items(user_id)
            current_due_count = len(due_result)
            
            # 2. Completed Today (Scheduled Only)
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            
            completed_total = await self.get_completed_today(user_id)
            
            # Count ad-hoc completed (Created today)
            adhoc_completed = 0
            try:
                # Check quizzes (approximation)
                q_res = await self.pg_client.execute_query(
                    """
                    SELECT COUNT(*) as cnt 
                    FROM study_sessions s
                    JOIN quizzes q ON (s.item_id = q.id AND s.item_type='quiz')
                    WHERE s.user_id = :uid 
                      AND s.reviewed_at >= :today
                      AND q.created_at >= :today
                      AND q.source = 'batch_gen'
                    """,
                    {"uid": user_id, "today": today_start}
                )
                if q_res: adhoc_completed += q_res[0]["cnt"]
            except Exception:
                pass

            # Subtract ad-hoc from total completed
            completed_scheduled = max(0, completed_total - adhoc_completed)
            
            # If current_due is 0, goal is completed_scheduled.
            total_goal = current_due_count + completed_scheduled
            
            # Enforce hard limit of 20 maximum generated items per day in the feed
            q_generated_res = await self.pg_client.execute_query(
                """
                SELECT COUNT(*) as cnt 
                FROM quizzes q
                WHERE q.user_id = :uid AND q.created_at >= :today AND q.source = 'batch_gen'
                """,
                {"uid": user_id, "today": today_start}
            )
            generated_today = q_generated_res[0]["cnt"] if q_generated_res else 0
            
            if generated_today >= 20:
                logger.info("FeedService: Daily quiz generation limit (20) reached.", user_id=user_id, generated_today=generated_today)
                
            return total_goal
        except Exception as e:
            logger.error("get_daily_goal error", error=str(e))
            return 20

    async def ensure_weekly_buffer(self, user_id: str):
        """
        Background task: Checks a random concept and ensures diversified content buffer exists.
        """
        try:
            # Pick a random concept
            res = await self.neo4j_client.execute_query(
                "MATCH (c:Concept {user_id: $user_id}) WHERE rand() < 0.2 RETURN c.name as name LIMIT 1",
                {"user_id": user_id},
            )
            if not res: return
            
            topic = res[0]["name"]
            
            # Check existing item count (approximate by checking quizzes)
            cnt_res = await self.pg_client.execute_query(
                "SELECT count(*) as c FROM quizzes WHERE concept_id IN (SELECT concept_id FROM proficiency_scores WHERE user_id = :uid)",
                {"uid": user_id}
            )
            count = cnt_res[0]["c"] if cnt_res else 0
            
            if count < 20:
                logger.info("Buffer: Low content, generating mixed batch", topic=topic, count=count)
                await self.generate_content_batch(topic, user_id, target_size=15)
                
        except Exception as e:
            logger.warning("ensure_weekly_buffer error", error=str(e))

    async def generate_content_batch(self, topic_name: str, user_id: str, target_size: int = 15, force_research: bool = False):
        """Generates a diversified batch of content (MCQs, Term Cards, Code, etc.) for a topic."""
        try:
            # Step 0: Resolve Topic to Concept ID
            concept_id = None
            concept_def = ""
            try:
                concept_res = await self.neo4j_client.execute_query(
                    "MATCH (c:Concept {user_id: $user_id}) WHERE toLower(c.name) = toLower($name) RETURN c.id as id, c.definition as def LIMIT 1",
                    {"name": topic_name, "user_id": user_id}
                )
                if concept_res:
                    concept_id = concept_res[0]["id"]
                    concept_def = concept_res[0]["def"]
            except Exception:
                pass

            # Generate logic
            research_agent = WebResearchAgent(self.neo4j_client, self.pg_client)
            research_result = await research_agent.research_topic(
                topic=topic_name,
                user_id=user_id,
                force=force_research,
            )
            
            content_text = concept_def + "\n" + (research_result.get("summary") or "")
            
            # Use Mixed Generator
            new_items = await self.content_generator.generate_mixed_batch(
                topic=topic_name,
                definition=content_text[:6000],
                count=target_size
            )
            
            saved_count = 0
            for item in new_items:
                itype = item.get("type")
                content = item.get("content")
                if not content: continue

                try:
                    item_id = str(uuid.uuid4())
                    
                    if itype in ["mcq", "fill_blank", "code_challenge"]:
                        # Save to quizzes table
                        await self.pg_client.execute_update(
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
                                "opts": json.dumps(content.get("options", [])),
                                "correct": str(content.get("is_correct") or content.get("solution_code") or content.get("answers", [""])[0]),
                                "exp": content.get("explanation", ""),
                                "lang": content.get("language"),
                                "icode": content.get("initial_code")
                            }
                        )
                    elif itype == "term_card":
                        # Save to flashcards table
                        await self.pg_client.execute_update(
                            """
                            INSERT INTO flashcards (id, user_id, concept_id, front_content, back_content, created_at, source)
                            VALUES (:id, :uid, :cid, :front, :back, NOW(), 'batch_gen')
                            """,
                            {
                                "id": item_id,
                                "uid": user_id,
                                "cid": concept_id,
                                "front": content.get("front"),
                                "back": content.get("back")
                            }
                        )
                    else:
                        # Save to generated_content table
                        await self.pg_client.execute_update(
                            """
                            INSERT INTO generated_content (id, user_id, concept_id, content_type, content_json, created_at)
                            VALUES (:id, :uid, :cid, :ctype, :cjson, NOW())
                            """,
                            {
                                "id": item_id,
                                "uid": user_id,
                                "cid": concept_id or "unknown",
                                "ctype": "mermaid" if itype == "diagram" else itype,
                                "cjson": json.dumps(content)
                            }
                        )
                    saved_count += 1
                except Exception as e:
                    logger.warning("FeedService: Failed to save batch item", type=itype, error=str(e))
            
            return {"status": "generated", "generated": saved_count}
            
        except Exception as e:
            logger.error("generate_content_batch error", error=str(e))
            return {"status": "error", "error": str(e)}
