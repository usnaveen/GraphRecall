"""Spaced Repetition Service — SM-2 and FSRS Algorithms.

Supports two scheduling algorithms:
  SM-2 (SuperMemo 2): Classic algorithm using Easiness Factor.
  FSRS (Free Spaced Repetition Scheduler): Modern algorithm using
        Stability, Difficulty, and Retrievability.

Users pick their preferred algorithm in Settings. The service
routes to the correct implementation at review time.
"""

import math
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
# FSRS Algorithm Implementation
# ============================================================================


class FSRSAlgorithm:
    """
    Free Spaced Repetition Scheduler (FSRS) v4.5 implementation.

    Uses three core parameters:
      Stability (S)  — expected half-life of a memory in days
      Difficulty (D) — intrinsic difficulty of the item (1–10)
      Retrievability (R) — probability of recall at elapsed time t

    Grade mapping (same DifficultyLevel enum as SM-2):
      AGAIN → 1   HARD → 2   GOOD → 3   EASY → 4
    """

    DIFFICULTY_TO_GRADE = {
        DifficultyLevel.AGAIN: 1,
        DifficultyLevel.HARD: 2,
        DifficultyLevel.GOOD: 3,
        DifficultyLevel.EASY: 4,
    }

    # Default FSRS-4.5 weight vector (17 parameters)
    W = [
        0.4, 0.6, 2.4, 5.8,   # w0-w3: initial stability per grade (1-4)
        4.93,                   # w4: initial difficulty offset
        0.94,                   # w5: initial difficulty grade factor
        0.86,                   # w6: difficulty update factor
        0.01,                   # w7: mean-reversion weight
        1.49,                   # w8: stability increase factor
        0.14,                   # w9: stability exponent (difficulty)
        0.94,                   # w10: stability exponent (retrievability)
        2.18,                   # w11: fail stability factor
        0.05,                   # w12: fail difficulty exponent
        0.34,                   # w13: fail stability exponent
        1.26,                   # w14: fail retrievability exponent
        0.29,                   # w15: hard penalty
        2.61,                   # w16: easy bonus
    ]

    @staticmethod
    def retrievability(elapsed_days: float, stability: float) -> float:
        """Probability of recall: R(t) = (1 + t / (9·S))^(−1)."""
        if stability <= 0:
            return 0.0
        return (1.0 + elapsed_days / (9.0 * stability)) ** (-1)

    @classmethod
    def initial_stability(cls, grade: int) -> float:
        """Initial S after the very first review (grade 1–4)."""
        return max(0.1, cls.W[grade - 1])

    @classmethod
    def initial_difficulty(cls, grade: int) -> float:
        """Initial D after the very first review."""
        d = cls.W[4] - (grade - 3) * cls.W[5]
        return max(1.0, min(10.0, d))

    @classmethod
    def next_difficulty(cls, d: float, grade: int) -> float:
        """Update difficulty after a subsequent review."""
        new_d = d - cls.W[6] * (grade - 3)
        # Mean-revert toward D(4) to avoid runaway values
        d4 = cls.initial_difficulty(4)
        new_d = cls.W[7] * d4 + (1.0 - cls.W[7]) * new_d
        return max(1.0, min(10.0, new_d))

    @classmethod
    def next_stability(cls, s: float, d: float, r: float, grade: int) -> float:
        """Calculate new stability after a review."""
        if grade == 1:
            # Failure path — stability drops
            new_s = (
                cls.W[11]
                * d ** (-cls.W[12])
                * ((s + 1) ** cls.W[13] - 1)
                * math.exp(cls.W[14] * (1.0 - r))
            )
        else:
            # Success path (hard / good / easy)
            hard_penalty = cls.W[15] if grade == 2 else 1.0
            easy_bonus = cls.W[16] if grade == 4 else 1.0
            new_s = s * (
                1.0
                + math.exp(cls.W[8])
                * (11.0 - d)
                * s ** (-cls.W[9])
                * (math.exp((1.0 - r) * cls.W[10]) - 1.0)
                * hard_penalty
                * easy_bonus
            )
        return max(0.1, new_s)

    @staticmethod
    def next_interval(stability: float, desired_retention: float = 0.9) -> int:
        """Optimal interval (days) to reach desired_retention."""
        interval = 9.0 * stability * (1.0 / desired_retention - 1.0)
        return max(1, min(365, round(interval)))


# ============================================================================
# Spaced Repetition Service
# ============================================================================


