"""Pointwise scoring signals for NeuroFeed (FSRS urgency, lapse backtracking, FIRe leverage)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from backend.feed_ranker.graph_signals import GraphSignalsProtocol
from backend.feed_ranker.types import CandidateCard, RankerConfig
from backend.services.spaced_repetition import FSRSAlgorithm


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def score_fsrs_candidate(
    card: CandidateCard,
    config: RankerConfig,
) -> tuple[float, float, bool]:
    """Compute (retrievability, fsrs_urgency, is_cold_start) for a candidate card."""
    is_cold_start = (
        card.stability is None
        or card.stability <= 0
        or (card.reps_fsrs or 0) == 0
    )

    if card.concept_id is None:
        return 0.85, max(0.0, float(card.fallback_priority)), False

    if is_cold_start:
        eff_s, eff_d = FSRSAlgorithm.cold_start_priors(card.complexity_score)
        elapsed = 0.5 if card.elapsed_days is None else max(0.0, float(card.elapsed_days))
    else:
        eff_s = float(card.stability)
        eff_d = card.difficulty_fsrs
        elapsed = 0.0 if card.elapsed_days is None else max(0.0, float(card.elapsed_days))

    retrievability = FSRSAlgorithm.retrievability(elapsed, eff_s)
    urgency = FSRSAlgorithm.calculate_priority_score(
        stability=None if is_cold_start else eff_s,
        difficulty=eff_d,
        elapsed_days=elapsed,
        reps=0 if is_cold_start else card.reps_fsrs,
        desired_retention=config.desired_retention,
        complexity_score=card.complexity_score,
    )
    return round(retrievability, 6), urgency, is_cold_start


def is_recent_lapse(
    card: CandidateCard,
    retrievability: float,
    config: RankerConfig,
    now: datetime,
) -> bool:
    """Detect whether a concept recently lapsed and warrants prerequisite backtracking."""
    if not card.concept_id:
        return False

    if card.last_review_grade == 1:
        if card.last_reviewed_at is None:
            return True
        age_hours = (_to_utc(now) - _to_utc(card.last_reviewed_at)).total_seconds() / 3600.0
        if age_hours <= config.backtrack_window_hours:
            return True

    if (card.reps_fsrs or 0) > 0 and card.correct_streak == 0 and retrievability < 0.75:
        return True

    return False


async def compute_backtrack_targets(
    user_id: str,
    candidates: list[CandidateCard],
    retrievability_by_item: dict[str, float],
    graph_signals: GraphSignalsProtocol,
    config: RankerConfig,
    now: Optional[datetime] = None,
    prereq_cache: Optional[dict[str, list[tuple[str, int, float]]]] = None,
) -> dict[str, tuple[float, str]]:
    """Map prerequisite concept_id -> (backtrack_boost, lapsed_child_concept_id)."""
    ref_now = _to_utc(now) if now is not None else datetime.now(timezone.utc)
    cache = prereq_cache if prereq_cache is not None else {}

    lapsed_concepts: list[str] = []
    seen_lapsed: set[str] = set()
    for card in candidates:
        cid = card.concept_id
        if not cid or cid in seen_lapsed:
            continue
        r = retrievability_by_item.get(card.item_id, 1.0)
        if is_recent_lapse(card, r, config, ref_now):
            seen_lapsed.add(cid)
            lapsed_concepts.append(cid)

    if not lapsed_concepts:
        return {}

    boosts: dict[str, tuple[float, str]] = {}
    for child_cid in lapsed_concepts:
        weak_id: Optional[str] = None
        try:
            weak_id = await graph_signals.weakest_prerequisite(user_id, child_cid)
        except Exception:
            weak_id = None

        ancestors = cache.get(child_cid)
        if ancestors is None:
            try:
                ancestors = await graph_signals.prerequisites(user_id, child_cid, depth=2)
            except Exception:
                ancestors = []
            cache[child_cid] = ancestors

        if weak_id:
            prev = boosts.get(weak_id)
            if prev is None or 1.0 > prev[0]:
                boosts[weak_id] = (1.0, child_cid)

        for anc_id, depth, strength in ancestors:
            if anc_id == weak_id:
                continue
            hop_decay = 0.65 ** max(0, depth - 1)
            weight = round(min(0.85, max(0.0, float(strength) * hop_decay * 0.75)), 4)
            if weight <= 0.0:
                continue
            prev = boosts.get(anc_id)
            if prev is None or weight > prev[0]:
                boosts[anc_id] = (weight, child_cid)

    return boosts


async def compute_fire_leverage(
    user_id: str,
    candidates: list[CandidateCard],
    urgency_by_concept: dict[str, float],
    graph_signals: GraphSignalsProtocol,
    config: RankerConfig,
    prereq_cache: Optional[dict[str, list[tuple[str, int, float]]]] = None,
) -> dict[str, float]:
    """Optional FIRe encompassing leverage: sum discounted ancestor urgency along prerequisites."""
    if config.w_fire == 0.0:
        return {}

    cache = prereq_cache if prereq_cache is not None else {}
    leverage: dict[str, float] = {}
    unique_concepts = {c.concept_id for c in candidates if c.concept_id}

    for cid in unique_concepts:
        ancestors = cache.get(cid)
        if ancestors is None:
            try:
                ancestors = await graph_signals.prerequisites(user_id, cid, depth=2)
            except Exception:
                ancestors = []
            cache[cid] = ancestors

        total = 0.0
        for anc_id, depth, strength in ancestors:
            anc_urgency = urgency_by_concept.get(anc_id, 0.0)
            if anc_urgency <= 0.0:
                continue
            total += float(strength) * (0.5 ** max(0, depth - 1)) * anc_urgency

        if total > 0.0:
            leverage[cid] = round(min(1.0, total), 4)

    return leverage
