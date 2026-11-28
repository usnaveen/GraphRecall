"""Deterministic claim splitting and passage windowing for local NLI faithfulness scoring.

No LLM is used anywhere here: markdown scaffolding and inline citations are stripped,
answers are segmented into atomic factual sentences/clauses, and retrieved note texts are
chunked into overlapping character windows that fit safely inside DeBERTa's 512-token budget.
"""
from __future__ import annotations

import re

_ABBREV_RE = re.compile(
    r"\b(?:e\.g|i\.e|vs|Dr|Mr|Mrs|Ms|Prof|Fig|Eq|Ref|al|approx|etc|St|No|Inc|Ltd|U\.S)\.",
    re.IGNORECASE,
)
_SCAFFOLD_PREFIX_RE = re.compile(
    r"^(?:based on your notes(?: and graph)?,?|from your notes,?|in summary,?|overall,?|additionally,?|moreover,?|note that:?|however,?)\s+",
    re.IGNORECASE,
)
_PURE_META_RE = re.compile(
    r"^(?:based on your notes|from your notes|here is (?:a |an )?(?:comparison|summary|overview|explanation)|in summary|conclusion|summary|references?)\b",
    re.IGNORECASE,
)


def clean_markdown(text: str) -> str:
    """Remove markdown formatting and inline citation tags like `[1]` or `[1, 3]`."""
    s = text.replace("\r\n", "\n")
    s = re.sub(r"\[\d{1,2}(?:\s*,\s*\d{1,2})*\]", "", s)
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", s)
    s = re.sub(r"\*\*(.*?)\*\*", r"\1", s)
    s = re.sub(r"__(.*?)__", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\s+([.,;:!?])", r"\1", s)
    return s


def split_claims(answer: str) -> list[str]:
    """Split a generated answer into atomic factual sentences/bullet claims."""
    if not answer or not answer.strip():
        return []
    cleaned = clean_markdown(answer)
    claims: list[str] = []

    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Strip bullet / numbered-list markers.
        is_bullet = bool(re.match(r"^(?:[-*•]+|\d+[.)])\s+", line))
        line = re.sub(r"^(?:[-*•]+|\d+[.)])\s+", "", line).strip()
        # Skip standalone headings / section lead-ins (ends with ':' or non-bullet title without punctuation).
        if line.endswith(":") and len(line.split()) <= 12:
            continue
        if not is_bullet and line[-1] not in ".!?" and len(line.split()) <= 10:
            continue
        if len(line.split()) < 4:
            continue

        # Protect decimals and common abbreviations before sentence splitting.
        protected = re.sub(r"(?<=\d)\.(?=\d)", "<DOT>", line)
        protected = _ABBREV_RE.sub(lambda m: m.group(0).replace(".", "<DOT>"), protected)

        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"(])", protected)
        for part in parts:
            sent = part.replace("<DOT>", ".").strip()
            sent = _SCAFFOLD_PREFIX_RE.sub("", sent).strip()
            if _PURE_META_RE.match(sent) and sent.endswith(":"):
                continue
            if len(sent.split()) < 5:
                continue
            if sent and sent[0].islower():
                sent = sent[0].upper() + sent[1:]
            claims.append(sent)

    return claims


_STOPWORDS = {
    "the", "and", "for", "that", "with", "from", "this", "are", "was", "were",
    "into", "which", "such", "more", "than", "have", "has", "can", "may",
    "often", "usually", "most", "when", "where", "what", "your", "based", "notes",
}


def _content_stems(text: str) -> set[str]:
    return {
        w[:5]
        for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(w) >= 3 and w not in _STOPWORDS
    }


def split_premise_sentences(texts: list[str]) -> list[str]:
    """Split retrieved notes into short 1-sentence units matching SNLI/MNLI premise granularity."""
    out: list[str] = []
    for text in texts:
        t = re.sub(r"\s+", " ", (text or "")).strip()
        if not t:
            continue
        for s in re.split(r"(?<=[.!?])\s+", t):
            s = s.strip()
            if not s:
                continue
            if len(s) <= 350:
                if len(s.split()) >= 4:
                    out.append(s)
            else:
                words = s.split()
                for i in range(0, len(words), 35):
                    seg = " ".join(words[i : i + 45])
                    if len(seg.split()) >= 4:
                        out.append(seg)
    return out


def candidate_premises_for_claim(
    sentences: list[str],
    claim: str,
    top_k: int = 30,
) -> list[tuple[str, int]]:
    """Select top-K (1-sentence and adjacent 2-sentence) premise candidates by content-stem overlap."""
    if not sentences:
        return []
    c_stems = _content_stems(claim)
    cands: list[tuple[int, int, str]] = []
    for i, s in enumerate(sentences):
        cands.append((len(c_stems & _content_stems(s)), 1, s))
        if i + 1 < len(sentences):
            w2 = f"{sentences[i]} {sentences[i + 1]}"
            cands.append((len(c_stems & _content_stems(w2)), 2, w2))
    cands.sort(key=lambda x: (-x[0], x[1]))
    seen: set[str] = set()
    picked: list[tuple[str, int]] = []
    for ov, _, txt in cands:
        if txt in seen:
            continue
        seen.add(txt)
        picked.append((txt, ov))
        if len(picked) >= top_k:
            break
    return picked


def chunk_passages(texts: list[str], window_chars: int = 900, overlap_chars: int = 200) -> list[str]:
    """Slice source texts into overlapping windows sized for a 512-token cross-encoder."""
    windows: list[str] = []
    step = max(1, window_chars - overlap_chars)
    for text in texts:
        t = re.sub(r"\s+", " ", (text or "")).strip()
        if not t:
            continue
        if len(t) <= window_chars:
            windows.append(t)
            continue
        for start in range(0, len(t), step):
            chunk = t[start : start + window_chars].strip()
            if chunk:
                windows.append(chunk)
            if start + window_chars >= len(t):
                break
    return windows
