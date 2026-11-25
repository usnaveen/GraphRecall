"""Second-stage reranking, MMR diversity selection, and lost-in-middle ordering.

Provides:
- `LexicalOverlapReranker`: zero-dependency, <1 ms BM25-like IDF-weighted overlap +
  exact phrase bonus + prior retrieval score blend.
- `CrossEncoderReranker`: lazy-loading wrapper around optional
  `sentence_transformers.CrossEncoder` with strict timeout and fallback.
- `mmr_select_chunks`: Maximal Marginal Relevance selection deduplicating by
  `parent_chunk_id` with cosine or token-Jaccard similarity.
- `order_lost_in_middle`: `[0, 2, 4, ..., 3, 1]` ordering to mitigate middle-context
  attention decay.
"""

from __future__ import annotations

import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_PRIOR_SCORE_KEYS = ("rrf_score", "_rrf_score", "similarity", "_score", "score")

_LEXICAL_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for",
        "from", "has", "have", "how", "in", "is", "it", "its", "of", "on", "or",
        "that", "the", "this", "to", "was", "were", "what", "when", "where",
        "which", "who", "why", "will", "with",
    }
)


@dataclass(frozen=True, slots=True)
class RerankResult:
    """Result returned by a Reranker implementation."""

    chunks: list[dict[str, Any]]
    method: str
    latency_ms: float
    used_fallback: bool


@runtime_checkable
class Reranker(Protocol):
    """Protocol for second-stage chunk rerankers."""

    def rerank(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        top_k: int = 6,
    ) -> RerankResult:
        """Score and return top_k reranked chunks."""
        ...


def _tokenize(text: str, *, drop_stopwords: bool = False) -> list[str]:
    tokens = _TOKEN_RE.findall((text or "").lower())
    if drop_stopwords and tokens:
        filtered = [t for t in tokens if t not in _LEXICAL_STOPWORDS]
        if filtered:
            return filtered
    return tokens


def _chunk_text(chunk: dict[str, Any]) -> str:
    title = str(chunk.get("title") or "").strip()
    body = str(
        chunk.get("window_content")
        or chunk.get("content")
        or chunk.get("parent_content")
        or chunk.get("child_content")
        or ""
    ).strip()
    child = str(chunk.get("child_content") or "").strip()
    parts = [p for p in (title, body) if p]
    if child and child not in body:
        parts.append(child)
    return " ".join(parts)


def _extract_prior_score(chunk: dict[str, Any]) -> float:
    for key in _PRIOR_SCORE_KEYS:
        val = chunk.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return 0.0


def _parent_dedupe_key(chunk: dict[str, Any], fallback_idx: int) -> str:
    key = chunk.get("parent_chunk_id") or chunk.get("id") or chunk.get("note_id")
    if key is not None and str(key).strip():
        return str(key)
    return f"__idx_{fallback_idx}"


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        norm_a += fx * fx
        norm_b += fy * fy
    denom = math.sqrt(norm_a) * math.sqrt(norm_b)
    if denom <= 0.0:
        return 0.0
    return dot / denom


def _jaccard_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    inter = len(tokens_a & tokens_b)
    if inter == 0:
        return 0.0
    union = len(tokens_a | tokens_b)
    return inter / union if union > 0 else 0.0


