"""Grounding Guard: retrieval confidence gating, citation auditing, and async LLM circuit breaking."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Literal, Optional, Sequence, TypeVar

T = TypeVar("T")

_GENERAL_BYPASS_INTENTS: frozenset[str] = frozenset({"general", "greeting", "greetings", "chitchat"})
_NON_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({400, 401, 403, 404, 422})
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_RETRYABLE_MSG_MARKERS: tuple[str, ...] = (
    "429",
    "rate limit",
    "rate_limit",
    "ratelimit",
    "too many requests",
    "timeout",
    "timed out",
    "503",
    "502",
    "504",
    "500",
    "service unavailable",
)

# Bracketed citation groups like [1], [G1], [1, 2], [1, G2]: not followed by '(' (a markdown link) and
# not glued to an identifier or another bracket (array indexing: nums[0], dp[i][9], f(x)[2]).
# Group 1 is the single space before it, removed together with an invalid citation.
_BRACKET_CITATION_RE = re.compile(
    r"([ \t]?)(?<![\w\)])\[(\s*(?:G?\d+)(?:\s*,\s*G?\d+)*\s*)\](?!\()",
    re.IGNORECASE,
)
_BRACKET_GROUP_RE = re.compile(r"\[[^\[\]]*\]$")


def _is_indexing_chain(text: str, start: int) -> bool:
    """True when the bracket at ``start`` continues a chain glued to an identifier (``dp[10][9]``)
    rather than a run of citations after a space (``see [1][2]``)."""
    i = start
    while i > 0 and text[i - 1] == "]":
        m = _BRACKET_GROUP_RE.search(text[:i])
        if not m:
            return False
        i = m.start()
    return i > 0 and (text[i - 1].isalnum() or text[i - 1] in "_)")


# Code is never rewritten: fenced blocks and inline code spans.
_CODE_SEGMENT_RE = re.compile(r"(```[\s\S]*?(?:```|$)|`[^`\n]+`)")


@dataclass(slots=True)
class GroundingDecision:
    """Outcome of retrieval-confidence gating before final LLM answer generation."""

    should_abstain: bool
    confidence_tier: Literal["high", "medium", "low"]
    reason: str
    max_score: float
    valid_chunk_indices: set[int]
    valid_graph_ids: set[str]
    abstention_message: str = ""
    best_similarity: Optional[float] = None
    term_coverage: Optional[float] = None
    concept_coverage: Optional[float] = None


@dataclass(slots=True)
class CitationAudit:
    """Result of verifying bracketed [1] / [G1] citations against retrieved context."""

    valid_refs: list[str]
    invalid_refs: list[str]
    grounded_ratio: float
    cleaned_text: str


class CircuitBreakerOpenError(Exception):
    """Raised when an AsyncCircuitBreaker is OPEN and rejects calls."""

    def __init__(self, message: str = "LLM circuit breaker is open", retry_after_s: float = 0.0) -> None:
        super().__init__(message)
        self.retry_after_s = max(0.0, float(retry_after_s))


_LOW_RELEVANCE_MESSAGE = (
    "Your notes don't seem to cover this: the closest passages and concepts don't match the "
    "question. Add notes on this topic or rephrase it with the terms your notes use."
)


def _extract_chunk_scores(
    chunks: Sequence[dict[str, Any]],
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Extract (best_vector_score, best_rrf_score, best_rerank_score) from GraphRecall chunk dicts."""
    vector_scores: list[float] = []
    rrf_scores: list[float] = []
    rerank_scores: list[float] = []

    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue

        rrf_raw = chunk.get("rrf_score")
        if rrf_raw is None:
            rrf_raw = chunk.get("_rrf_score")
        if rrf_raw is not None:
            try:
                rrf_scores.append(float(rrf_raw))
            except (TypeError, ValueError):
                pass

        rerank_raw = chunk.get("rerank_score")
        if rerank_raw is not None:
            try:
                rerank_scores.append(float(rerank_raw))
            except (TypeError, ValueError):
                pass

        vec_raw = chunk.get("similarity")
        if vec_raw is None:
            vec_raw = chunk.get("score")
        if vec_raw is None and rrf_raw is None:
            vec_raw = chunk.get("_score")
        if vec_raw is not None:
            try:
                vector_scores.append(float(vec_raw))
            except (TypeError, ValueError):
                pass

    return (
        max(vector_scores) if vector_scores else None,
        max(rrf_scores) if rrf_scores else None,
        max(rerank_scores) if rerank_scores else None,
    )


