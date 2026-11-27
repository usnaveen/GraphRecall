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
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol, Sequence, runtime_checkable

import numpy as np

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


def _chunk_text(chunk: dict[str, Any], *, prefer_child: bool = False) -> str:
    title = str(chunk.get("title") or "").strip()
    if prefer_child:
        body = str(
            chunk.get("child_content")
            or chunk.get("window_content")
            or chunk.get("content")
            or chunk.get("parent_content")
            or ""
        ).strip()
        return " ".join(p for p in (title, body) if p)
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


def _is_cjk_char(cp: int) -> bool:
    return (
        (0x4E00 <= cp <= 0x9FFF)
        or (0x3400 <= cp <= 0x4DBF)
        or (0x20000 <= cp <= 0x2A6DF)
        or (0x2A700 <= cp <= 0x2B73F)
        or (0x2B740 <= cp <= 0x2B81F)
        or (0x2B820 <= cp <= 0x2CEAF)
        or (0xF900 <= cp <= 0xFAFF)
        or (0x2F800 <= cp <= 0x2FA1F)
    )


def _is_bert_punctuation(char: str) -> bool:
    cp = ord(char)
    if (33 <= cp <= 47) or (58 <= cp <= 64) or (91 <= cp <= 96) or (123 <= cp <= 126):
        return True
    return unicodedata.category(char).startswith("P")


