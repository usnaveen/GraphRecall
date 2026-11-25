"""Follow-up questions: give retrieval the context a human would assume, without an LLM call.

Turn 1 "Explain LoRA", turn 2 "what are its limitations?" — retrieving on "its limitations"
alone finds nothing about LoRA. A follow-up is detected from anaphoric pronouns, explicit
continuation/comparative openers, or very short non-standalone queries when there is an earlier
non-greeting turn; the retrieval query is then anchored to the previous turn's entities or
compact content keywords without punctuation that breaks Postgres `websearch_to_tsquery` AND
semantics. The router still classifies the user's exact words; only retrieval sees the expanded
query.
"""
from __future__ import annotations

import re
from typing import Optional

_PRONOUN = re.compile(
    r"\b(it|its|it's|itself|this|that|these|those|they|them|their|theirs|the same|above|"
    r"previous|earlier|former|latter|same)\b",
    re.I,
)
_EXPLICIT_CONTINUATION_OPENER = re.compile(
    r"^\s*(what about|how about|why not|compared to|compare with|compare to|versus|vs\.?|"
    r"same for|more on|go on|continue|elaborate|give an example|example)\b",
    re.I,
)
_GENERIC_OPENER = re.compile(
    r"^\s*(and|but|also|so|then|why|how come|ok|okay)\b",
    re.I,
)
_TRIVIAL_GREETING = re.compile(
    r"^\s*(hi|hello|hey|yo|sup|thanks|thank you|thx|ok|okay|good morning|good afternoon|good evening)[!.?\s]*$",
    re.I,
)
_WORD_TOKEN_RE = re.compile(r"[A-Za-z0-9_`-]+")

_NON_SUBJECT_CAPS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "could", "did", "do",
        "does", "explain", "find", "for", "from", "give", "how", "i", "if", "in", "is", "it",
        "its", "me", "more", "of", "ok", "okay", "on", "or", "please", "show", "so", "summarize",
        "tell", "that", "the", "their", "them", "then", "these", "they", "this", "those", "to",
        "what", "when", "where", "which", "who", "why", "will", "with", "would",
    }
)
_ANCHOR_STOPWORDS = _NON_SUBJECT_CAPS | frozenset(
    {
        "about", "after", "all", "also", "any", "because", "been", "before", "being", "between",
        "both", "compare", "contrast", "difference", "different", "each", "example", "examples",
        "general", "had", "has", "have", "having", "here", "into", "just", "like", "make", "many",
        "may", "might", "most", "much", "must", "need", "no", "not", "now", "only", "other",
        "our", "out", "over", "same", "should", "since", "some", "such", "than", "there",
        "through", "under", "up", "use", "used", "using", "very", "was", "we", "were", "while",
        "work", "works", "you", "your",
    }
)

MAX_SHORT_WORDS = 4


def _has_own_subject(query: str) -> bool:
    """Return True when the query names a capitalized or technical subject of its own."""
    words = _WORD_TOKEN_RE.findall(query)
    for idx, tok in enumerate(words):
        cleaned = tok.strip("`.,?!:;\"'()[]{}")
        if len(cleaned) < 2:
            continue
        if cleaned.isupper() and cleaned.isalpha():
            return True
        if any(c.isupper() for c in cleaned[1:]) and any(c.islower() for c in cleaned):
            return True
        if any(c.isdigit() for c in cleaned) and any(c.isalpha() for c in cleaned):
            return True
        if idx > 0 and cleaned[0].isupper() and cleaned.lower() not in _NON_SUBJECT_CAPS:
            return True
    return False


def _contains_term(query: str, term: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", query, re.I))


def is_followup(query: str, has_history: bool) -> bool:
    """Detect whether a query depends on the preceding conversation turn."""
    clean = (query or "").strip()
    if not has_history or not clean:
        return False
    if _PRONOUN.search(clean):
        return True
    if _EXPLICIT_CONTINUATION_OPENER.match(clean):
        return True

    words = clean.split()
    if len(words) <= MAX_SHORT_WORDS:
        if _GENERIC_OPENER.match(clean):
            return True
        return not _has_own_subject(clean)

    # Queries >= 5 words with a generic opener ("why", "and", "so", "then", "but") and no
    # anaphoric pronoun are treated as standalone unless explicitly elliptical above.
    return False


def contextualize(
    query: str,
    previous_question: Optional[str],
    previous_entities: Optional[list[str]],
) -> str:
    """Retrieval query for this turn. Returns the query unchanged when it stands on its own."""
    clean_query = (query or "").strip()
    if not clean_query:
        return query

    clean_prev_q = (previous_question or "").strip()
    if clean_prev_q and _TRIVIAL_GREETING.match(clean_prev_q):
        clean_prev_q = ""

    clean_entities = [
        e.strip()
        for e in (previous_entities or [])
        if isinstance(e, str) and e.strip()
    ]

    if not is_followup(clean_query, bool(clean_prev_q or clean_entities)):
        return query

    if clean_entities:
        anchor_terms = [e for e in clean_entities if not _contains_term(clean_query, e)][:4]
        if not anchor_terms:
            return query  # the follow-up already names the topic ("why does LoRA work?")
        anchor = " ".join(anchor_terms)
        return f"{clean_query} {anchor}"

    if clean_prev_q:
        content_terms: list[str] = []
        seen_lower: set[str] = set()
        for raw_tok in _WORD_TOKEN_RE.findall(clean_prev_q):
            tok = raw_tok.strip("`.,?!:;\"'()[]{}")
            if len(tok) < 2:
                continue
            low = tok.lower()
            if low in _ANCHOR_STOPWORDS or low in seen_lower:
                continue
            if _contains_term(clean_query, tok):
                continue
            seen_lower.add(low)
            content_terms.append(tok)
            if len(content_terms) >= 8:
                break
        if not content_terms:
            return query
        return f"{clean_query} {' '.join(content_terms)}"

    return query
