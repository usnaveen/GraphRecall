"""Main FeedRanker orchestrator: FSRS urgency + prerequisite backtracking + MMR diversity."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from backend.feed_ranker.graph_signals import GraphSignalsProtocol, NullGraphSignals
from backend.feed_ranker.mmr import mmr_select
from backend.feed_ranker.scoring import (
    compute_backtrack_targets,
    compute_fire_leverage,
    score_fsrs_candidate,
)
from backend.feed_ranker.types import CandidateCard, RankedCard, RankerConfig


class FeedRanker:
    """Ranks candidate feed cards using FSRS retrievability, graph signals, and MMR."""

    def __init__(
        self,
        graph_signals: Optional[GraphSignalsProtocol] = None,
        config: Optional[RankerConfig] = None,
    ) -> None:
        self.graph_signals: GraphSignalsProtocol = graph_signals or NullGraphSignals()
        self.config: RankerConfig = config or RankerConfig()

    async def missing_backtrack_prerequisites(
        self,
        user_id: str,
        candidates: list[CandidateCard],
        now: Optional[datetime] = None,
    ) -> list[str]:
        """Return missing prerequisite concept IDs needed for post-lapse remediation."""
        if not candidates:
            return []

        ref_now = now or datetime.now(timezone.utc)
        retrievability_by_item: dict[str, float] = {}
        present_concepts: set[str] = set()

        for card in candidates:
            r, _, _ = score_fsrs_candidate(card, self.config)
            retrievability_by_item[card.item_id] = r
            if card.concept_id:
                present_concepts.add(card.concept_id)

        backtrack_map = await compute_backtrack_targets(
            user_id=user_id,
            candidates=candidates,
            retrievability_by_item=retrievability_by_item,
            graph_signals=self.graph_signals,
            config=self.config,
            now=ref_now,
        )
        missing = [
            (pid, boost)
            for pid, (boost, _) in backtrack_map.items()
            if pid not in present_concepts
        ]
        missing.sort(key=lambda item: (-item[1], item[0]))
        return [pid for pid, _ in missing]

    async def rank(
        self,
        user_id: str,
        candidates: list[CandidateCard],
        limit: int = 20,
        recent_concept_ids: Optional[list[str]] = None,
        now: Optional[datetime] = None,
    ) -> list[RankedCard]:
        """Rank candidates into a diversified reels-compatible sequence."""
        if not candidates or limit <= 0:
            return []

        ref_now = now or datetime.now(timezone.utc)
        n = len(candidates)

        retrievabilities: list[float] = [0.0] * n
        fsrs_urgencies: list[float] = [0.0] * n
        cold_flags: list[bool] = [False] * n
        retrievability_by_item: dict[str, float] = {}
        urgency_by_concept: dict[str, float] = {}

        for idx, card in enumerate(candidates):
            r, u, is_cold = score_fsrs_candidate(card, self.config)
            retrievabilities[idx] = r
            fsrs_urgencies[idx] = u
            cold_flags[idx] = is_cold
            retrievability_by_item[card.item_id] = r
            if card.concept_id is not None:
                prev_u = urgency_by_concept.get(card.concept_id, 0.0)
                if u > prev_u:
                    urgency_by_concept[card.concept_id] = u

        prereq_cache: dict[str, list[tuple[str, int, float]]] = {}
        backtrack_map = await compute_backtrack_targets(
            user_id=user_id,
            candidates=candidates,
            retrievability_by_item=retrievability_by_item,
            graph_signals=self.graph_signals,
            config=self.config,
            now=ref_now,
            prereq_cache=prereq_cache,
        )
        fire_map = await compute_fire_leverage(
            user_id=user_id,
            candidates=candidates,
            urgency_by_concept=urgency_by_concept,
            graph_signals=self.graph_signals,
            config=self.config,
            prereq_cache=prereq_cache,
        )

        # Fetch PPR / neighborhood relevance seeded from most urgent concepts
        neighborhood_map: dict[str, float] = {}
        if self.config.w_neighborhood > 0.0:
            ranked_seeds = [
                cid
                for cid, _ in sorted(
                    urgency_by_concept.items(),
                    key=lambda kv: (-kv[1], kv[0]),
                )[:5]
            ]
            if ranked_seeds:
                try:
                    neighborhood_map = (
                        await self.graph_signals.concept_neighborhood(
                            user_id,
                            ranked_seeds,
                            k=20,
                        )
                        or {}
                    )
                except Exception:
                    neighborhood_map = {}

        total_scores: list[float] = []
        component_rows: list[dict[str, float]] = []

        for idx, card in enumerate(candidates):
            cid = card.concept_id
            if cid is None:
                # Non-concept user uploads retain fallback score without graph distortion
                score = round(float(card.fallback_priority), 4)
                total_scores.append(score)
                component_rows.append({"fallback_priority": score})
                continue

            fsrs_term = self.config.w_fsrs * fsrs_urgencies[idx]
            bt_raw = backtrack_map[cid][0] if cid in backtrack_map else 0.0
            bt_term = self.config.w_backtrack * bt_raw
            fire_raw = fire_map.get(cid, 0.0)
            fire_term = self.config.w_fire * fire_raw
            nbr_raw = float(neighborhood_map.get(cid, 0.0))
            nbr_term = self.config.w_neighborhood * nbr_raw

            total = round(fsrs_term + bt_term + fire_term + nbr_term, 4)
            total_scores.append(total)
            component_rows.append(
                {
                    "fsrs": round(fsrs_term, 4),
                    "backtrack": round(bt_term, 4),
                    "fire": round(fire_term, 4),
                    "neighborhood": round(nbr_term, 4),
                }
            )

        selected_indices = mmr_select(
            cards=candidates,
            relevance_scores=total_scores,
            config=self.config,
            limit=limit,
            recent_concept_ids=recent_concept_ids,
        )

        ranked_cards: list[RankedCard] = []
        for idx in selected_indices:
            card = candidates[idx]
            r = retrievabilities[idx]
            is_cold = cold_flags[idx]
            comps = component_rows[idx]

            if comps.get("backtrack", 0.0) > 0.0:
                reason = "prereq_backtrack"
            elif card.concept_id is not None and is_cold:
                reason = "cold_start"
            elif comps.get("neighborhood", 0.0) > 0.05 and fsrs_urgencies[idx] < 0.25:
                reason = "neighborhood_bridge"
            else:
                reason = "fsrs_due"

            needs_revisit = (
                card.concept_id is not None
                and (
                    (not is_cold and r < self.config.revisit_retrievability_threshold)
                    or card.last_review_grade == 1
                    or reason == "prereq_backtrack"
                )
            )
            badge = "Revisit" if needs_revisit else None

            ranked_cards.append(
                RankedCard(
                    card=card,
                    score=total_scores[idx],
                    retrievability=r,
                    reason=reason,
                    badge=badge,
                    components=comps,
                )
            )

        ranked_cards = self._apply_invisible_warmup(
            ranked_cards,
            recent_concept_ids=recent_concept_ids,
        )
        return ranked_cards

    def _apply_invisible_warmup(
        self,
        ranked: list[RankedCard],
        recent_concept_ids: Optional[list[str]] = None,
    ) -> list[RankedCard]:
        """Swap a comfortable ZPD card into slot 0 if slot 0 is a hard lapse (invisible pacing)."""
        if not self.config.invisible_warmup_lead or len(ranked) < 3:
            return ranked

        first = ranked[0]
        if first.reason == "prereq_backtrack":
            return ranked

        is_hard_opener = (
            first.card.last_review_grade == 1 or first.retrievability < 0.45
        )
        if not is_hard_opener:
            return ranked

        recent_last = recent_concept_ids[-1] if recent_concept_ids else None
        first_cid = first.card.concept_id
        best_swap: Optional[int] = None
        best_key: tuple[int, float] = (-1, -1.0)

        for pos in range(1, len(ranked)):
            cand = ranked[pos]
            if cand.card.concept_id is None or cand.reason == "prereq_backtrack":
                continue
            if not (0.72 <= cand.retrievability <= 0.92):
                continue
            # Preserve adjacent-concept uniqueness at slot 0 -> 1 and around removal point
            if first_cid is not None and cand.card.concept_id == first_cid:
                continue
            if 0 < pos < len(ranked) - 1:
                left_cid = ranked[pos - 1].card.concept_id
                right_cid = ranked[pos + 1].card.concept_id
                if left_cid is not None and left_cid == right_cid:
                    continue
            avoids_recent = 1 if (recent_last is None or cand.card.concept_id != recent_last) else 0
            cand_key = (avoids_recent, cand.score)
            if cand_key > best_key:
                best_key = cand_key
                best_swap = pos

        if best_swap is None:
            return ranked

        reordered = list(ranked)
        warmup_card = reordered.pop(best_swap)
        reordered.insert(0, warmup_card)
        return reordered