# Words that frame a question rather than name its topic. Kept out of term coverage.
_QUESTION_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "do", "does", "for", "from", "has", "have",
    "how", "in", "is", "it", "its", "of", "on", "or", "that", "the", "this", "to", "was", "were",
    "what", "when", "where", "which", "who", "why", "will", "with", "i", "me", "my", "you", "your",
    "can", "could", "should", "would", "explain", "describe", "tell", "about", "between",
    "difference", "different", "use", "using", "make", "work", "works", "get", "best", "way",
    "please", "vs", "versus", "s", "there", "their", "them", "they", "we", "our", "if", "than",
})
_TERM_RE = re.compile(r"[a-z0-9]+")

# Calibrated on GraphRecall's own corpus (10 in-domain vs 10 off-topic questions, Nov 2026):
# best cosine in-domain 0.605-0.862, off-topic 0.550-0.607; passage term coverage in-domain
# >= 0.5, off-topic 0.0 for all ten; concept-name coverage in-domain > 0, off-topic 0.0.
_STRONG_SIMILARITY = 0.66
_MIN_TERM_COVERAGE = 0.6


def query_terms(query: str) -> list[str]:
    """Content terms of a question, in order, deduplicated (single letters dropped, digits kept)."""
    out: list[str] = []
    for tok in _TERM_RE.findall((query or "").lower()):
        if tok in _QUESTION_STOPWORDS or (len(tok) == 1 and not tok.isdigit()) or tok in out:
            continue
        out.append(tok)
    return out


def _chunk_text(chunk: dict[str, Any]) -> str:
    return " ".join(
        str(chunk.get(k) or "")
        for k in ("title", "content", "window_content", "parent_content", "child_content", "text")
    )


def _coverage(terms: Sequence[str], texts: Sequence[str]) -> float:
    vocab: set[str] = set()
    for text in texts:
        vocab.update(_TERM_RE.findall(text.lower()))
    return sum(t in vocab for t in terms) / len(terms)


def evaluate_retrieval_confidence(
    chunks: Sequence[dict[str, Any]],
    graph_concepts: Sequence[dict[str, Any]],
    intent: str,
    query: str = "",
    min_vector_score: float = _STRONG_SIMILARITY,
    min_term_coverage: float = _MIN_TERM_COVERAGE,
) -> GroundingDecision:
    """Decide whether retrieved chunks and graph concepts justify answering or abstaining.

    Off-topic means all three signals fail: no strong semantic match (best cosine), no query term
    naming a retrieved concept, and too few query terms in the retrieved passages. RRF and the
    reranker score are deliberately not used: RRF is rank-based (whatever ranks first scores
    1/(k+1) however irrelevant), and the reranker min-max normalises within the candidate set.
    """
    valid_chunk_indices = set(range(1, len(chunks) + 1))
    valid_graph_ids = {f"G{i}" for i in range(1, len(graph_concepts) + 1)}
    best_vector, best_rrf, best_rerank = _extract_chunk_scores(chunks)
    score_candidates = [s for s in (best_vector, best_rerank, best_rrf) if s is not None]
    max_score = max(score_candidates) if score_candidates else 0.0

    def decide(abstain: bool, tier: Literal["high", "medium", "low"], reason: str,
               term_cov: Optional[float] = None, concept_cov: Optional[float] = None,
               message: str = "") -> GroundingDecision:
        return GroundingDecision(
            should_abstain=abstain,
            confidence_tier=tier,
            reason=reason,
            max_score=max_score if chunks or graph_concepts else 0.0,
            valid_chunk_indices=valid_chunk_indices,
            valid_graph_ids=valid_graph_ids,
            abstention_message=message,
            best_similarity=best_vector,
            term_coverage=term_cov,
            concept_coverage=concept_cov,
        )

    norm_intent = (intent or "general").strip().lower()
    if norm_intent in _GENERAL_BYPASS_INTENTS:
        return decide(False, "medium", "general_intent_bypass")

    if not chunks and not graph_concepts:
        return decide(True, "low", "no_retrieval_results", message=(
            "I couldn't find enough matching information in your notes or knowledge graph "
            "to answer this reliably. Try adding notes on this topic or rephrasing your question."
        ))

    semantic_ok = best_vector is not None and best_vector >= min_vector_score
    terms = query_terms(query)

    if not terms:
        # Nothing topical to check (no query passed, or only framing words): similarity alone.
        if best_vector is not None and not semantic_ok and not graph_concepts:
            return decide(True, "low", "low_vector_similarity", message=_LOW_RELEVANCE_MESSAGE)
        return decide(False, "high" if semantic_ok else "medium",
                      "graph_and_chunk_support" if graph_concepts else "chunk_support_sufficient")

    term_cov = _coverage(terms, [_chunk_text(c) for c in chunks if isinstance(c, dict)]) if chunks else 0.0
    concept_cov = _coverage(terms, [str(c.get("name") or "") for c in graph_concepts if isinstance(c, dict)])
    lexical_ok = term_cov >= min_term_coverage
    concept_ok = concept_cov > 0.0

    if not (semantic_ok or lexical_ok or concept_ok):
        return decide(True, "low", "off_topic", term_cov, concept_cov, _LOW_RELEVANCE_MESSAGE)

    tier: Literal["high", "medium", "low"] = "high" if semantic_ok and (lexical_ok or concept_ok) else "medium"
    reason = "graph_and_chunk_support" if concept_ok and chunks else (
        "graph_only_support" if concept_ok else "chunk_support_sufficient")
    return decide(False, tier, reason, term_cov, concept_cov)


