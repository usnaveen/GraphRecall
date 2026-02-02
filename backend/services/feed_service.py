"""Feed Service - Generates the active recall feed for users.

Combines:
- Spaced repetition due items
- Generated content (MCQs, flashcards)
- User uploads (screenshots, infographics)
- Concept showcases
"""

import random
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog

from backend.models.feed_schemas import (
    FeedItem,
    FeedItemType,
    FeedResponse,
    FeedFilterRequest,
)
from backend.services.spaced_repetition import SpacedRepetitionService
from backend.services.spaced_repetition import SpacedRepetitionService
from backend.agents.content_generator import ContentGeneratorAgent
from backend.agents.web_quiz_agent import WebQuizAgent

logger = structlog.get_logger()


class FeedService:
    """Service for generating user's learning feed."""
    
    def __init__(self, pg_client, neo4j_client):
        self.pg_client = pg_client
        self.neo4j_client = neo4j_client
        self.sr_service = SpacedRepetitionService(pg_client)
        self.content_generator = ContentGeneratorAgent()
        self.web_quiz_agent = WebQuizAgent()
    
    async def get_user_streak(self, user_id: str) -> int:
        """Get the user's current streak in days."""
        try:
            result = await self.pg_client.execute_query(
                """
                WITH daily_activity AS (
                    SELECT DISTINCT DATE(reviewed_at) as activity_date
                    FROM study_sessions
                    WHERE user_id = :user_id
                    ORDER BY activity_date DESC
                )
                SELECT COUNT(*) as streak
                FROM (
                    SELECT activity_date,
                           activity_date - ROW_NUMBER() OVER (ORDER BY activity_date DESC)::int as grp
                    FROM daily_activity
                ) grouped
                WHERE grp = (
                    SELECT activity_date - ROW_NUMBER() OVER (ORDER BY activity_date DESC)::int
                    FROM daily_activity
                    ORDER BY activity_date DESC
                    LIMIT 1
                )
                """,
                {"user_id": user_id},
            )
            
            if result:
                return result[0].get("streak", 0)
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
                score = score_map.get(concept_id, 0.0)
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
                        "id": str(row["id"])
                    }

            elif item_type == FeedItemType.FLASHCARD:
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
                        "id": str(row["id"])
                    }
                    
        except Exception as e:
            logger.warning("FeedService: DB lookup failed", error=str(e))
            
        return None

    async def generate_feed_item(
        self,
        concept: dict,
        item_type: FeedItemType,
        user_id: str = "default_user", # Added user_id
    ) -> Optional[FeedItem]:
        """Generate a feed item of the specified type for a concept."""
        try:
            content = None
            
            # 1. Try fetching from DB first
            if item_type in [FeedItemType.MCQ, FeedItemType.FLASHCARD] and concept.get("id"):
                 content = await self._get_db_content(concept.get("id"), item_type, user_id)
                 
            if content:
                logger.info("FeedService: Using persisted content", item_type=item_type, concept_id=concept.get("id"))
                return FeedItem(
                    item_type=item_type,
                    content=content,
                    concept_id=concept.get("id"),
                    concept_name=concept.get("name"),
                    domain=concept.get("domain"),
                    due_date=concept.get("sm2_data", {}).get("next_review"),
                    priority_score=concept.get("priority_score", 1.0),
                )
            
            # 2. Try Web Augmentation (for MCQs only)
            if item_type == FeedItemType.MCQ and not content:
                try:
                    # Only search if we really lack content
                    logger.info("FeedService: DB empty, trying Web Search", concept=concept.get("name"))
                    web_mcqs = await self.web_quiz_agent.find_quizzes(
                        concept_name=concept.get("name"), 
                        domain=concept.get("domain", "General")
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
                                                         options_json, correct_answer, explanation, created_at, source)
                                    VALUES (:id, :user_id, :concept_id, :question_text, 'mcq',
                                            :options_json, :correct_answer, :explanation, NOW(), 'web_search')
                                    """,
                                    {
                                        "id": q_id,
                                        "user_id": user_id,
                                        "concept_id": concept.get("id") or "unknown",
                                        "question_text": mcq.question,
                                        "options_json": json.dumps([o.model_dump() for o in mcq.options]),
                                        "correct_answer": next((o.id for o in mcq.options if o.is_correct), "A"),
                                        "explanation": mcq.explanation,
                                    }
                                )
                                saved_count += 1
                                if not first_saved_item:
                                    first_saved_item = {
                                        "question": mcq.question,
                                        "options": [o.model_dump() for o in mcq.options],
                                        "explanation": mcq.explanation,
                                        "id": q_id
                                    }
                             except Exception as e:
                                 logger.warning("FeedService: Failed to save web MCQ", error=str(e))
                                 
                         if first_saved_item:
                             logger.info("FeedService: Using Web content", items_found=saved_count)
                             return FeedItem(
                                item_type=item_type,
                                content=first_saved_item,
                                concept_id=concept.get("id"),
                                concept_name=concept.get("name"),
                                domain=concept.get("domain"),
                                priority_score=concept.get("priority_score", 0.9), # Web content slightly lower than human/generated
                             )
                except Exception as e:
                    logger.warning("FeedService: Web search failed", error=str(e))

            # 3. If no content, generate it
            content = {}
            if item_type == FeedItemType.CONCEPT_SHOWCASE:
                content = await self.content_generator.generate_concept_showcase(
                    concept_name=concept["name"],
                    concept_definition=concept.get("definition", ""),
                    domain=concept.get("domain", "General"),
                    complexity_score=concept.get("complexity_score", 5),
                    prerequisites=concept.get("prerequisites", []),
                    related_concepts=concept.get("related_concepts", []),
                )
                
            elif item_type == FeedItemType.MCQ:
                mcq = await self.content_generator.generate_mcq(
                    concept_name=concept["name"],
                    concept_definition=concept.get("definition", ""),
                    related_concepts=concept.get("related_concepts", []),
                    difficulty=int(concept.get("complexity_score", 5)),
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
                
            elif item_type == FeedItemType.FILL_BLANK:
                fill_blank = await self.content_generator.generate_fill_blank(
                    concept_name=concept["name"],
                    concept_definition=concept.get("definition", ""),
                    difficulty=int(concept.get("complexity_score", 5)),
                )
                content = {
                    "sentence": fill_blank.sentence,
                    "answers": fill_blank.answers,
                    "hint": fill_blank.hint,
                }
                
            elif item_type == FeedItemType.FLASHCARD:
                flashcards = await self.content_generator.generate_flashcards(
                    concept_name=concept["name"],
                    concept_definition=concept.get("definition", ""),
                    related_concepts=concept.get("related_concepts", []),
                    num_cards=1,
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
                
                mermaid = await self.content_generator.generate_mermaid_diagram(
                    concepts=diagram_concepts,
                    diagram_type="mindmap", # Default to mindmap for single concept focus
                    title=f"Map: {concept['name']}",
                )
                content = {
                    "mermaid_code": mermaid.mermaid_code,
                    "title": mermaid.title,
                    "chart_type": mermaid.diagram_type,
                }
            
            if not content:
                return None

            return FeedItem(
                item_type=item_type,
                content=content,
                concept_id=concept.get("id"),
                concept_name=concept.get("name"),
                domain=concept.get("domain"),
                due_date=concept.get("sm2_data", {}).get("next_review"),
                priority_score=concept.get("priority_score", 1.0),
            )

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
                    content={
                        "concept_name": concept.get("name", "Concept"),
                        "definition": concept.get("definition", ""),
                        "domain": concept.get("domain", "General"),
                        "complexity_score": concept.get("complexity_score", 5),
                        "tagline": f"Review: {concept.get('name', 'this concept')}",
                        "visual_metaphor": "",
                        "key_points": [concept.get("definition", "No definition available.")],
                        "real_world_example": "",
                        "connections_note": "",
                        "emoji_icon": "📘",
                        "prerequisites": concept.get("prerequisites", []),
                        "related_concepts": concept.get("related_concepts", []),
                    },
                    concept_id=concept.get("id"),
                    concept_name=concept.get("name"),
                    domain=concept.get("domain"),
                    priority_score=concept.get("priority_score", 0.5),
                )
            except Exception:
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
                item_type=FeedItemType.FLASHCARD,
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
                item_type=FeedItemType.FLASHCARD,
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
                item_type=FeedItemType.FLASHCARD,
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
            item = await self.generate_feed_item(concept, FeedItemType.MCQ)
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
        
        # Filter by domains if specified
        if request.domains:
            due_concepts = [
                c for c in due_concepts
                if c.get("domain") in request.domains
            ]
        
        # Determine content type distribution
        allowed_types = request.item_types or list(FeedItemType)
        
        # Generate items for due concepts
        for concept in due_concepts[:request.max_items]:
            # Randomly select a content type
            possible_types = [
                t for t in [
                    FeedItemType.CONCEPT_SHOWCASE,
                    FeedItemType.MCQ,
                    FeedItemType.FILL_BLANK,
                    FeedItemType.MCQ,
                    FeedItemType.FILL_BLANK,
                    FeedItemType.FLASHCARD,
                    FeedItemType.MERMAID_DIAGRAM,
                ]
                if t in allowed_types
            ]
            
            if not possible_types:
                continue
            
            item_type = random.choice(possible_types)
            
            item = await self.generate_feed_item(concept, item_type, user_id=request.user_id)
            if item:
                feed_items.append(item)
            
            # Stop if we have enough items
            if len(feed_items) >= request.max_items:
                break
        
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
                    feed_items.append(FeedItem(
                        item_type=upload_type,
                        content={
                            "file_url": upload.get("file_url"),
                            "thumbnail_url": upload.get("thumbnail_url"),
                            "title": upload.get("title"),
                            "description": upload.get("description"),
                        },
                        concept_id=None,
                        concept_name=upload.get("title"),
                        domain=None,
                        priority_score=0.5,  # Lower priority than due items
                    ))
        
        # Sort by priority
        feed_items.sort(key=lambda x: x.priority_score, reverse=True)
        
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
                     is_correct, response_time_ms, reviewed_at)
                VALUES 
                    (:user_id, :concept_id, :item_type, :interaction_type,
                     :is_correct, :response_time_ms, NOW())
                RETURNING id
                """,
                {
                    "user_id": user_id,
                    "concept_id": concept_id,
                    "item_type": item_type,
                    "interaction_type": interaction_type,
                    "is_correct": is_correct,
                    "response_time_ms": response_time_ms,
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
