"""Deterministic-first conversational query rewriter for multi-turn RAG follow-ups.

Fast gating (`needs_rewrite`) skips standalone queries in <0.1 ms, while follow-ups
with coreference, comparative ellipsis, or ultra-short phrasing are rewritten via an
optional async LLM function with automatic timeout/error fallback to deterministic
entity carryover from recent conversation turns.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Optional

RewriteMethod = Literal["passthrough", "llm", "entity_carryover"]
LLMRewriteFn = Callable[[str, list[dict[str, Any]]], Awaitable[str] | str]

_PRONOUN_RE = re.compile(
    r"\b(?:it|its|they|them|their|that|this|those|these|former|latter|same)\b",
    re.IGNORECASE,
)
_ELLIPSIS_RE = re.compile(
    r"\b(?:compare\s+with|compare\s+to|how\s+does\s+it|why\s+does\s+that|"
    r"vs\.?|versus|difference|what\s+about|how\s+about)\b",
    re.IGNORECASE,
)

_BACKTICK_RE = re.compile(r"`([^`\n]{2,80})`")
_ACRONYM_RE = re.compile(r"\b[A-Z]{2,}[A-Z0-9_-]*\b")
_MIXED_TECH_RE = re.compile(
    r"\b(?:[A-Za-z]*[A-Z][a-z]*[A-Z][A-Za-z0-9_-]*|[A-Za-z]{2,}[0-9]+[A-Za-z0-9_-]*)\b"
)
_CAP_PHRASE_RE = re.compile(r"\b[A-Z][a-zA-Z0-9-]+(?:\s+[A-Z][a-zA-Z0-9-]+){1,3}\b")
_CAP_WORD_RE = re.compile(r"\b[A-Z][a-zA-Z0-9_-]{2,}\b")
_WORD_RE = re.compile(r"[A-Za-z0-9_`-]+")

_XML_TAG_RE = re.compile(r"<[^>]{1,160}>|<\|[^|>]{1,80}\|>")
_OVERRIDE_LINE_RE = re.compile(
    r"(?:^|\b)(?:ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?[^.!?\n]*[.!?]?|"
    r"system\s*(?:prompt|override)?\s*:|developer\s*:|assistant\s*:|user\s*:|"
    r"\[/?(?:inst|sys|system)\])",
    re.IGNORECASE,
)

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "because", "before", "after",
        "but", "by", "can", "could", "did", "do", "does", "for", "from", "had",
        "has", "have", "here", "how", "i", "if", "in", "into", "is", "it", "its",
        "let", "may", "might", "more", "most", "no", "not", "of", "ok", "okay",
        "on", "or", "our", "please", "see", "should", "since", "so", "some",
        "sure", "than", "that", "the", "their", "them", "then", "there", "these",
        "they", "this", "those", "to", "try", "use", "used", "uses", "using",
        "was", "we", "were", "what", "when", "where", "which", "while", "who",
        "why", "will", "with", "would", "yes", "you", "your",
        # Discourse / section starters commonly capitalized in answers
        "additionally", "actually", "although", "also", "answer", "basically",
        "context", "currently", "essentially", "example", "figure", "finally",
        "first", "furthermore", "generally", "hello", "hey", "hi", "however",
        "importantly", "instead", "moreover", "note", "notes", "overview",
        "question", "second", "section", "specifically", "step", "summary",
        "system", "table", "thank", "thanks", "therefore", "third", "typically",
        "user", "assistant", "usually",
    }
)


@dataclass(frozen=True, slots=True)
class RewriteResult:
    """Structured outcome from conversational query rewriting."""

    rewritten_query: str
    was_rewritten: bool
    method: RewriteMethod
    latency_ms: float
    extracted_entities: list[str]


def _extract_turn_text(turn: Any) -> tuple[str, str]:
    if isinstance(turn, dict):
        role = str(turn.get("role") or turn.get("type") or "").strip().lower()
        content = turn.get("content") or turn.get("text") or ""
        return role, str(content).strip()
    return "", str(turn or "").strip()


def _has_prior_turn(history: list[dict[str, Any]] | None) -> bool:
    if not history:
        return False
    for turn in history:
        _, content = _extract_turn_text(turn)
        if content:
            return True
    return False


def _has_standalone_entity(query: str) -> bool:
    if _BACKTICK_RE.search(query):
        return True
    if _ACRONYM_RE.search(query) or _MIXED_TECH_RE.search(query):
        return True
    words = _WORD_RE.findall(query)
    for idx, token in enumerate(words):
        cleaned = token.strip("`.,?!:;\"'()[]{}")
        if not cleaned:
            continue
        # Non-initial capitalized word that isn't a plain stopword counts as an entity.
        if idx > 0 and cleaned[0].isupper() and cleaned.lower() not in _STOPWORDS:
            return True
    return False


def needs_rewrite(query: str, history: list[dict[str, Any]]) -> bool:
    """Fast deterministic gate deciding whether a query needs conversational rewriting."""
    clean_query = (query or "").strip()
    if not clean_query or not _has_prior_turn(history):
        return False

    if _PRONOUN_RE.search(clean_query):
        return True
    if _ELLIPSIS_RE.search(clean_query):
        return True

    words = _WORD_RE.findall(clean_query)
    if len(words) <= 4 and not _has_standalone_entity(clean_query):
        return True

    return False


def _select_recent_turn_texts(history: list[dict[str, Any]]) -> list[str]:
    """Return text from the most recent user turn and most recent assistant response."""
    if not history:
        return []

    last_user: Optional[tuple[int, str]] = None
    last_assistant: Optional[tuple[int, str]] = None
    fallback: list[tuple[int, str]] = []

    for idx, turn in enumerate(history):
        role, content = _extract_turn_text(turn)
        if not content:
            continue
        fallback.append((idx, content))
        if role in ("user", "human"):
            last_user = (idx, content)
        elif role in ("assistant", "ai", "model", "bot"):
            last_assistant = (idx, content)

    selected: list[tuple[int, str]] = []
    if last_user is not None:
        selected.append(last_user)
    if last_assistant is not None:
        selected.append(last_assistant)

    if not selected:
        selected = fallback[-2:]

    selected.sort(key=lambda pair: pair[0])
    return [text for _, text in selected]


def _normalize_candidate(term: str) -> str:
    return term.strip("`.,?!:;\"'()[]{} ")


def extract_history_entities(
    history: list[dict[str, Any]],
    max_entities: int = 4,
) -> list[str]:
    """Extract salient technical terms, acronyms, phrases, and backticked identifiers."""
    if max_entities <= 0 or not history:
        return []

    texts = _select_recent_turn_texts(history)
    if not texts:
        return []

    combined = "\n".join(texts)
    candidates: list[str] = []

    def _add(raw: str) -> None:
        cleaned = _normalize_candidate(raw)
        if len(cleaned) < 2:
            return
        if cleaned.lower() in _STOPWORDS:
            return
        candidates.append(cleaned)

    # Priority order: backticked identifiers -> acronyms/mixed-case tech -> multi-word phrases -> non-initial proper nouns.
    for match in _BACKTICK_RE.finditer(combined):
        _add(match.group(1))
    for match in _ACRONYM_RE.finditer(combined):
        _add(match.group(0))
    for match in _MIXED_TECH_RE.finditer(combined):
        _add(match.group(0))
    for match in _CAP_PHRASE_RE.finditer(combined):
        phrase = _normalize_candidate(match.group(0))
        words = phrase.split()
        # Trim leading stopword if sentence-initial (e.g. "The Reciprocal Rank Fusion").
        while words and words[0].lower() in _STOPWORDS:
            words = words[1:]
        if len(words) >= 2:
            _add(" ".join(words))
    for text in texts:
        # Collect standalone capitalized words not solely at sentence start.
        for match in _CAP_WORD_RE.finditer(text):
            start = match.start()
            before = text[:start].rstrip()
            at_sentence_start = (not before) or before[-1] in ".!?\n:"
            if not at_sentence_start:
                _add(match.group(0))

    deduped: list[str] = []
    seen_lower: set[str] = set()
    for term in candidates:
        key = term.lower()
        if key in seen_lower:
            continue
        seen_lower.add(key)
        deduped.append(term)
        if len(deduped) >= max_entities:
            break

    return deduped


def deterministic_entity_carryover(query: str, history: list[dict[str, Any]]) -> str:
    """Append concise disambiguation entities from recent history to the query."""
    clean_query = (query or "").strip()
    entities = extract_history_entities(history)
    if not entities:
        return clean_query
    return f"{clean_query} (context: {', '.join(entities)})"


def sanitize_rewritten_query(text: str, max_chars: int = 400) -> str:
    """Strip XML/prompt-injection markers, collapse whitespace, and cap length."""
    if not text:
        return ""
    cleaned = _XML_TAG_RE.sub(" ", str(text))
    cleaned = _OVERRIDE_LINE_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'"):
        cleaned = cleaned[1:-1].strip()
    if max_chars > 0 and len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip()
    return cleaned


async def rewrite_followup_query(
    query: str,
    history: list[dict[str, Any]],
    llm_rewrite_fn: Optional[LLMRewriteFn] = None,
    timeout_s: float = 2.5,
    max_chars: int = 400,
) -> RewriteResult:
    """Rewrite conversational follow-up queries with fast gating and safe fallback."""
    t0 = time.perf_counter()
    clean_query = (query or "").strip()

    if not needs_rewrite(clean_query, history):
        return RewriteResult(
            rewritten_query=clean_query,
            was_rewritten=False,
            method="passthrough",
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            extracted_entities=[],
        )

    entities = extract_history_entities(history)

    if llm_rewrite_fn is not None:
        try:
            maybe_coro = llm_rewrite_fn(clean_query, history)
            if inspect.isawaitable(maybe_coro):
                raw_reply = await asyncio.wait_for(maybe_coro, timeout=timeout_s)
            else:
                raw_reply = maybe_coro
            sanitized = sanitize_rewritten_query(str(raw_reply or ""), max_chars=max_chars)
            if sanitized:
                return RewriteResult(
                    rewritten_query=sanitized,
                    was_rewritten=True,
                    method="llm",
                    latency_ms=(time.perf_counter() - t0) * 1000.0,
                    extracted_entities=entities,
                )
        except Exception:
            pass

    carried = sanitize_rewritten_query(
        deterministic_entity_carryover(clean_query, history),
        max_chars=max_chars,
    )
    if not carried:
        carried = clean_query[:max_chars].rstrip() if max_chars > 0 else clean_query

    return RewriteResult(
        rewritten_query=carried,
        was_rewritten=(carried != clean_query),
        method="entity_carryover",
        latency_ms=(time.perf_counter() - t0) * 1000.0,
        extracted_entities=entities,
    )