def verify_citations(
    answer_text: str,
    valid_chunk_indices: set[int],
    valid_graph_ids: Optional[set[str]] = None,
) -> CitationAudit:
    """Audit and strip invalid [1] / [G1] citations while preserving markdown links."""
    if not answer_text:
        return CitationAudit(valid_refs=[], invalid_refs=[], grounded_ratio=1.0, cleaned_text="")

    normalized_graph_ids = {gid.upper() for gid in (valid_graph_ids or set())}
    valid_refs: list[str] = []
    invalid_refs: list[str] = []

    def _replace_match(match: re.Match[str]) -> str:
        lead, raw_inner = match.group(1), match.group(2)
        if not lead and _is_indexing_chain(match.string, match.start(2) - 1):
            return match.group(0)
        parts = [p.strip() for p in raw_inner.split(",") if p.strip()]
        if any(p == "0" or (p.isdigit() and len(p) > 3) for p in parts):
            return match.group(0)  # citations are 1-based and small: [0] or [2024] is not one
        kept_parts: list[str] = []

        for part in parts:
            upper = part.upper()
            if upper.startswith("G"):
                if upper in normalized_graph_ids:
                    valid_refs.append(upper)
                    kept_parts.append(upper)
                else:
                    invalid_refs.append(upper)
            else:
                try:
                    idx = int(part)
                except ValueError:
                    invalid_refs.append(part)
                    continue
                if idx in valid_chunk_indices:
                    valid_refs.append(str(idx))
                    kept_parts.append(str(idx))
                else:
                    invalid_refs.append(str(idx))

        if not kept_parts:
            return ""  # drop the citation and the one space before it; nothing else is rewritten
        return lead + "[" + ", ".join(kept_parts) + "]"

    # Only prose is audited: code segments (odd indices after the split) pass through untouched.
    segments = _CODE_SEGMENT_RE.split(answer_text)
    cleaned = "".join(seg if i % 2 else _BRACKET_CITATION_RE.sub(_replace_match, seg)
                      for i, seg in enumerate(segments))

    total = len(valid_refs) + len(invalid_refs)
    grounded_ratio = (len(valid_refs) / total) if total > 0 else 1.0
    return CitationAudit(
        valid_refs=valid_refs,
        invalid_refs=invalid_refs,
        grounded_ratio=round(grounded_ratio, 6),
        cleaned_text=cleaned,
    )


