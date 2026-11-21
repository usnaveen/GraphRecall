"""Maximal Marginal Relevance (MMR) with pool-centered cosine similarity for feed slates."""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

from backend.feed_ranker.types import CandidateCard, RankerConfig


def pool_centered_cosine_matrix(
    embeddings: list[Optional[Sequence[float]]],
    use_pool_centered: bool = True,
) -> dict[tuple[int, int], float]:
    """Compute symmetric pairwise embedding similarities clipped to [0, 1].

    When `use_pool_centered` is True and at least 3 valid embeddings exist, raw
    cosines are shifted and scaled relative to the candidate pool's median cosine
    similarity (`(cos - m) / (1 - m)`), matching `concept_similarity.py`'s insight
    that dense embedding models compress unrelated pairs into a narrow high band
    such as [0.84, 0.94].
    """
    unit_vecs: dict[int, np.ndarray] = {}
    dim: Optional[int] = None

    for idx, emb in enumerate(embeddings):
        if emb is None or len(emb) == 0:
            continue
        vec = np.asarray(emb, dtype=np.float64)
        if vec.ndim != 1:
            continue
        if dim is None:
            dim = int(vec.shape[0])
        elif vec.shape[0] != dim:
            continue
        norm = float(np.linalg.norm(vec))
        if norm <= 1e-12:
            continue
        unit_vecs[idx] = vec / norm

    valid_indices = sorted(unit_vecs.keys())
    if len(valid_indices) < 2:
        return {}

    raw_pairs: dict[tuple[int, int], float] = {}
    for pos_a, idx_a in enumerate(valid_indices):
        va = unit_vecs[idx_a]
        for idx_b in valid_indices[pos_a + 1 :]:
            cos_val = float(np.dot(va, unit_vecs[idx_b]))
            raw_pairs[(idx_a, idx_b)] = cos_val

    if not raw_pairs:
        return {}

    if use_pool_centered and len(valid_indices) >= 3:
        pool_median = float(np.median(list(raw_pairs.values())))
        denom = max(1.0 - pool_median, 1e-4)
    else:
        pool_median = 0.0
        denom = 1.0

    sims: dict[tuple[int, int], float] = {}
    for (idx_a, idx_b), cos_val in raw_pairs.items():
        if use_pool_centered and len(valid_indices) >= 3:
            scaled = float(np.clip((cos_val - pool_median) / denom, 0.0, 1.0))
        else:
            scaled = float(np.clip(cos_val, 0.0, 1.0))
        sims[(idx_a, idx_b)] = scaled
        sims[(idx_b, idx_a)] = scaled

    return sims


def pairwise_card_similarity(
    i: int,
    j: int,
    cards: list[CandidateCard],
    emb_sim: dict[tuple[int, int], float],
    config: RankerConfig,
) -> float:
    """Compute blended redundancy similarity in [0, 1] between candidates i and j."""
    ci = cards[i]
    cj = cards[j]

    if ci.concept_id is not None and ci.concept_id == cj.concept_id:
        return 1.0

    same_domain = 1.0 if (ci.domain and cj.domain and ci.domain == cj.domain) else 0.0
    same_type = 1.0 if ci.item_type == cj.item_type else 0.0
    e_sim = emb_sim.get((i, j), 0.0)

    blended = (
        config.embedding_weight * e_sim
        + config.same_domain_weight * same_domain
        + config.same_type_weight * same_type
    )
    return min(1.0, max(0.0, blended))


def mmr_select(
    cards: list[CandidateCard],
    relevance_scores: list[float],
    config: RankerConfig,
    limit: int,
    recent_concept_ids: Optional[list[str]] = None,
) -> list[int]:
    """Greedy MMR subset selector with recency weighting and adjacent concept protection."""
    n = len(cards)
    if n == 0 or limit <= 0:
        return []

    target_k = min(limit, n)
    min_rel = min(relevance_scores)
    max_rel = max(relevance_scores)
    span = max_rel - min_rel
    if span <= 1e-12:
        norm_rel = [1.0] * n
    else:
        norm_rel = [(r - min_rel) / span for r in relevance_scores]

    emb_sim = pool_centered_cosine_matrix(
        [c.embedding for c in cards],
        use_pool_centered=config.use_pool_centered_cosine,
    )

    recent_list = list(recent_concept_ids or [])
    remaining = set(range(n))
    selected: list[int] = []

    while remaining and len(selected) < target_k:
        if selected:
            last_cid = cards[selected[-1]].concept_id
        elif recent_list:
            last_cid = recent_list[-1]
        else:
            last_cid = None

        has_alternative_concept = (
            last_cid is not None
            and any(cards[idx].concept_id != last_cid for idx in remaining)
        )

        best_idx: Optional[int] = None
        best_mmr = -float("inf")
        best_raw = -float("inf")

        for idx in sorted(remaining):
            cid = cards[idx].concept_id
            # Strict adjacent same-concept guard when at least one other concept exists
            if has_alternative_concept and cid is not None and cid == last_cid:
                continue

            redundancy = 0.0
            for pos, s_idx in enumerate(selected):
                dist = len(selected) - 1 - pos
                decay = config.recent_history_decay ** dist
                sim = pairwise_card_similarity(idx, s_idx, cards, emb_sim, config)
                redundancy = max(redundancy, decay * sim)

            if cid is not None and recent_list:
                for offset, prev_cid in enumerate(reversed(recent_list)):
                    if prev_cid is not None and cid == prev_cid:
                        hist_dist = len(selected) + offset
                        redundancy = max(
                            redundancy,
                            config.recent_history_decay ** hist_dist,
                        )

            mmr_score = config.mmr_lambda * norm_rel[idx] - (1.0 - config.mmr_lambda) * redundancy
            raw_rel = relevance_scores[idx]

            if (
                mmr_score > best_mmr + 1e-12
                or (abs(mmr_score - best_mmr) <= 1e-12 and raw_rel > best_raw + 1e-12)
            ):
                best_mmr = mmr_score
                best_raw = raw_rel
                best_idx = idx

        # Safety fallback if guard filtered unexpectedly (should never happen due to check)
        if best_idx is None:
            best_idx = max(remaining, key=lambda idx: (relevance_scores[idx], -idx))

        selected.append(best_idx)
        remaining.remove(best_idx)

    return selected