class SpacedRepetitionService:
    """Service for managing spaced repetition reviews."""

    def __init__(self, pg_client, algorithm: str = "sm2"):
        """Initialize with database client and algorithm choice."""
        self.pg_client = pg_client
        self.algorithm_name = algorithm
        self.sm2 = SM2Algorithm()
        self.fsrs = FSRSAlgorithm()
    
    async def get_or_create_sm2_data(
        self,
        user_id: str,
        item_id: str,
        item_type: str,
    ) -> SM2Data:
        """
        Get existing SM2 data or create new entry.
        Also reads FSRS columns (stability, difficulty_fsrs, reps_fsrs).

        Args:
            user_id: User ID
            item_id: Item ID (concept, flashcard, etc.)
            item_type: Type of item

        Returns:
            SM2Data object (with extra FSRS attrs stored in _fsrs_* attributes)
        """
        # Try to get existing data
        result = await self.pg_client.execute_query(
            """
            SELECT
                concept_id as item_id, user_id,
                easiness_factor, interval_days, repetition_count,
                last_reviewed as last_review,
                next_review_due as next_review,
                total_reviews, correct_streak,
                stability, difficulty_fsrs, reps_fsrs
            FROM proficiency_scores
            WHERE user_id = :user_id
              AND concept_id = :item_id
            """,
            {"user_id": user_id, "item_id": item_id},
        )

        if result:
            row = result[0]
            sm2_data = SM2Data(
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
            # Attach FSRS fields as extra attributes
            sm2_data._fsrs_stability = row.get("stability")
            sm2_data._fsrs_difficulty = row.get("difficulty_fsrs")
            sm2_data._fsrs_reps = row.get("reps_fsrs", 0)
            return sm2_data

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
        new_data._fsrs_stability = None
        new_data._fsrs_difficulty = None
        new_data._fsrs_reps = 0

        # Insert into database
        await self.pg_client.execute_insert(
            """
            INSERT INTO proficiency_scores
                (user_id, concept_id, score, easiness_factor, interval_days,
                 repetition_count, next_review_due, total_reviews, correct_streak)
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
        Record a review and update spaced repetition data.
        Routes to SM-2 or FSRS based on self.algorithm_name.

        Args:
            review: The review result

        Returns:
            Updated SM2Data
        """
        # Get current data (includes FSRS columns)
        current = await self.get_or_create_sm2_data(
            user_id=review.user_id,
            item_id=review.item_id,
            item_type=review.item_type,
        )

        now = datetime.now(timezone.utc)

        if self.algorithm_name == "fsrs":
            # ── FSRS path ──
            grade = self.fsrs.DIFFICULTY_TO_GRADE[review.difficulty]

            old_stability = getattr(current, "_fsrs_stability", None)
            old_difficulty = getattr(current, "_fsrs_difficulty", None)
            fsrs_reps = getattr(current, "_fsrs_reps", 0) or 0

            if old_stability is None or fsrs_reps == 0:
                # First review under FSRS
                new_stability = self.fsrs.initial_stability(grade)
                new_difficulty = self.fsrs.initial_difficulty(grade)
            else:
                # Compute elapsed days since last review
                if current.last_review:
                    elapsed = max(0.0, (now - current.last_review).total_seconds() / 86400.0)
                else:
                    elapsed = 0.0
                r = self.fsrs.retrievability(elapsed, old_stability)
                new_stability = self.fsrs.next_stability(old_stability, old_difficulty, r, grade)
                new_difficulty = self.fsrs.next_difficulty(old_difficulty, grade)

            new_interval = self.fsrs.next_interval(new_stability)
            next_review = now + timedelta(days=new_interval)
            new_repetition = fsrs_reps + 1

            # Streak
            is_correct = grade >= 2  # HARD and above count as correct in FSRS
            new_streak = (current.correct_streak + 1) if is_correct else 0

            # Mastery score (0-1)
            mastery_score = min(1.0, (
                (new_repetition / 10) * 0.3 +
                ((10.0 - new_difficulty) / 9.0) * 0.3 +
                (new_streak / 5) * 0.2 +
                min(1.0, new_stability / 30.0) * 0.2
            ))

            # Update database (both shared + FSRS columns)
            await self.pg_client.execute_update(
                """
                UPDATE proficiency_scores
                SET
                    score = :score,
                    interval_days = :interval,
                    last_reviewed = :last_review,
                    next_review_due = :next_review,
                    total_reviews = total_reviews + 1,
                    correct_streak = :streak,
                    stability = :stability,
                    difficulty_fsrs = :difficulty_fsrs,
                    reps_fsrs = :reps_fsrs,
                    updated_at = NOW()
                WHERE user_id = :user_id AND concept_id = :item_id
                """,
                {
                    "user_id": review.user_id,
                    "item_id": review.item_id,
                    "score": mastery_score,
                    "interval": new_interval,
                    "last_review": now,
                    "next_review": next_review,
                    "streak": new_streak,
                    "stability": new_stability,
                    "difficulty_fsrs": new_difficulty,
                    "reps_fsrs": new_repetition,
                },
            )

            new_ef = current.easiness_factor  # unchanged under FSRS

        else:
            # ── SM-2 path (default) ──
            quality = self.sm2.DIFFICULTY_TO_QUALITY[review.difficulty]

            new_ef, new_interval, new_repetition = self.sm2.calculate_new_interval(
                current_ef=current.easiness_factor,
                current_interval=current.interval,
                current_repetition=current.repetition,
                quality=quality,
            )

            next_review = now + timedelta(days=new_interval)

            is_correct = quality >= 3
            new_streak = (current.correct_streak + 1) if is_correct else 0

            mastery_score = min(1.0, (
                (new_repetition / 10) * 0.4 +
                ((new_ef - 1.3) / 1.2) * 0.3 +
                (new_streak / 5) * 0.3
            ))

            await self.pg_client.execute_update(
                """
                UPDATE proficiency_scores
                SET
                    score = :score,
                    easiness_factor = :ef,
                    interval_days = :interval,
                    repetition_count = :rep,
                    last_reviewed = :last_review,
                    next_review_due = :next_review,
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

        # ── Common: Log study session for activity tracking ──
        try:
            await self.pg_client.execute_insert(
                """
                INSERT INTO study_sessions
                    (id, user_id, concept_id, reviewed_at, is_correct, item_type, response_time_ms, session_type)
                VALUES
                    (:id, :user_id, :concept_id, :reviewed_at, :is_correct, :item_type, :response_time_ms, :session_type)
                """,
                {
                    "id": str(uuid.uuid4()),
                    "user_id": review.user_id,
                    "concept_id": review.item_id,
                    "reviewed_at": now,
                    "is_correct": is_correct,
                    "item_type": review.item_type,
                    "response_time_ms": review.response_time_ms,
                    "session_type": "flashcard" if review.item_type == "flashcard" else "quiz",
                }
            )
        except Exception as e:
            logger.warning("Failed to log study session", error=str(e))

        logger.info(
            "SpacedRepetitionService: Review recorded",
            user_id=review.user_id,
            item_id=review.item_id,
            algorithm=self.algorithm_name,
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
                
                priority = self.sm2.calculate_priority_score(sm2_data, now)
                
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
                COUNT(*) FILTER (WHERE next_review_due <= :now) as due_count,
                COUNT(*) FILTER (WHERE next_review_due < :today_start) as overdue_count,
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
                    DATE(next_review_due) as review_date,
                    COUNT(*) as count
                FROM proficiency_scores
                WHERE user_id = :user_id
                  AND next_review_due >= :today
                GROUP BY DATE(next_review_due)
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

    async def get_upcoming_schedule_with_topics(
        self, user_id: str, neo4j_client, days: int = 30
    ) -> list[dict]:
        """Get items due per day with topic names (up to 10 per day)."""
        try:
            today = datetime.now(timezone.utc).date()

            query = """
                SELECT
                    DATE(next_review_due) as review_date,
                    COUNT(*) as count,
                    array_agg(concept_id) as concept_ids
                FROM proficiency_scores
                WHERE user_id = :user_id
                  AND next_review_due >= :today
                GROUP BY DATE(next_review_due)
                ORDER BY review_date ASC
                LIMIT :days
            """
            result = await self.pg_client.execute_query(
                query, {"user_id": user_id, "today": today, "days": days}
            )

            # Collect all unique concept IDs
            all_concept_ids = set()
            for row in result:
                for cid in (row.get("concept_ids") or []):
                    if cid:
                        all_concept_ids.add(cid)

            # Resolve names from Neo4j in bulk
            concept_name_map: dict[str, str] = {}
            if all_concept_ids and neo4j_client:
                try:
                    neo_result = await neo4j_client.execute_query(
                        "MATCH (c:Concept) WHERE c.id IN $ids RETURN c.id as id, c.name as name",
                        {"ids": list(all_concept_ids)},
                    )
                    for row in neo_result:
                        concept_name_map[row["id"]] = row["name"]
                except Exception as e:
                    logger.warning("Failed to resolve concept names", error=str(e))

            schedule = []
            for row in result:
                d = row["review_date"]
                if hasattr(d, "date"):
                    d = d.date()
                date_str = d.isoformat() if hasattr(d, "isoformat") else str(d)
                if "T" in date_str:
                    date_str = date_str.split("T")[0]

                # Get topic names (limit 10 per day)
                concept_ids = row.get("concept_ids") or []
                topics = []
                seen = set()
                for cid in concept_ids:
                    if cid and cid in concept_name_map and cid not in seen:
                        topics.append(concept_name_map[cid])
                        seen.add(cid)
                    if len(topics) >= 10:
                        break

                schedule.append({
                    "date": date_str,
                    "count": row["count"],
                    "topics": topics,
                })

            return schedule
        except Exception as e:
            logger.error("SR Service: Error getting schedule with topics", error=str(e))
            return []