def _extract_status_code(exc: BaseException) -> Optional[int]:
    for attr in ("status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    response = getattr(exc, "response", None)
    if response is not None:
        val = getattr(response, "status_code", None)
        if isinstance(val, int):
            return val
    return None


def is_retryable_llm_error(exc: BaseException) -> bool:
    """Return True only for transient/upstream LLM errors that should trip a circuit breaker."""
    if any(cls.__name__ == "ValidationError" for cls in type(exc).__mro__):
        return False
    if isinstance(exc, ValueError):
        return False

    status_code = _extract_status_code(exc)
    if status_code is not None:
        if status_code in _NON_RETRYABLE_STATUS_CODES:
            return False
        if status_code in _RETRYABLE_STATUS_CODES:
            return True

    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, ConnectionError)):
        return True

    msg = str(exc).lower()
    if any(marker in msg for marker in _RETRYABLE_MSG_MARKERS):
        return True
    return False


class AsyncCircuitBreaker:
    """Async CLOSED -> OPEN -> HALF_OPEN -> CLOSED circuit breaker for LLM calls."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 30.0,
        half_open_max_calls: int = 2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._failure_threshold = max(1, int(failure_threshold))
        self._recovery_timeout_s = max(0.0, float(recovery_timeout_s))
        self._half_open_max_calls = max(1, int(half_open_max_calls))
        self._clock = clock
        self._lock = asyncio.Lock()

        self._state: Literal["closed", "open", "half_open"] = "closed"
        self._consecutive_failures = 0
        self._open_count = 0
        self._rejected_calls = 0
        self._opened_at = 0.0
        self._half_open_calls = 0
        self._half_open_successes = 0

    def _maybe_advance_state_locked(self) -> None:
        if self._state == "open":
            elapsed = self._clock() - self._opened_at
            if elapsed >= self._recovery_timeout_s:
                self._state = "half_open"
                self._half_open_calls = 0
                self._half_open_successes = 0

    @property
    def state(self) -> Literal["closed", "open", "half_open"]:
        self._maybe_advance_state_locked()
        return self._state

    async def call(
        self,
        fn: Callable[..., Coroutine[Any, Any, T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        async with self._lock:
            self._maybe_advance_state_locked()
            entered_half_open = False
            if self._state == "open":
                self._rejected_calls += 1
                remaining = max(0.0, self._recovery_timeout_s - (self._clock() - self._opened_at))
                raise CircuitBreakerOpenError(
                    f"Circuit breaker is open; retry in {remaining:.2f}s",
                    retry_after_s=remaining,
                )
            if self._state == "half_open":
                if self._half_open_calls >= self._half_open_max_calls:
                    self._rejected_calls += 1
                    raise CircuitBreakerOpenError(
                        "Circuit breaker is half-open and probe limit reached",
                        retry_after_s=0.0,
                    )
                self._half_open_calls += 1
                entered_half_open = True

        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:
            async with self._lock:
                if is_retryable_llm_error(exc):
                    self._consecutive_failures += 1
                    if self._state != "open" and (
                        entered_half_open or self._consecutive_failures >= self._failure_threshold
                    ):
                        self._state = "open"
                        self._opened_at = self._clock()
                        self._open_count += 1
                        self._half_open_calls = 0
                        self._half_open_successes = 0
                elif entered_half_open and self._state == "half_open":
                    # Non-retryable client error does not trip the breaker; release probe slot.
                    self._half_open_calls = max(0, self._half_open_calls - 1)
            raise

        async with self._lock:
            if entered_half_open and self._state == "half_open":
                self._half_open_successes += 1
                if self._half_open_successes >= self._half_open_max_calls:
                    self._state = "closed"
                    self._consecutive_failures = 0
                    self._half_open_calls = 0
                    self._half_open_successes = 0
            elif self._state == "closed":
                self._consecutive_failures = 0

        return result

    def stats(self) -> dict[str, Any]:
        self._maybe_advance_state_locked()
        return {
            "state": self._state,
            "consecutive_failures": self._consecutive_failures,
            "open_count": self._open_count,
            "rejected_calls": self._rejected_calls,
        }
