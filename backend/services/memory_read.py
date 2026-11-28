"""Query-conditioned fixed-slot memory read (discrete analogue of Memorilla's memory module).

Instead of dumping an unbounded k-hop subgraph or lexical community slice into the LLM prompt,
this module compresses candidate graph memory (`concepts` + `relationships` + community summaries)
into a fixed-size, query-conditioned budget (`DEFAULT_MEMORY_SLOT_BUDGET = 16`) via temperature-scaled
softmax attention and Maximal Marginal Relevance (MMR) deduplication.
"""

from __future__ import annotations

import math
import re
from typing import Any, Optional, Sequence

import numpy as np

DEFAULT_MEMORY_SLOT_BUDGET = 16
DEFAULT_MAX_RELATIONSHIPS = 6

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for", "from", "has", "have",
    "how", "in", "is", "it", "its", "of", "on", "or", "that", "the", "this", "to", "was", "were",
    "what", "when", "where", "which", "who", "why", "will", "with", "about", "explain", "compare",
    "summarize", "find", "no", "definition", "unknown",
})


def _tokens(text: str) -> set[str]:
    return {
        tok
        for tok in _TOKEN_RE.findall((text or "").lower())
        if len(tok) >= 2 and tok not in _STOPWORDS
    }


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    if va.shape != vb.shape or va.size == 0:
        return 0.0
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom <= 1e-12:
        return 0.0
    return float(np.dot(va, vb) / denom)


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _softmax(scores: Sequence[float], temperature: float) -> list[float]:
    if not scores:
        return []
    temp = max(1e-3, float(temperature))
    arr = np.asarray(scores, dtype=np.float64) / temp
    arr -= np.max(arr)
    exp = np.exp(arr)
    total = float(np.sum(exp))
    if total <= 0.0:
        return [1.0 / len(scores)] * len(scores)
    return [float(x / total) for x in exp]


def _concept_text(c: dict[str, Any]) -> str:
    return f"{c.get('name') or ''} {c.get('definition') or ''}".strip()


def _valid_emb(obj: dict[str, Any], dim: int) -> Optional[Sequence[float]]:
    emb = obj.get("embedding")
    if isinstance(emb, (list, tuple, np.ndarray)) and len(emb) == dim and dim > 0:
        return emb
    return None


def _concept_scores(
    query: str,
    concepts: Sequence[dict[str, Any]],
    query_embedding: Optional[Sequence[float]],
) -> tuple[list[float], str]:
    q_toks = _tokens(query)
    q_dim = len(query_embedding) if query_embedding else 0
    has_embs = q_dim > 0 and all(_valid_emb(c, q_dim) is not None for c in concepts)
    method = "embedding_attention_mmr" if has_embs else "lexical_attention_mmr"

    scores: list[float] = []
    for c in concepts:
        hops = int(c.get("hops") or 0)
        hop_prior = 0.08 if hops == 0 else (0.03 if hops == 1 else 0.0)
        conf = float(c.get("confidence", 0.8) or 0.8)
        conf_prior = 0.04 * max(0.0, min(1.0, conf))

        if has_embs and query_embedding is not None:
            sim = _cosine(query_embedding, _valid_emb(c, q_dim))  # [-1, 1]
            name_toks = _tokens(str(c.get("name") or ""))
            name_hit = (len(q_toks & name_toks) / len(q_toks)) if q_toks else 0.0
            rel = 0.80 * sim + 0.20 * name_hit
        else:
            name_toks = _tokens(str(c.get("name") or ""))
            body_toks = _tokens(_concept_text(c))
            if q_toks:
                name_cov = len(q_toks & name_toks) / len(q_toks)
                body_cov = len(q_toks & body_toks) / len(q_toks)
                rel = 0.60 * name_cov + 0.40 * body_cov
            else:
                rel = 0.0

        scores.append(rel + hop_prior + conf_prior)
    return scores, method


