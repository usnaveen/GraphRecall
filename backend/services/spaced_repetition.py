"""Spaced Repetition Service using SM-2 Algorithm.

The SM-2 algorithm calculates optimal review intervals based on:
- Easiness Factor (EF): How easy the item is for this user (1.3 to 2.5)
- Interval: Days until next review
- Repetition: Number of successful reviews in a row

When a user reviews an item, they rate their recall quality (0-5):
- 0-2: Failure - reset to beginning
- 3: Correct but with difficulty
- 4: Correct with hesitation
- 5: Perfect recall
"""

import structlog
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from pydantic import BaseModel

from backend.models.feed_schemas import DifficultyLevel, SM2Data, ReviewResult

logger = structlog.get_logger()


# ============================================================================
# SM-2 Algorithm Implementation
# ============================================================================


class SM2Algorithm:
    """
    Implementation of the SuperMemo 2 (SM-2) algorithm.
    
    This is the foundation of most modern spaced repetition systems.
    """

    # Mapping from our difficulty levels to SM-2 quality ratings (0-5)
    DIFFICULTY_TO_QUALITY = {
        DifficultyLevel.AGAIN: 1,  # Complete failure
        DifficultyLevel.HARD: 3,   # Correct with difficulty
        DifficultyLevel.GOOD: 4,   # Correct with hesitation
        DifficultyLevel.EASY: 5,   # Perfect recall
    }

    @staticmethod
    def calculate_new_interval(
        current_ef: float,
        current_interval: int,
        current_repetition: int,
        quality: int,
    ) -> tuple[float, int, int]:
        """
        Calculate new SM-2 parameters after a review.
        
        Args:
            current_ef: Current easiness factor (1.3-2.5)
            current_interval: Current interval in days
            current_repetition: Current repetition count
            quality: Quality of recall (0-5)
            
        Returns:
            Tuple of (new_ef, new_interval, new_repetition)
        """
        # Calculate new easiness factor
        # EF' = EF + (0.1 - (5-q) * (0.08 + (5-q) * 0.02))
        new_ef = current_ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        
        # Ensure EF doesn't go below 1.3
        new_ef = max(1.3, new_ef)
        
        if quality < 3:
            # Failed recall - reset to beginning
            new_interval = 1
            new_repetition = 0
        else:
            # Successful recall
            new_repetition = current_repetition + 1
            
            if new_repetition == 1:
                new_interval = 1
            elif new_repetition == 2:
                new_interval = 6
            else:
                # I(n) = I(n-1) * EF
                new_interval = int(round(current_interval * new_ef))
        
        # Cap interval at 365 days (1 year)
        new_interval = min(new_interval, 365)
        
        return new_ef, new_interval, new_repetition

    @staticmethod
    def calculate_priority_score(
        sm2_data: SM2Data,
        current_time: Optional[datetime] = None,
    ) -> float:
        """
        Calculate priority score for sorting feed items.
        
        Higher score = more urgent to review.
        
        Factors:
        - Days overdue (most important)
        - Lower easiness factor = harder item
        - Lower repetition count = less established memory
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)
        
        # Calculate days overdue (negative if not yet due)
        days_overdue = (current_time - sm2_data.next_review).days
        
        # Base priority from overdue status
        if days_overdue > 0:
            # Overdue items get exponential priority boost
            overdue_factor = 1.0 + (days_overdue * 0.5)
        elif days_overdue == 0:
            # Due today
            overdue_factor = 1.0
        else:
            # Not yet due - lower priority
            overdue_factor = 0.5 / (abs(days_overdue) + 1)
        
        # Difficulty factor (lower EF = harder = higher priority)
        difficulty_factor = (2.5 - sm2_data.easiness_factor) / 1.2 + 0.5
        
        # Novelty factor (fewer repetitions = less established)
        novelty_factor = 1.0 / (sm2_data.repetition + 1)
        
        # Combined priority
        priority = overdue_factor * (0.6 + 0.3 * difficulty_factor + 0.1 * novelty_factor)
        
        return round(priority, 3)


# ============================================================================
# Spaced Repetition Service
# ============================================================================


class SpacedRepetitionService:
    """Service for managing spaced repetition reviews."""
    
    def __init__(self, pg_client):
        """Initialize with database client."""
        self.pg_client = pg_client
        self.algorithm = SM2Algorithm()
    
    async def get_or_create_sm2_data(
        self,
        user_id: str,
        item_id: str,
        item_type: str,
    ) -> SM2Data:
        """
        Get existing SM2 data or create new entry.
        
        Args:
            user_id: User ID
            item_id: Item ID (concept, flashcard, etc.)
            item_type: Type of item
            
        Returns:
            SM2Data object
        """
        # Try to get existing data
        result = await self.pg_client.execute_query(
            """
            SELECT 
                concept_id as item_id, item_type, user_id,
                easiness_factor, interval_days, repetition_count,
                last_review, next_review, total_reviews, correct_streak
            FROM proficiency_scores
            WHERE user_id = :user_id 
              AND concept_id = :item_id
            """,
            {"user_id": user_id, "item_id": item_id},
        )
        
        if result:
            row = result[0]
            return SM2Data(
                item_id=item_id,
                item_type=item_type,
                user_id=user_id,
                easiness_factor=row.get("easiness_factor", 2.5),
                interval=row.get("interval_days", 1),
                repetition=row.get("repetition_count", 0),
                last_review=row.get("last_review"),
                next_review=row.get("next_review", datetime.now(timezone.utc)),
                total_reviews=row.get("total_reviews", 0),
                correct_streak=row.get("correct_streak", 0),
            )
        
        # Create new SM2 data with defaults
        now = datetime.now(timezone.utc)
        new_data = SM2Data(
            item_id=item_id,
            item_type=item_type,
            user_id=user_id,
            easiness_factor=2.5,
            interval=1,
            repetition=0,
            last_review=None,
            next_review=now,
            total_reviews=0,
            correct_streak=0,
        )
        
        # Insert into database
        await self.pg_client.execute_insert(
            """
            INSERT INTO proficiency_scores 
                (user_id, concept_id, score, easiness_factor, interval_days, 
                 repetition_count, next_review, total_reviews, correct_streak)
            VALUES 
                (:user_id, :item_id, 0.0, :ef, :interval, :rep, :next_review, 0, 0)
            ON CONFLICT (user_id, concept_id) DO NOTHING
            RETURNING id
            """,
            {
                "user_id": user_id,
                "item_id": item_id,
                "ef": 2.5,
                "interval": 1,
                "rep": 0,
                "next_review": now,
            },
        )
        
        return new_data
    
    async def record_review(
        self,
        review: ReviewResult,
    ) -> SM2Data:
        """
        Record a review and update SM2 data.
        
        Args:
            review: The review result
            
        Returns:
            Updated SM2Data
        """
        # Get current SM2 data
        current = await self.get_or_create_sm2_data(
            user_id=review.user_id,
            item_id=review.item_id,
            item_type=review.item_type,
        )
        
        # Convert difficulty to quality rating
        quality = self.algorithm.DIFFICULTY_TO_QUALITY[review.difficulty]
        
        # Calculate new SM2 parameters
        new_ef, new_interval, new_repetition = self.algorithm.calculate_new_interval(
            current_ef=current.easiness_factor,
            current_interval=current.interval,
            current_repetition=current.repetition,
            quality=quality,
        )
        
        # Calculate next review date
        now = datetime.now(timezone.utc)
        next_review = now + timedelta(days=new_interval)
        
        # Update streak
        if quality >= 3:
            new_streak = current.correct_streak + 1
        else:
            new_streak = 0
        
        # Calculate mastery score (0-1 scale)
        # Based on repetition count, EF, and streak
        mastery_score = min(1.0, (
            (new_repetition / 10) * 0.4 +  # Repetition contribution
            ((new_ef - 1.3) / 1.2) * 0.3 +  # EF contribution
            (new_streak / 5) * 0.3  # Streak contribution
        ))
        
        # Update database
        await self.pg_client.execute_update(
            """
            UPDATE proficiency_scores
            SET 
                score = :score,
                easiness_factor = :ef,
                interval_days = :interval,
                repetition_count = :rep,
                last_review = :last_review,
                next_review = :next_review,
                total_reviews = total_reviews + 1,
                correct_streak = :streak,
                updated_at = NOW()
            WHERE user_id = :user_id AND concept_id = :item_id
            """,
            {
                "user_id": review.user_id,
                "item_id": review.item_id,
                "score": mastery_score,
                "ef": new_ef,
                "interval": new_interval,
                "rep": new_repetition,
                "last_review": now,
                "next_review": next_review,
                "streak": new_streak,
            },
        )

        # Log study session for activity tracking (Streak & Heatmap)
        try:
            await self.pg_client.execute_insert(
                """
                INSERT INTO study_sessions
                    (id, user_id, concept_id, reviewed_at, is_correct, item_type, response_time_ms)
                VALUES
                    (:id, :user_id, :concept_id, :reviewed_at, :is_correct, :item_type, :response_time_ms)
                """,
                {
                    "id": str(uuid.uuid4()),
                    "user_id": review.user_id,
                    "concept_id": review.item_id,
                    "reviewed_at": now,
                    "is_correct": quality >= 3,
                    "item_type": review.item_type,
                    "response_time_ms": review.response_time_ms,
                }
            )
        except Exception as e:
            logger.warning("Failed to log study session", error=str(e))
        
        logger.info(
            "SpacedRepetitionService: Review recorded",
            user_id=review.user_id,
            item_id=review.item_id,
            quality=quality,
            new_interval=new_interval,
            next_review=next_review.isoformat(),
        )
        
        return SM2Data(
            item_id=review.item_id,
            item_type=review.item_type,
            user_id=review.user_id,
            easiness_factor=new_ef,
            interval=new_interval,
            repetition=new_repetition,
            last_review=now,
            next_review=next_review,
            total_reviews=current.total_reviews + 1,
            correct_streak=new_streak,
        )
    
    async def get_due_items(
        self,
        user_id: str,
        limit: int = 20,
        include_overdue: bool = True,
    ) -> list[dict]:
        """
        Get items due for review.
        
        Args:
            user_id: User ID
            limit: Maximum number of items
            include_overdue: Include overdue items
            
        Returns:
            List of items with SM2 data
        """
        now = datetime.now(timezone.utc)
        
        # Query for due items
        query = """
            SELECT 
                ps.concept_id as item_id,
                'concept' as item_type,
                ps.easiness_factor,
                ps.interval_days as interval,
                ps.repetition_count as repetition,
                ps.last_review,
                ps.next_review,
                ps.total_reviews,
                ps.correct_streak,
                ps.score as mastery_score,
                c.name as concept_name,
                c.definition,
                c.domain,
                c.complexity_score
            FROM proficiency_scores ps
            JOIN (
                SELECT DISTINCT id, name, definition, domain, complexity_score
                FROM (
                    -- Get concepts from Neo4j through a materialized view or sync table
                    SELECT id, name, definition, domain, complexity_score
                    FROM concepts_cache
                ) concepts
            ) c ON ps.concept_id = c.id
            WHERE ps.user_id = :user_id
              AND ps.next_review <= :now
            ORDER BY ps.next_review ASC
            LIMIT :limit
        """
        
        # Simplified query that works with current schema
        query = """
            SELECT 
                ps.concept_id as item_id,
                'concept' as item_type,
                COALESCE(ps.easiness_factor, 2.5) as easiness_factor,
                COALESCE(ps.interval_days, 1) as interval,
                COALESCE(ps.repetition_count, 0) as repetition,
                ps.last_reviewed as last_review,
                COALESCE(ps.next_review_due, NOW()) as next_review,
                COALESCE(ps.total_reviews, 0) as total_reviews,
                COALESCE(ps.correct_streak, 0) as correct_streak,
                COALESCE(ps.score, 0) as mastery_score
            FROM proficiency_scores ps
            WHERE ps.user_id = :user_id
              AND (ps.next_review_due IS NULL OR ps.next_review_due <= :now)
            ORDER BY ps.next_review_due ASC NULLS FIRST
            LIMIT :limit
        """
        
        try:
            results = await self.pg_client.execute_query(
                query,
                {"user_id": user_id, "now": now, "limit": limit},
            )
            
            # Calculate priority scores
            items = []
            for row in results:
                sm2_data = SM2Data(
                    item_id=row["item_id"],
                    item_type=row["item_type"],
                    user_id=user_id,
                    easiness_factor=row["easiness_factor"],
                    interval=row["interval"],
                    repetition=row["repetition"],
                    last_review=row["last_review"],
                    next_review=row["next_review"],
                    total_reviews=row["total_reviews"],
                    correct_streak=row["correct_streak"],
                )
                
                priority = self.algorithm.calculate_priority_score(sm2_data, now)
                
                items.append({
                    "sm2_data": sm2_data.model_dump(),
                    "priority_score": priority,
                    "mastery_score": row["mastery_score"],
                })
            
            # Sort by priority
            items.sort(key=lambda x: x["priority_score"], reverse=True)
            
            return items[:limit]
            
        except Exception as e:
            logger.error("SpacedRepetitionService: Error getting due items", error=str(e))
            return []
    
    async def get_user_stats(self, user_id: str) -> dict:
        """
        Get spaced repetition statistics for a user.
        
        Args:
            user_id: User ID
            
        Returns:
            Statistics dictionary
        """
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Get counts
        stats_query = """
            SELECT 
                COUNT(*) FILTER (WHERE next_review <= :now) as due_count,
                COUNT(*) FILTER (WHERE next_review < :today_start) as overdue_count,
                COUNT(*) FILTER (WHERE last_reviewed >= :today_start) as reviewed_today,
                AVG(score) as avg_mastery,
                MAX(correct_streak) as max_streak
            FROM proficiency_scores
            WHERE user_id = :user_id
        """
        
        try:
            result = await self.pg_client.execute_query(
                stats_query,
                {"user_id": user_id, "now": now, "today_start": today_start},
            )
            
            if result:
                row = result[0]
                return {
                    "due_today": row.get("due_count", 0) or 0,
                    "overdue": row.get("overdue_count", 0) or 0,
                    "completed_today": row.get("reviewed_today", 0) or 0,
                    "average_mastery": round(row.get("avg_mastery", 0) or 0, 2),
                    "max_streak": row.get("max_streak", 0) or 0,
                }
            
            return {
                "due_today": 0,
                "overdue": 0,
                "completed_today": 0,
                "average_mastery": 0,
                "max_streak": 0,
            }
            
        except Exception as e:
            logger.error("SpacedRepetitionService: Error getting stats", error=str(e))
            return {}
    async def get_upcoming_schedule(self, user_id: str, days: int = 30) -> list[dict]:
        """Get count of items due for each day in the future."""
        try:
            today = datetime.now(timezone.utc).date()
            
            query = """
                SELECT 
                    DATE(next_review) as review_date,
                    COUNT(*) as count
                FROM proficiency_scores
                WHERE user_id = :user_id
                  AND next_review >= :today
                GROUP BY DATE(next_review)
                ORDER BY review_date ASC
                LIMIT :days
            """
            
            params = {
                "user_id": user_id,
                "today": today,
                "days": days
            }
            
            result = await self.pg_client.execute_query(query, params)
            
            schedule = []
            for row in result:
                d = row["review_date"]
                if hasattr(d, 'date'):
                     d = d.date()
                
                # Ensure it's string format YYYY-MM-DD
                date_str = d.isoformat() if hasattr(d, 'isoformat') else str(d)
                if 'T' in date_str:
                    date_str = date_str.split('T')[0]

                schedule.append({
                    "date": date_str,
                    "count": row["count"]
                })
                
            return schedule
        except Exception as e:
            logger.error("SR Service: Error getting schedule", error=str(e))
            return []
