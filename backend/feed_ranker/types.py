"""Data contracts and configuration for the NeuroFeed ranker."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Sequence


@dataclass
class CandidateCard:
    """Normalized candidate item consumed by FeedRanker."""

    item_id: str
    concept_id: Optional[str]
    item_type: str
    domain: Optional[str] = None
    complexity_score: Optional[float] = None
    stability: Optional[float] = None
    difficulty_fsrs: Optional[float] = None
    reps_fsrs: int = 0
    elapsed_days: Optional[float] = None
    last_review_grade: Optional[int] = None
    last_reviewed_at: Optional[datetime] = None
    correct_streak: int = 0
    embedding: Optional[Sequence[float]] = None
    fallback_priority: float = 0.5
    payload: Any = None


@dataclass
class RankedCard:
    """Ranked output item with score breakdown and optional badge."""

    card: CandidateCard
    score: float
    retrievability: float
    reason: str
    badge: Optional[str] = None
    components: dict[str, float] = field(default_factory=dict)


@dataclass
class RankerConfig:
    """Tunable weights and diversity parameters for FeedRanker."""

    desired_retention: float = 0.9
    w_fsrs: float = 1.0
    w_backtrack: float = 0.65
    w_fire: float = 0.20
    w_neighborhood: float = 0.15
    mmr_lambda: float = 0.72
    same_domain_weight: float = 0.25
    same_type_weight: float = 0.15
    embedding_weight: float = 0.60
    use_pool_centered_cosine: bool = True
    revisit_retrievability_threshold: float = 0.75
    backtrack_window_hours: float = 48.0
    invisible_warmup_lead: bool = True
    recent_history_decay: float = 0.65