class _WordPieceTokenizer:
    """Zero-dependency BERT uncased WordPiece tokenizer matching HuggingFace `BertTokenizer`."""

    def __init__(self, vocab_path: str | Path, *, max_input_chars_per_word: int = 100) -> None:
        vocab: dict[str, int] = {}
        with Path(vocab_path).open("r", encoding="utf-8") as fh:
            for idx, line in enumerate(fh):
                token = line.rstrip("\r\n")
                if token:
                    vocab[token] = idx
        self.vocab = vocab
        self.pad_id = vocab.get("[PAD]", 0)
        self.unk_id = vocab.get("[UNK]", 100)
        self.cls_id = vocab.get("[CLS]", 101)
        self.sep_id = vocab.get("[SEP]", 102)
        self.max_input_chars_per_word = max_input_chars_per_word

    @staticmethod
    def _clean_text(text: str) -> str:
        out: list[str] = []
        for ch in text or "":
            cp = ord(ch)
            if cp == 0 or cp == 0xFFFD:
                continue
            cat = unicodedata.category(ch)
            if ch in ("\t", "\n", "\r") or cat == "Zs" or ch.isspace():
                out.append(" ")
            elif cat in ("Cc", "Cf"):
                continue
            elif _is_cjk_char(cp):
                out.extend((" ", ch, " "))
            else:
                out.append(ch)
        return "".join(out)

    @staticmethod
    def _strip_accents(token: str) -> str:
        return "".join(
            ch for ch in unicodedata.normalize("NFD", token) if unicodedata.category(ch) != "Mn"
        )

    def _basic_tokenize(self, text: str) -> list[str]:
        cleaned = self._clean_text(text)
        out: list[str] = []
        for raw_tok in cleaned.strip().split():
            tok = self._strip_accents(raw_tok.lower())
            cur: list[str] = []
            for ch in tok:
                if _is_bert_punctuation(ch):
                    if cur:
                        out.append("".join(cur))
                        cur = []
                    out.append(ch)
                else:
                    cur.append(ch)
            if cur:
                out.append("".join(cur))
        return out

    def tokenize_ids(self, text: str) -> list[int]:
        ids: list[int] = []
        for word in self._basic_tokenize(text):
            if len(word) > self.max_input_chars_per_word:
                ids.append(self.unk_id)
                continue
            start = 0
            sub_ids: list[int] = []
            is_bad = False
            n = len(word)
            while start < n:
                end = n
                cur_id: Optional[int] = None
                while start < end:
                    substr = word[start:end]
                    if start > 0:
                        substr = "##" + substr
                    tid = self.vocab.get(substr)
                    if tid is not None:
                        cur_id = tid
                        break
                    end -= 1
                if cur_id is None:
                    is_bad = True
                    break
                sub_ids.append(cur_id)
                start = end
            if is_bad:
                ids.append(self.unk_id)
            else:
                ids.extend(sub_ids)
        return ids

    def encode_pair(self, query: str, doc: str, *, max_length: int = 256) -> tuple[list[int], list[int], list[int]]:
        q_ids = self.tokenize_ids(query)
        d_ids = self.tokenize_ids(doc)
        # Preserve query tokens while truncating longer passage from the tail.
        max_q = max(1, max_length - 4)
        if len(q_ids) > max_q:
            q_ids = q_ids[:max_q]
        max_d = max(0, max_length - 3 - len(q_ids))
        if len(d_ids) > max_d:
            d_ids = d_ids[:max_d]
        input_ids = [self.cls_id, *q_ids, self.sep_id, *d_ids, self.sep_id]
        token_type_ids = [0] * (len(q_ids) + 2) + [1] * (len(d_ids) + 1)
        attention_mask = [1] * len(input_ids)
        return input_ids, attention_mask, token_type_ids

    def encode_batch(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        max_length: int = 256,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """LEANN-style dynamic batching: pad only to the longest sequence in this batch."""
        encoded = [self.encode_pair(q, d, max_length=max_length) for q, d in pairs]
        batch_len = max((len(ids) for ids, _, _ in encoded), default=1)
        batch_size = len(encoded)
        input_ids = np.full((batch_size, batch_len), self.pad_id, dtype=np.int64)
        attention_mask = np.zeros((batch_size, batch_len), dtype=np.int64)
        token_type_ids = np.zeros((batch_size, batch_len), dtype=np.int64)
        for row_idx, (ids, mask, types) in enumerate(encoded):
            seq_len = len(ids)
            input_ids[row_idx, :seq_len] = ids
            attention_mask[row_idx, :seq_len] = mask
            token_type_ids[row_idx, :seq_len] = types
        return input_ids, attention_mask, token_type_ids


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


DEFAULT_ONNX_MODEL = Path(__file__).resolve().parents[2] / "eval" / "retrieval" / "artifacts" / "ms-marco-MiniLM-L6-v2.onnx"
DEFAULT_ONNX_VOCAB = Path(__file__).resolve().parents[2] / "eval" / "retrieval" / "artifacts" / "vocab.txt"


class OnnxCrossEncoderReranker:
    """Zero-torch ONNXRuntime cross-encoder with LEANN-style dynamic batching and lexical fallback."""

    def __init__(
        self,
        model_path: str | Path = DEFAULT_ONNX_MODEL,
        vocab_path: str | Path = DEFAULT_ONNX_VOCAB,
        *,
        max_length: int = 256,
        use_child_text: bool = True,
        rrf_blend_weight: float = 0.0,
        fallback: Optional[Reranker] = None,
        session: Any = None,
        tokenizer: Optional[_WordPieceTokenizer] = None,
    ) -> None:
        self.model_path = Path(model_path)
        self.vocab_path = Path(vocab_path)
        self.max_length = int(max_length)
        self.use_child_text = bool(use_child_text)
        self.rrf_blend_weight = min(1.0, max(0.0, float(rrf_blend_weight)))
        self.fallback: Reranker = fallback if fallback is not None else LexicalOverlapReranker()
        self._session: Any = session
        self._tokenizer: Optional[_WordPieceTokenizer] = tokenizer

    def _get_runtime(self) -> tuple[Any, _WordPieceTokenizer]:
        if self._tokenizer is None:
            if not self.vocab_path.exists():
                raise FileNotFoundError(f"Tokenizer vocab not found: {self.vocab_path}")
            self._tokenizer = _WordPieceTokenizer(self.vocab_path)
        if self._session is None:
            if not self.model_path.exists():
                raise FileNotFoundError(f"ONNX model not found: {self.model_path}")
            import onnxruntime as ort

            opts = ort.SessionOptions()
            opts.inter_op_num_threads = 1
            opts.intra_op_num_threads = 4
            self._session = ort.InferenceSession(
                str(self.model_path),
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
        return self._session, self._tokenizer

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
                method="onnx_cross_encoder",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                used_fallback=False,
            )

        try:
            session, tokenizer = self._get_runtime()
            pairs = [(query, _chunk_text(c, prefer_child=self.use_child_text)) for c in chunks]
            input_ids, attention_mask, token_type_ids = tokenizer.encode_batch(
                pairs, max_length=self.max_length
            )
            ort_inputs: dict[str, Any] = {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
            }
            input_names = {inp.name for inp in session.get_inputs()}
            if "token_type_ids" in input_names:
                ort_inputs["token_type_ids"] = token_type_ids
            outputs = session.run(None, ort_inputs)
            logits = np.asarray(outputs[0], dtype=np.float64).reshape(-1)
            if len(logits) != len(chunks):
                raise ValueError("ONNX CrossEncoder returned mismatched score count")

            prior_scores = [_extract_prior_score(c) for c in chunks]
            max_prior = max(prior_scores) if prior_scores else 0.0
            min_prior = min(prior_scores) if prior_scores else 0.0

            ranked: list[tuple[float, int, dict[str, Any]]] = []
            for idx, (chunk, logit) in enumerate(zip(chunks, logits)):
                ce_logit = float(logit)
                ce_prob = _sigmoid(ce_logit)
                if self.rrf_blend_weight > 0.0:
                    if max_prior > min_prior:
                        prior_norm = (prior_scores[idx] - min_prior) / (max_prior - min_prior)
                    elif max_prior > 0.0:
                        prior_norm = 1.0
                    else:
                        prior_norm = 0.0
                    score = (1.0 - self.rrf_blend_weight) * ce_prob + self.rrf_blend_weight * prior_norm
                else:
                    score = ce_logit

                copied = dict(chunk)
                copied["ce_logit"] = round(ce_logit, 6)
                copied["ce_prob"] = round(ce_prob, 6)
                copied["rerank_score"] = round(score, 6)
                ranked.append((score, -idx, copied))

            ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
            return RerankResult(
                chunks=[item[2] for item in ranked[:top_k]],
                method="onnx_cross_encoder",
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                used_fallback=False,
            )
        except Exception:
            fb = self.fallback.rerank(query, chunks, top_k=top_k)
            return RerankResult(
                chunks=fb.chunks,
                method=fb.method,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                used_fallback=True,
            )


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
    *,
    max_per_parent: Optional[int] = 1,
    prefer_rerank_score: bool = False,
) -> list[dict[str, Any]]:
    """Select up to k diverse chunks using Maximal Marginal Relevance (MMR).

    Deduplicates up to `max_per_parent` child chunks per `parent_chunk_id` (default 1;
    pass `None` or `<= 0` for unlimited) keeping highest-scored representatives.
    Uses cosine similarity when embeddings are present, otherwise token Jaccard similarity.
    """
    if not chunks or k <= 0:
        return []

    lam = min(1.0, max(0.0, float(lambda_mult)))

    # Parent-level cap preserving highest-scored representatives per parent.
    cap = None if (max_per_parent is None or max_per_parent <= 0) else int(max_per_parent)
    if cap == 1:
        deduped_map: dict[str, tuple[int, dict[str, Any]]] = {}
        for idx, chunk in enumerate(chunks):
            pkey = _parent_dedupe_key(chunk, idx)
            existing = deduped_map.get(pkey)
            if existing is None or _best_chunk_score(chunk) > _best_chunk_score(existing[1]):
                deduped_map[pkey] = (idx, dict(chunk))
        candidates = [pair[1] for pair in sorted(deduped_map.values(), key=lambda p: p[0])]
    elif cap is not None:
        by_parent: dict[str, list[tuple[int, float, dict[str, Any]]]] = {}
        for idx, chunk in enumerate(chunks):
            pkey = _parent_dedupe_key(chunk, idx)
            by_parent.setdefault(pkey, []).append((idx, _best_chunk_score(chunk), dict(chunk)))
        kept_entries: list[tuple[int, dict[str, Any]]] = []
        for entries in by_parent.values():
            entries.sort(key=lambda e: (-e[1], e[0]))
            for idx, _, item in entries[:cap]:
                kept_entries.append((idx, item))
        kept_entries.sort(key=lambda pair: pair[0])
        candidates = [item for _, item in kept_entries]
    else:
        candidates = [dict(c) for c in chunks]

    if len(candidates) <= 1:
        return candidates[:k]

    token_sets = [set(_tokenize(_chunk_text(c), drop_stopwords=True)) for c in candidates]
    raw_scores = [_best_chunk_score(c) for c in candidates]
    has_any_score = any(
        any(c.get(key) is not None for key in ("rerank_score", *_PRIOR_SCORE_KEYS))
        for c in candidates
    )
    has_rerank_score = prefer_rerank_score and any(c.get("rerank_score") is not None for c in candidates)
    max_s = max(raw_scores) if raw_scores else 0.0
    min_s = min(raw_scores) if raw_scores else 0.0

    rel_scores: list[float] = []
    for idx, c in enumerate(candidates):
        c_emb = c.get("embedding")
        if has_rerank_score:
            if max_s > min_s:
                rel_scores.append((raw_scores[idx] - min_s) / (max_s - min_s))
            elif max_s > 0.0:
                rel_scores.append(1.0)
            else:
                rel_scores.append(0.5)
        elif query_embedding is not None and c_emb is not None:
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
