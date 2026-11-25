"""Follow-up questions: give retrieval the context a human would assume, without an LLM call.

Turn 1 "Explain LoRA", turn 2 "what are its limitations?" — retrieving on "its limitations"
alone finds nothing about LoRA. A follow-up is detected from pronouns / continuation openers / a
very short question when there is an earlier turn; the retrieval query is then anchored to the
previous turn's topics (entities from that turn's routing), or to its question text. The router
still classifies the user's exact words; only retrieval sees the expanded query.

Why not an LLM rewrite: one more model call (~300-800 ms and quota) on every follow-up, for a case
this cheap rule handles; an LLM rewrite can be added behind a flag when the rule misses (measure on
logged multi-turn queries first).
"""
from __future__ import annotations

import re
from typing import Optional

_PRONOUN = re.compile(r"\b(it|its|it's|itself|this|that|these|those|they|them|their|theirs|the same|above|"
                      r"previous|earlier|former|latter|such)\b", re.I)
_OPENER = re.compile(r"^\s*(and|but|also|so|then|what about|how about|why not|why|how come|ok|okay|"
                     r"compared to|versus|vs\.?|same for|more on|go on|continue|elaborate|example)\b", re.I)
MAX_SHORT_WORDS = 4


def is_followup(query: str, has_history: bool) -> bool:
    if not has_history or not query.strip():
        return False
    words = query.split()
    return bool(_PRONOUN.search(query) or _OPENER.match(query) or len(words) <= MAX_SHORT_WORDS)


def contextualize(query: str, previous_question: Optional[str], previous_entities: Optional[list[str]]) -> str:
    """Retrieval query for this turn. Returns the query unchanged when it stands on its own."""
    if not is_followup(query, bool(previous_question or previous_entities)):
        return query
    previous_entities = [e for e in (previous_entities or []) if e]
    anchor_terms = [e for e in previous_entities if e.lower() not in query.lower()][:4]
    if previous_entities and not anchor_terms:
        return query  # the follow-up already names the topic ("why does LoRA work?")
    if anchor_terms:
        anchor = ", ".join(anchor_terms)
    elif previous_question:
        anchor = " ".join(previous_question.split()[:24])
    else:
        return query
    return f"{query.strip()} (about: {anchor})"