class LexicalOverlapReranker:
    """Zero-dependency, deterministic (<1 ms) BM25-like lexical reranker."""

    def __init__(
        self,
        *,
        k1: float = 1.2,
        b: float = 0.75,
        lexical_weight: float = 0.65,
        phrase_weight: float = 0.20,
        prior_weight: float = 0.15,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.lexical_weight = lexical_weight
        self.phrase_weight = phrase_weight
        self.prior_weight = prior_weight

    def rerank(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        top_k: int = 6,
    ) -> RerankResult:
        t0 = time.perf_counter()
        if not chunks or top_k <= 0:
            return RerankResult(
                chunks=[],
                method="lexical_overlap",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                used_fallback=False,
            )

        query_tokens = _tokenize(query, drop_stopwords=True)
        unique_q_terms = list(dict.fromkeys(query_tokens))
        norm_phrase = " ".join(_tokenize(query, drop_stopwords=False))

        doc_tokens_list: list[list[str]] = []
        doc_tf_list: list[dict[str, int]] = []
        doc_norm_text_list: list[str] = []
        prior_scores: list[float] = []

        for chunk in chunks:
            full_tokens = _tokenize(_chunk_text(chunk), drop_stopwords=False)
            doc_tokens_list.append(full_tokens)
            doc_norm_text_list.append(" ".join(full_tokens))
            tf: dict[str, int] = {}
            for tok in full_tokens:
                tf[tok] = tf.get(tok, 0) + 1
            doc_tf_list.append(tf)
            prior_scores.append(_extract_prior_score(chunk))

        n_docs = len(chunks)
        avgdl = sum(len(toks) for toks in doc_tokens_list) / max(1, n_docs)
        if avgdl <= 0.0:
            avgdl = 1.0

        max_prior = max(prior_scores) if prior_scores else 0.0
        min_prior = min(prior_scores) if prior_scores else 0.0

        # Compute IDF for each unique query term across candidate chunks.
        idf: dict[str, float] = {}
        for term in unique_q_terms:
            df = sum(1 for tf in doc_tf_list if term in tf)
            idf[term] = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))

        max_bm25_bound = sum(idf[t] * (self.k1 + 1.0) for t in unique_q_terms)

        scored: list[tuple[float, float, int, dict[str, Any]]] = []
        for idx, chunk in enumerate(chunks):
            tf = doc_tf_list[idx]
            dl = max(1, len(doc_tokens_list[idx]))

            bm25_raw = 0.0
            for term in unique_q_terms:
                freq = tf.get(term, 0)
                if freq <= 0:
                    continue
                denom = freq + self.k1 * (1.0 - self.b + self.b * (dl / avgdl))
                bm25_raw += idf[term] * ((freq * (self.k1 + 1.0)) / denom)

            bm25_norm = (bm25_raw / max_bm25_bound) if max_bm25_bound > 0.0 else 0.0

            phrase_bonus = 0.0
            if norm_phrase:
                if len(query_tokens) >= 2 and norm_phrase in doc_norm_text_list[idx]:
                    phrase_bonus = 1.0
                elif len(query_tokens) == 1:
                    title_tokens = set(_tokenize(str(chunk.get("title") or "")))
                    if query_tokens[0] in title_tokens:
                        phrase_bonus = 0.75
                    elif query_tokens[0] in tf:
                        phrase_bonus = 0.35

            prior_raw = prior_scores[idx]
            if max_prior > min_prior:
                prior_norm = (prior_raw - min_prior) / (max_prior - min_prior)
            elif max_prior > 0.0:
                prior_norm = 1.0
            else:
                prior_norm = 0.0

            total_score = (
                self.lexical_weight * bm25_norm
                + self.phrase_weight * phrase_bonus
                + self.prior_weight * prior_norm
            )

            copied = dict(chunk)
            copied["rerank_score"] = round(total_score, 6)
            scored.append((total_score, prior_raw, -idx, copied))

        scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        selected = [item[3] for item in scored[:top_k]]

        return RerankResult(
            chunks=selected,
            method="lexical_overlap",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            used_fallback=False,
        )


class CrossEncoderReranker:
    """Lazy cross-encoder reranker with strict timeout and deterministic fallback."""

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        timeout_ms: float = 120.0,
        fallback: Optional[Reranker] = None,
        *,
        model: Any = None,
    ) -> None:
        self.model_name = model_name
        self.timeout_ms = float(timeout_ms)
        self.fallback: Reranker = fallback if fallback is not None else LexicalOverlapReranker()
        self._model: Any = model

    def _get_or_load_model(self) -> Any:
        if self._model is not None:
            return self._model
        from sentence_transformers import CrossEncoder  # type: ignore[import-not-found]

        self._model = CrossEncoder(self.model_name)
        return self._model

    def rerank(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        top_k: int = 6,
    ) -> RerankResult:
        t0 = time.perf_counter()
        if not chunks or top_k <= 0:
            return RerankResult(
                chunks=[],
                method="cross_encoder",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                used_fallback=False,
            )

        timeout_s = max(0.001, self.timeout_ms / 1000.0)
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            def _run_predict() -> list[float]:
                model = self._get_or_load_model()
                pairs = [(query, _chunk_text(c)) for c in chunks]
                raw_scores = model.predict(pairs)
                return [float(s) for s in raw_scores]

            future = executor.submit(_run_predict)
            scores = future.result(timeout=timeout_s)
            if len(scores) != len(chunks):
                raise ValueError("CrossEncoder returned mismatched score count")

            ranked: list[tuple[float, int, dict[str, Any]]] = []
            for idx, (chunk, score) in enumerate(zip(chunks, scores)):
                copied = dict(chunk)
                copied["rerank_score"] = round(score, 6)
                ranked.append((score, -idx, copied))

            ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
            return RerankResult(
                chunks=[item[2] for item in ranked[:top_k]],
                method="cross_encoder",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                used_fallback=False,
            )
        except (FuturesTimeoutError, Exception):
            fb = self.fallback.rerank(query, chunks, top_k=top_k)
            return RerankResult(
                chunks=fb.chunks,
                method=fb.method,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                used_fallback=True,
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)


