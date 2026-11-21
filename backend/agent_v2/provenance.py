"""Provenance validation enforcing 'no quote, no edge' on agent-proposed bridges."""

from __future__ import annotations

import re
from typing import Iterable

from backend.agent_v2.protocols import (
    NoteChunk,
    ProposedBridge,
    ProvenanceReport,
    RejectedBridge,
    VerifiedBridge,
    VerifiedQuote,
)

_SMART_TRANS = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u00a0": " ",
})

_WHITESPACE_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "if", "in", "on", "at", "to", "for",
    "of", "by", "with", "from", "as", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "this", "that", "these", "those",
    "it", "its", "he", "she", "they", "we", "you", "i", "me", "my", "your",
    "our", "their", "his", "her", "not", "no", "nor", "so", "too", "very",
    "than", "then", "there", "here", "where", "when", "what", "which", "who",
    "whom", "how", "all", "any", "both", "each", "few", "more", "most", "other",
    "some", "such", "into", "out", "up", "down", "over", "under", "about",
    "between", "through", "during", "before", "after",
})


def normalize_for_quote_match(text: str) -> str:
    """Normalize typography and whitespace for strict substring provenance matching."""
    if not text:
        return ""
    cleaned = text.translate(_SMART_TRANS).strip().lower()
    return _WHITESPACE_RE.sub(" ", cleaned)


def verify_quote_in_text(
    quote: str,
    chunk_text: str,
    *,
    min_chars: int = 12,
    min_content_tokens: int = 2,
) -> bool:
    """Return True iff `quote` is non-trivial (length + content words) and appears verbatim."""
    norm_quote = normalize_for_quote_match(quote)
    if len(norm_quote) < min_chars:
        return False
    content_tokens = {
        tok for tok in _TOKEN_RE.findall(norm_quote)
        if len(tok) >= 3 and tok not in _STOPWORDS
    }
    if len(content_tokens) < min_content_tokens:
        return False
    norm_chunk = normalize_for_quote_match(chunk_text)
    if not norm_chunk:
        return False
    return norm_quote in norm_chunk


def validate_proposed_bridges(
    proposals: Iterable[ProposedBridge],
    chunks_by_id: dict[str, NoteChunk],
    *,
    min_chars: int = 12,
) -> ProvenanceReport:
    """Validate every proposed bridge against cited source and target chunks."""
    accepted: list[VerifiedBridge] = []
    rejected: list[RejectedBridge] = []

    for proposal in proposals:
        src_chunk = chunks_by_id.get(proposal.source_chunk_id)
        if src_chunk is None:
            rejected.append(RejectedBridge(proposal=proposal, reason="missing_source_chunk"))
            continue

        tgt_chunk = chunks_by_id.get(proposal.target_chunk_id)
        if tgt_chunk is None:
            rejected.append(RejectedBridge(proposal=proposal, reason="missing_target_chunk"))
            continue

        if src_chunk.note_id == tgt_chunk.note_id:
            rejected.append(RejectedBridge(proposal=proposal, reason="same_note_bridge_not_cross_note"))
            continue

        if not verify_quote_in_text(proposal.source_quote, src_chunk.content, min_chars=min_chars):
            rejected.append(RejectedBridge(proposal=proposal, reason="unverified_source_quote"))
            continue

        if not verify_quote_in_text(proposal.target_quote, tgt_chunk.content, min_chars=min_chars):
            rejected.append(RejectedBridge(proposal=proposal, reason="unverified_target_quote"))
            continue

        accepted.append(
            VerifiedBridge(
                proposal=proposal,
                verified_quotes=[
                    VerifiedQuote(
                        chunk_id=src_chunk.chunk_id,
                        note_id=src_chunk.note_id,
                        note_title=src_chunk.note_title,
                        quote=proposal.source_quote.strip(),
                    ),
                    VerifiedQuote(
                        chunk_id=tgt_chunk.chunk_id,
                        note_id=tgt_chunk.note_id,
                        note_title=tgt_chunk.note_title,
                        quote=proposal.target_quote.strip(),
                    ),
                ],
            )
        )

    return ProvenanceReport(accepted=accepted, rejected=rejected)
