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

# Match bracketed citation groups like [1], [G1], [1, 2], [1, G2] ONLY when NOT immediately followed by '('.
_BRACKET_CITATION_RE = re.compile(
    r"\[(\s*(?:G?\d+)(?:\s*,\s*G?\d+)*\s*)\](?!\()",
    re.IGNORECASE,
)


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


def evaluate_retrieval_confidence(
    chunks: Sequence[dict[str, Any]],
    graph_concepts: Sequence[dict[str, Any]],
    intent: str,
    min_vector_score: float = 0.58,
    min_rrf_score: float = 0.012,
) -> GroundingDecision:
    """Decide whether retrieved chunks and graph concepts justify answering or abstaining."""
    valid_chunk_indices = set(range(1, len(chunks) + 1))
    valid_graph_ids = {f"G{i}" for i in range(1, len(graph_concepts) + 1)}
    best_vector, best_rrf, best_rerank = _extract_chunk_scores(chunks)
    score_candidates = [s for s in (best_vector, best_rerank, best_rrf) if s is not None]
    max_score = max(score_candidates) if score_candidates else 0.0

    norm_intent = (intent or "general").strip().lower()
    if norm_intent in _GENERAL_BYPASS_INTENTS:
        return GroundingDecision(
            should_abstain=False,
            confidence_tier="medium",
            reason="general_intent_bypass",
            max_score=max_score,
            valid_chunk_indices=valid_chunk_indices,
            valid_graph_ids=valid_graph_ids,
            abstention_message="",
        )

    if not chunks and not graph_concepts:
        return GroundingDecision(
            should_abstain=True,
            confidence_tier="low",
            reason="no_retrieval_results",
            max_score=0.0,
            valid_chunk_indices=valid_chunk_indices,
            valid_graph_ids=valid_graph_ids,
            abstention_message=(
                "I couldn't find enough matching information in your notes or knowledge graph "
                "to answer this reliably. Try adding notes on this topic or rephrasing your question."
            ),
        )

    if not graph_concepts:
        has_vector = best_vector is not None
        has_rrf = best_rrf is not None
        vector_ok = best_vector >= min_vector_score if has_vector else False
        rrf_ok = best_rrf >= min_rrf_score if has_rrf else False

        abstain_reason: Optional[str] = None
        if has_vector and has_rrf:
            if not vector_ok and not rrf_ok:
                abstain_reason = "low_vector_and_rrf_score"
        elif has_vector and not vector_ok:
            abstain_reason = "low_vector_similarity"
        elif has_rrf and not rrf_ok:
            abstain_reason = "low_rrf_score"

        if abstain_reason is not None:
            return GroundingDecision(
                should_abstain=True,
                confidence_tier="low",
                reason=abstain_reason,
                max_score=max_score,
                valid_chunk_indices=valid_chunk_indices,
                valid_graph_ids=valid_graph_ids,
                abstention_message=(
                    "The retrieved note snippets had low relevance and no supporting knowledge graph "
                    "concepts were found. Please add more specific notes on this topic or refine your query."
                ),
            )

        high_vector = has_vector and best_vector >= max(min_vector_score + 0.12, 0.70)
        high_rrf = has_rrf and best_rrf >= (min_rrf_score * 2.0)
        tier: Literal["high", "medium", "low"] = (
            "high" if (high_vector or high_rrf) else "medium"
        )
        return GroundingDecision(
            should_abstain=False,
            confidence_tier=tier,
            reason="chunk_support_sufficient",
            max_score=max_score,
            valid_chunk_indices=valid_chunk_indices,
            valid_graph_ids=valid_graph_ids,
            abstention_message="",
        )

    # Graph concepts are present (with or without chunks).
    strong_chunk = (
        (best_vector is not None and best_vector >= min_vector_score)
        or (best_rrf is not None and best_rrf >= min_rrf_score)
        or (bool(chunks) and best_vector is None and best_rrf is None)
    )
    return GroundingDecision(
        should_abstain=False,
        confidence_tier="high" if strong_chunk else "medium",
        reason="graph_and_chunk_support" if chunks else "graph_only_support",
        max_score=max_score,
        valid_chunk_indices=valid_chunk_indices,
        valid_graph_ids=valid_graph_ids,
        abstention_message="",
    )


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
        raw_inner = match.group(1)
        parts = [p.strip() for p in raw_inner.split(",") if p.strip()]
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
            return ""
        return "[" + ", ".join(kept_parts) + "]"

    cleaned = _BRACKET_CITATION_RE.sub(_replace_match, answer_text)
    if invalid_refs:
        # Collapse horizontal whitespace introduced by stripped citations without collapsing newlines.
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
        cleaned = re.sub(r"[ \t]+([.,;:!?])", r"\1", cleaned)
        cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
        cleaned = cleaned.strip()

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