def _best_chunk_score(chunk: dict[str, Any]) -> float:
    for key in ("rerank_score", *_PRIOR_SCORE_KEYS):
        val = chunk.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return 0.0


def mmr_select_chunks(
    query_embedding: Optional[Sequence[float]],
    chunks: list[dict[str, Any]],
    k: int = 6,
    lambda_mult: float = 0.72,
) -> list[dict[str, Any]]:
    """Select up to k diverse chunks using Maximal Marginal Relevance (MMR).

    Deduplicates by `parent_chunk_id` (falling back to `id` / `note_id`) first so
    duplicate parent chunks never crowd out diversity. Uses cosine similarity when
    embeddings are present, otherwise falls back to token Jaccard similarity.
    """
    if not chunks or k <= 0:
        return []

    lam = min(1.0, max(0.0, float(lambda_mult)))

    # Parent-level deduplication keeping highest-scored representative per parent.
    deduped_map: dict[str, tuple[int, dict[str, Any]]] = {}
    for idx, chunk in enumerate(chunks):
        pkey = _parent_dedupe_key(chunk, idx)
        existing = deduped_map.get(pkey)
        if existing is None or _best_chunk_score(chunk) > _best_chunk_score(existing[1]):
            deduped_map[pkey] = (idx, dict(chunk))

    candidates = [pair[1] for pair in sorted(deduped_map.values(), key=lambda p: p[0])]
    if len(candidates) <= 1:
        return candidates[:k]

    token_sets = [set(_tokenize(_chunk_text(c), drop_stopwords=True)) for c in candidates]
    raw_scores = [_best_chunk_score(c) for c in candidates]
    has_any_score = any(
        any(c.get(key) is not None for key in ("rerank_score", *_PRIOR_SCORE_KEYS))
        for c in candidates
    )
    max_s = max(raw_scores) if raw_scores else 0.0
    min_s = min(raw_scores) if raw_scores else 0.0

    rel_scores: list[float] = []
    for idx, c in enumerate(candidates):
        c_emb = c.get("embedding")
        if query_embedding is not None and c_emb is not None:
            rel_scores.append(_cosine_similarity(query_embedding, c_emb))
        elif has_any_score:
            if max_s > min_s:
                rel_scores.append((raw_scores[idx] - min_s) / (max_s - min_s))
            elif max_s > 0.0:
                rel_scores.append(1.0)
            else:
                rel_scores.append(0.0)
        else:
            # Preserve caller rank order when neither embeddings nor scores exist.
            rel_scores.append(1.0 / (1.0 + idx))

    def _pair_sim(i: int, j: int) -> float:
        emb_i = candidates[i].get("embedding")
        emb_j = candidates[j].get("embedding")
        if emb_i is not None and emb_j is not None:
            return _cosine_similarity(emb_i, emb_j)
        return _jaccard_similarity(token_sets[i], token_sets[j])

    selected_indices: list[int] = []
    remaining = list(range(len(candidates)))

    first_idx = max(remaining, key=lambda i: (rel_scores[i], -i))
    selected_indices.append(first_idx)
    remaining.remove(first_idx)

    target_k = min(k, len(candidates))
    while remaining and len(selected_indices) < target_k:
        best_idx = max(
            remaining,
            key=lambda i: (
                lam * rel_scores[i]
                - (1.0 - lam) * max(_pair_sim(i, s) for s in selected_indices),
                -i,
            ),
        )
        selected_indices.append(best_idx)
        remaining.remove(best_idx)

    return [candidates[i] for i in selected_indices]


def order_lost_in_middle(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reorder ranked chunks `[0, 1, 2, 3, 4, ...]` to `[0, 2, 4, ..., 3, 1]`."""
    if len(chunks) <= 2:
        return list(chunks)
    front = chunks[0::2]
    back = chunks[1::2]
    return list(front) + list(reversed(back))