def select_graph_memory(
    query: str,
    concepts: Sequence[dict[str, Any]],
    relationships: Sequence[dict[str, Any]],
    *,
    query_embedding: Optional[Sequence[float]] = None,
    max_slots: int = DEFAULT_MEMORY_SLOT_BUDGET,
    max_relationships: int = DEFAULT_MAX_RELATIONSHIPS,
    temperature: float = 0.12,
    lambda_mmr: float = 0.75,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Select up to `max_slots` query-conditioned graph items (concepts + relationships).

    Mirrors Memorilla's fixed-slot memory read in discrete text/graph form: computes a
    softmax attention distribution across all retrieved graph candidates, then greedily packs
    diverse, non-redundant memory slots via MMR.
    """
    budget = max(1, int(max_slots))
    concept_list = list(concepts or [])
    rel_list = list(relationships or [])

    if not concept_list and not rel_list:
        return [], [], {
            "budget": budget,
            "in_concepts": 0,
            "in_relationships": 0,
            "out_concepts": 0,
            "out_relationships": 0,
            "method": "empty",
            "top_attention": 0.0,
        }

    # Reserve relationship slots only if relationships actually exist, leaving >=1 for concepts.
    rel_cap = min(len(rel_list), max(0, min(int(max_relationships), budget - (1 if concept_list else 0))))
    concept_cap = min(len(concept_list), budget - rel_cap)

    raw_scores, method = _concept_scores(query, concept_list, query_embedding)
    attn = _softmax(raw_scores, temperature=temperature)
    q_dim = len(query_embedding) if query_embedding else 0
    tok_cache = [_tokens(_concept_text(c)) for c in concept_list]

    # Normalize scores to [0, 1] before MMR penalty.
    max_s = max(raw_scores) if raw_scores else 0.0
    min_s = min(raw_scores) if raw_scores else 0.0
    span = (max_s - min_s) if (max_s - min_s) > 1e-9 else 1.0
    norm_rel = [(s - min_s) / span for s in raw_scores]

    chosen_idx: list[int] = []
    remaining = list(range(len(concept_list)))
    while remaining and len(chosen_idx) < concept_cap:
        best_i = None
        best_val = -math.inf
        for i in remaining:
            if not chosen_idx:
                mmr_val = norm_rel[i]
            else:
                if method == "embedding_attention_mmr":
                    ei = _valid_emb(concept_list[i], q_dim)
                    max_sim = max(0.0, max(_cosine(ei, _valid_emb(concept_list[j], q_dim)) for j in chosen_idx))
                else:
                    max_sim = max(_jaccard(tok_cache[i], tok_cache[j]) for j in chosen_idx)
                mmr_val = lambda_mmr * norm_rel[i] - (1.0 - lambda_mmr) * max_sim
            if mmr_val > best_val:
                best_val = mmr_val
                best_i = i
        if best_i is None:
            break
        chosen_idx.append(best_i)
        remaining.remove(best_i)

    selected_concepts = [concept_list[i] for i in chosen_idx]
    selected_names = {
        str(c.get("name") or "").strip().lower()
        for c in selected_concepts
        if c.get("name")
    }
    selected_ids = {str(c.get("id")) for c in selected_concepts if c.get("id")}

    # Score relationships by query overlap + endpoint connection to chosen concepts + strength.
    q_toks = _tokens(query)
    scored_rels: list[tuple[float, int, dict[str, Any], set[str]]] = []
    for idx, r in enumerate(rel_list):
        src_name = str(r.get("src_name") or r.get("src") or "")
        tgt_name = str(r.get("tgt_name") or r.get("tgt") or "")
        src_id = str(r.get("src") or "")
        tgt_id = str(r.get("tgt") or "")
        rel_type = str(r.get("type") or "")
        rtoks = _tokens(f"{src_name} {rel_type} {tgt_name}")
        q_hit = (len(q_toks & rtoks) / len(q_toks)) if q_toks else 0.0
        endpoints = (
            (1.0 if (src_name.lower() in selected_names or src_id in selected_ids) else 0.0)
            + (1.0 if (tgt_name.lower() in selected_names or tgt_id in selected_ids) else 0.0)
        ) / 2.0
        strength = max(0.0, min(1.0, float(r.get("strength", 1.0) or 1.0)))
        prereq_bonus = 0.15 if rel_type == "PREREQUISITE_OF" else 0.0
        score = 0.45 * endpoints + 0.35 * q_hit + 0.20 * strength + prereq_bonus
        scored_rels.append((score, idx, r, rtoks))

    remaining_budget = max(0, budget - len(selected_concepts))
    actual_rel_cap = min(rel_cap, remaining_budget)
    selected_rels: list[dict[str, Any]] = []
    chosen_rtoks: list[set[str]] = []
    pool = list(scored_rels)
    while pool and len(selected_rels) < actual_rel_cap:
        best_pos = max(
            range(len(pool)),
            key=lambda p: (
                pool[p][0]
                if not chosen_rtoks
                else lambda_mmr * pool[p][0]
                - (1.0 - lambda_mmr) * max(_jaccard(pool[p][3], ct) for ct in chosen_rtoks)
            ),
        )
        _, _, rel_item, rtoks = pool.pop(best_pos)
        selected_rels.append(rel_item)
        chosen_rtoks.append(rtoks)

    stats = {
        "budget": budget,
        "in_concepts": len(concept_list),
        "in_relationships": len(rel_list),
        "out_concepts": len(selected_concepts),
        "out_relationships": len(selected_rels),
        "method": method,
        "top_attention": round(max(attn), 4) if attn else 0.0,
    }
    return selected_concepts, selected_rels, stats


def rank_communities_by_attention(
    summaries: Sequence[dict[str, Any]],
    query: str,
    *,
    query_embedding: Optional[Sequence[float]] = None,
    max_count: int = 4,
    lambda_mmr: float = 0.75,
) -> list[dict[str, Any]]:
    """Select top `max_count` community summaries using semantic/lexical attention + MMR."""
    items = list(summaries or [])
    if len(items) <= max_count:
        return items

    q_toks = _tokens(query)
    q_dim = len(query_embedding) if query_embedding else 0
    has_embs = q_dim > 0 and all(_valid_emb(s, q_dim) is not None for s in items)
    max_size = max((int(s.get("size") or 1) for s in items), default=1)
    tok_cache = [_tokens(f"{s.get('title', '')} {s.get('summary', '')}") for s in items]

    scores: list[float] = []
    for s, stoks in zip(items, tok_cache):
        lex = (len(q_toks & stoks) / len(q_toks)) if q_toks else 0.0
        size_prior = math.log1p(int(s.get("size") or 0)) / max(1.0, math.log1p(max_size))
        if has_embs and query_embedding is not None:
            cos = _cosine(query_embedding, _valid_emb(s, q_dim))
            scores.append(0.75 * cos + 0.15 * lex + 0.10 * size_prior)
        else:
            scores.append(0.85 * lex + 0.15 * size_prior)

    chosen: list[int] = []
    remaining = list(range(len(items)))
    while remaining and len(chosen) < max_count:
        best_i = max(
            remaining,
            key=lambda i: (
                scores[i]
                if not chosen
                else lambda_mmr * scores[i]
                - (1.0 - lambda_mmr)
                * max(
                    0.0,
                    max(
                        _cosine(_valid_emb(items[i], q_dim), _valid_emb(items[j], q_dim))
                        if has_embs
                        else _jaccard(tok_cache[i], tok_cache[j])
                        for j in chosen
                    ),
                )
            ),
        )
        chosen.append(best_i)
        remaining.remove(best_i)
    return [items[i] for i in chosen]
