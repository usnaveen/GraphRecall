"""Creative reels-style concept card engines (deterministic, zero LLM calls).

Provides four deterministic card engines aligned with GraphRecall's feed and
``knowledge_map`` evidence schema:

1. ``DiagramOcclusionCard`` & ``extract_diagram_cards_from_markdown`` — occludes
   high-information Mermaid diagram nodes/messages and extracts validated
   ``http(s)`` Markdown figure explanation cards.
2. ``SpotTheBugCard`` & ``SPOT_THE_BUG_CARDS`` — 8 production ML/RAG/Systems/
   LeetCode bug-spotting snippets with 1-based line grading and ``knowledge_map``
   compatible evidence payloads.
3. ``TradeoffDuelCard`` & ``TRADEOFF_DUEL_CARDS`` — 6 production RAG/ML
   system-design tradeoff duels.
4. ``DigestArticlePlan`` & ``plan_article_digest`` — deterministic pre-processor
   for "Digest This" on saved/curated articles, bounded by ``max_cards``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import re
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit

from backend.services.structure_cards import extract_structure_cards


# ---------------------------------------------------------------------------
# URL & text helpers
# ---------------------------------------------------------------------------

def is_safe_http_url(url: Optional[str]) -> bool:
    """Strictly validate that ``url`` is a well-formed ``http`` or ``https`` URL.

    Rejects ``javascript:``, ``data:``, ``file:``, missing host, whitespace in
    scheme/host, and any ASCII control characters.
    """
    if not isinstance(url, str) or not url:
        return False
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        return False
    cleaned = url.strip()
    if not cleaned or any(ch.isspace() for ch in cleaned):
        return False
    try:
        parsed = urlsplit(cleaned)
    except ValueError:
        return False
    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    if not parsed.netloc or not parsed.hostname:
        return False
    return True


def _short_id(prefix: str, seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _tokenize_match(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) >= 2}


def _match_score(concept_names: Iterable[str], *, title: str, concept_name: str, tags: Iterable[str],
                 extra: str = "") -> int:
    queries = [q.strip().lower() for q in (concept_names or []) if isinstance(q, str) and q.strip()]
    if not queries:
        return 0
    target_full = f"{concept_name} {title} {' '.join(tags)} {extra}".lower()
    target_tokens = _tokenize_match(target_full)
    tag_set = {t.lower() for t in tags}
    cname = concept_name.lower()
    score = 0
    for q in queries:
        if q == cname or q in tag_set:
            score += 10
        elif q in target_full:
            score += 6
        q_tokens = _tokenize_match(q)
        if q_tokens:
            overlap = len(q_tokens & target_tokens)
            score += overlap * 2
    return score


# ---------------------------------------------------------------------------
# 1. Diagram Occlusion Cards (Mermaid + Markdown figures)
# ---------------------------------------------------------------------------

_GENERIC_NODE_LABELS = {
    "start", "end", "begin", "done", "exit", "stop", "init", "input", "output",
    "true", "false", "none", "null", "step", "next", "prev", "main", "loop",
}

_FENCE_OPEN_RE = re.compile(r"^\s*```([a-zA-Z0-9_-]*)\s*$")
_FENCE_CLOSE_RE = re.compile(r"^\s*```\s*$")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.*\S)\s*$")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\r\n]+)\)")

# Mermaid node definition shapes in priority order (most specific delimiters first).
_MERMAID_NODE_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r'(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_-]*)\(\("([^"\n]+)"\)\)'), '((', '))'),
    (re.compile(r'(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_-]*)\(\(([^()\n]+)\)\)'), '((', '))'),
    (re.compile(r'(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_-]*)\["([^"\n]+)"\]'), '[', ']'),
    (re.compile(r'(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_-]*)\[([^\]\n]+)\]'), '[', ']'),
    (re.compile(r'(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_-]*)\("([^"\n]+)"\)'), '(', ')'),
    (re.compile(r'(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_-]*)\(([^()\n]+)\)'), '(', ')'),
    (re.compile(r'(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_-]*)\{"([^"\n]+)"\}'), '{', '}'),
    (re.compile(r'(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_-]*)\{([^}\n]+)\}'), '{', '}'),
]

_MERMAID_RESERVED_IDS = {
    "graph", "flowchart", "subgraph", "end", "style", "classdef", "class",
    "click", "linkstyle", "direction", "sequencediagram", "participant", "actor",
}

_SEQ_PARTICIPANT_RE = re.compile(
    r"^(\s*(?:participant|actor)\s+[A-Za-z0-9_-]+\s+as\s+)(.+?)\s*$"
)
_SEQ_MESSAGE_RE = re.compile(
    r"^(\s*[A-Za-z0-9_-]+\s*-{1,2}>{1,2}[+-]?\s*[A-Za-z0-9_-]+\s*:\s*)(.+?)\s*$"
)


@dataclass
class DiagramOcclusionCard:
    """Occlusion or explanation card extracted deterministically from a diagram."""

    id: str
    kind: str  # "mermaid" | "figure"
    title: str
    prompt: str
    source_title: str = ""
    source_url: Optional[str] = None
    concept_id: Optional[str] = None
    original_mermaid: Optional[str] = None
    occluded_mermaid: Optional[str] = None
    answer_key: dict[str, str] = field(default_factory=dict)
    distractors: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)
    image_url: Optional[str] = None
    caption: Optional[str] = None
    card_type: str = "diagram_occlusion"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_high_info_label(label: str) -> bool:
    cleaned = label.strip().strip("\"'").strip()
    if len(cleaned) < 4:
        return False
    if cleaned.lower() in _GENERIC_NODE_LABELS:
        return False
    if not re.search(r"[A-Za-z]{2}", cleaned):
        return False
    return True


def _label_richness(label: str) -> tuple[int, int]:
    words = len(label.split())
    return (min(words, 4), len(label))


@dataclass
class _MermaidCandidate:
    start: int
    end: int
    node_id: str
    label: str
    left_delim: str
    right_delim: str
    is_sequence_line: bool = False
    prefix: str = ""


def _parse_flowchart_candidates(mermaid_text: str) -> list[_MermaidCandidate]:
    candidates: list[_MermaidCandidate] = []
    occupied: list[tuple[int, int]] = []
    seen_nodes: set[str] = set()

    def _overlaps(s: int, e: int) -> bool:
        return any(not (e <= os or s >= oe) for os, oe in occupied)

    for pattern, ldelim, rdelim in _MERMAID_NODE_PATTERNS:
        for m in pattern.finditer(mermaid_text):
            s, e = m.span()
            if _overlaps(s, e):
                continue
            node_id = m.group(1)
            if node_id.lower() in _MERMAID_RESERVED_IDS:
                continue
            raw_label = m.group(2).strip()
            occupied.append((s, e))
            if node_id in seen_nodes:
                continue
            seen_nodes.add(node_id)
            candidates.append(
                _MermaidCandidate(
                    start=s,
                    end=e,
                    node_id=node_id,
                    label=raw_label,
                    left_delim=ldelim,
                    right_delim=rdelim,
                )
            )
    candidates.sort(key=lambda c: c.start)
    return candidates


def _parse_sequence_candidates(mermaid_text: str) -> list[_MermaidCandidate]:
    candidates: list[_MermaidCandidate] = []
    offset = 0
    for idx, line in enumerate(mermaid_text.splitlines(keepends=True)):
        stripped = line.rstrip("\r\n")
        m_part = _SEQ_PARTICIPANT_RE.match(stripped)
        m_msg = _SEQ_MESSAGE_RE.match(stripped) if not m_part else None
        m = m_part or m_msg
        if m:
            prefix = m.group(1)
            label = m.group(2).strip()
            candidates.append(
                _MermaidCandidate(
                    start=offset,
                    end=offset + len(stripped),
                    node_id=f"seq_{idx}",
                    label=label,
                    left_delim="",
                    right_delim="",
                    is_sequence_line=True,
                    prefix=prefix,
                )
            )
        offset += len(line)
    return candidates


def _build_mermaid_card(
    mermaid_text: str,
    *,
    title: str,
    source_title: str,
    safe_source_url: Optional[str],
    concept_id: Optional[str],
) -> Optional[DiagramOcclusionCard]:
    stripped = mermaid_text.strip()
    if not stripped:
        return None
    first_line = stripped.splitlines()[0].strip().lower()
    is_sequence = first_line.startswith("sequencediagram")
    is_flowchart = first_line.startswith(("flowchart", "graph"))
    if not (is_sequence or is_flowchart):
        return None

    all_candidates = (
        _parse_sequence_candidates(stripped)
        if is_sequence
        else _parse_flowchart_candidates(stripped)
    )
    high_info = [c for c in all_candidates if _is_high_info_label(c.label)]
    if not high_info:
        return None

    # Deduplicate labels while keeping appearance order.
    unique_high: list[_MermaidCandidate] = []
    seen_labels: set[str] = set()
    for c in high_info:
        key = c.label.lower()
        if key not in seen_labels:
            seen_labels.add(key)
            unique_high.append(c)

    if len(unique_high) == 1:
        num_slots = 1
    elif len(unique_high) <= 3:
        num_slots = min(2, len(unique_high) - 1) if len(unique_high) >= 2 else 1
    else:
        num_slots = min(3, len(unique_high) - 2)

    ranked = sorted(
        enumerate(unique_high),
        key=lambda pair: (-_label_richness(pair[1].label)[0], -_label_richness(pair[1].label)[1], pair[0]),
    )
    chosen_indices = {idx for idx, _ in ranked[:num_slots]}
    chosen = [c for idx, c in enumerate(unique_high) if idx in chosen_indices]

    # Assign slots in top-to-bottom appearance order.
    slot_for_start: dict[int, str] = {}
    answer_key: dict[str, str] = {}
    for slot_num, cand in enumerate(chosen, start=1):
        slot_name = f"SLOT_{slot_num}"
        slot_for_start[cand.start] = slot_name
        answer_key[slot_name] = cand.label

    # Reconstruct occluded Mermaid text cleanly from end to start.
    pieces: list[str] = []
    cursor = 0
    for cand in sorted(chosen, key=lambda c: c.start):
        slot_name = slot_for_start[cand.start]
        pieces.append(stripped[cursor:cand.start])
        if cand.is_sequence_line:
            pieces.append(f"{cand.prefix}[{slot_name}]")
        else:
            pieces.append(f'{cand.node_id}{cand.left_delim}"[{slot_name}]"{cand.right_delim}')
        cursor = cand.end
    pieces.append(stripped[cursor:])
    occluded_mermaid = "".join(pieces)

    answer_values_lower = {v.lower() for v in answer_key.values()}
    distractors: list[str] = []
    seen_dist: set[str] = set(answer_values_lower)
    for cand in all_candidates:
        lbl = cand.label.strip().strip("\"'")
        low = lbl.lower()
        if low in seen_dist or not _is_high_info_label(lbl):
            continue
        seen_dist.add(low)
        distractors.append(lbl)

    options = list(answer_key.values()) + distractors
    slots_desc = ", ".join(f"[{k}]" for k in answer_key)
    prompt = (
        f"Recall the occluded component(s) ({slots_desc}) in this {title or 'architecture'} diagram."
    )
    return DiagramOcclusionCard(
        id=_short_id("diag", f"{source_title}:{stripped}"),
        kind="mermaid",
        title=title or source_title or "Architecture Diagram",
        prompt=prompt,
        source_title=source_title,
        source_url=safe_source_url,
        concept_id=concept_id,
        original_mermaid=stripped,
        occluded_mermaid=occluded_mermaid,
        answer_key=answer_key,
        distractors=distractors,
        options=options,
    )


def _strip_optional_md_title(raw_target: str) -> str:
    """Extract URL from markdown link target ``url`` or ``url "title"``."""
    s = raw_target.strip()
    if s.startswith("<") and ">" in s:
        end_idx = s.index(">")
        return s[1:end_idx]
    m = re.match(r'^(.+?)\s+(?:"[^"]*"|\'[^\']*\')\s*$', s)
    if m:
        return m.group(1)
    return s


def extract_diagram_cards_from_markdown(
    markdown_text: str,
    source_title: str = "",
    source_url: Optional[str] = None,
    concept_id: Optional[str] = None,
) -> list[DiagramOcclusionCard]:
    """Deterministically extract Mermaid occlusion cards and safe figure cards."""
    if not markdown_text or not markdown_text.strip():
        return []

    safe_source_url = source_url.strip() if is_safe_http_url(source_url) else None
    lines = markdown_text.replace("\r\n", "\n").split("\n")
    cards: list[DiagramOcclusionCard] = []
    current_heading = ""
    in_code = False
    code_lang = ""
    code_lines: list[str] = []
    seen_figure_urls: set[str] = set()

    for line in lines:
        if not in_code:
            h = _HEADING_RE.match(line)
            if h:
                current_heading = re.sub(r"^\d{1,2}[.)]\s+", "", h.group(1)).strip()

            f_open = _FENCE_OPEN_RE.match(line)
            if f_open:
                in_code = True
                code_lang = (f_open.group(1) or "").strip().lower()
                code_lines = []
                continue

            for m_img in _IMAGE_RE.finditer(line):
                caption = " ".join(m_img.group(1).split()).strip()
                raw_url = _strip_optional_md_title(m_img.group(2))
                if len(caption) < 8:
                    continue
                if not is_safe_http_url(raw_url):
                    continue
                clean_url = raw_url.strip()
                if clean_url in seen_figure_urls:
                    continue
                seen_figure_urls.add(clean_url)
                card_title = current_heading or source_title or "Diagram Figure"
                cards.append(
                    DiagramOcclusionCard(
                        id=_short_id("fig", f"{clean_url}:{caption}"),
                        kind="figure",
                        title=card_title,
                        prompt=f"Explain the architecture and key takeaway shown in: {caption}",
                        source_title=source_title,
                        source_url=safe_source_url,
                        concept_id=concept_id,
                        answer_key={"takeaway": caption},
                        image_url=clean_url,
                        caption=caption,
                    )
                )
        else:
            if _FENCE_CLOSE_RE.match(line):
                if code_lang == "mermaid":
                    card = _build_mermaid_card(
                        "\n".join(code_lines),
                        title=current_heading or source_title or "Architecture Diagram",
                        source_title=source_title,
                        safe_source_url=safe_source_url,
                        concept_id=concept_id,
                    )
                    if card is not None:
                        cards.append(card)
                in_code = False
                code_lang = ""
                code_lines = []
            else:
                code_lines.append(line)

    return cards


# ---------------------------------------------------------------------------
# 2. Spot-The-Bug Cards
# ---------------------------------------------------------------------------

@dataclass
class SpotTheBugCard:
    """Interactive code debugging card with 1-based ``buggy_line_index``."""

    id: str
    title: str
    language: str
    lines: list[str]
    buggy_line_index: int  # 1-based within 1..len(lines)
    explanation: str
    fixed_line: str
    concept_name: str
    tags: list[str] = field(default_factory=list)
    card_type: str = "spot_the_bug"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


SPOT_THE_BUG_CARDS: list[SpotTheBugCard] = [
    SpotTheBugCard(
        id="bug-post-ann-filter",
        title="Post-ANN Multi-Tenant Filter Collapse",
        language="sql",
        lines=[
            "SELECT id, content",
            "FROM (",
            "  SELECT id, user_id, content, embedding <=> :query_vec AS dist",
            "  FROM note_chunks",
            "  ORDER BY embedding <=> :query_vec LIMIT 5",
            ") ann_hits",
            "WHERE user_id = :user_id;",
        ],
        buggy_line_index=5,
        explanation=(
            "Applying LIMIT 5 before WHERE user_id = :user_id executes a global ANN scan "
            "first; if the top 5 global hits belong to other tenants, the outer WHERE "
            "filters them all out and returns 0 results."
        ),
        fixed_line="  WHERE user_id = :user_id ORDER BY embedding <=> :query_vec LIMIT 5",
        concept_name="Multi-Tenant Vector Search",
        tags=["pgvector", "rag", "multi-tenant", "ann", "sql", "hnsw"],
    ),
    SpotTheBugCard(
        id="bug-data-leakage-scaler",
        title="Preprocessing Data Leakage Before Split",
        language="python",
        lines=[
            "from sklearn.model_selection import train_test_split",
            "from sklearn.preprocessing import StandardScaler",
            "X_scaled = StandardScaler().fit_transform(X)",
            "X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, test_size=0.2)",
            "clf = LogisticRegression(max_iter=500)",
            "clf.fit(X_train, y_train)",
            'print("Test accuracy:", clf.score(X_test, y_test))',
        ],
        buggy_line_index=3,
        explanation=(
            "Calling fit_transform(X) on the full dataset leaks test-set mean and variance "
            "into the training features, inflating offline evaluation metrics. Fit the "
            "scaler strictly on X_train and only call transform() on X_test."
        ),
        fixed_line=(
            "X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2); "
            "scaler = StandardScaler(); X_train = scaler.fit_transform(X_train); "
            "X_test = scaler.transform(X_test)"
        ),
        concept_name="Train-Test Split Data Leakage",
        tags=["ml", "data-leakage", "preprocessing", "scikit-learn", "evaluation"],
    ),
    SpotTheBugCard(
        id="bug-prompt-prefix-cache-bust",
        title="Prompt-Prefix KV Cache Bust",
        language="python",
        lines=[
            "def build_rag_messages(query: str, chunks: list[str], system_prompt: str) -> list[dict]:",
            '    context_block = "\\n".join(chunks)',
            '    system_content = f"<retrieved_context>\\n{context_block}\\n</retrieved_context>\\n{system_prompt}"',
            "    return [",
            '        {"role": "system", "content": system_content},',
            '        {"role": "user", "content": query},',
            "    ]",
        ],
        buggy_line_index=3,
        explanation=(
            "Placing dynamic per-query <retrieved_context> before the static system_prompt "
            "invalidates the prompt-prefix KV cache on every request. Always keep static "
            "instructions and tool schemas at the prefix and append dynamic context last."
        ),
        fixed_line=(
            '    system_content = f"{system_prompt}\\n<retrieved_context>\\n{context_block}\\n</retrieved_context>"'
        ),
        concept_name="Prompt Prefix Caching",
        tags=["llm", "kv-cache", "prompt-caching", "rag", "latency"],
    ),
    SpotTheBugCard(
        id="bug-semantic-cache-guard",
        title="Unguarded Semantic Cache Cross-Tenant / Entity Drift",
        language="python",
        lines=[
            "def lookup_semantic_cache(query: str, user_id: str, corpus_version: int) -> str | None:",
            "    q_vec = embed(query)",
            "    hit = cache_index.nearest(q_vec)",
            "    if hit and hit.cosine_sim >= 0.92:",
            "        return hit.cached_answer",
            "    return None",
        ],
        buggy_line_index=4,
        explanation=(
            "Matching solely on cosine_sim >= 0.92 leaks cached answers across tenants, "
            "serves stale answers after corpus edits, and collides on queries differing by "
            "critical entity/date/negation tokens (e.g. '2024' vs '2025')."
        ),
        fixed_line=(
            "    if hit and hit.user_id == user_id and hit.corpus_version == corpus_version "
            "and hit.cosine_sim >= 0.95 and entities_match(query, hit.query):"
        ),
        concept_name="Semantic Caching",
        tags=["rag", "semantic-cache", "multi-tenant", "caching", "embeddings"],
    ),
    SpotTheBugCard(
        id="bug-fsrs-null-due-flood",
        title="FSRS NULL Due-Date Review Queue Flood",
        language="sql",
        lines=[
            "SELECT f.id, f.front_content, f.back_content",
            "FROM flashcards f",
            "LEFT JOIN proficiency_scores p ON p.concept_id = f.concept_id AND p.user_id = f.user_id",
            "WHERE f.user_id = :user_id",
            "  AND (p.next_review_due IS NULL OR p.next_review_due <= NOW())",
            "ORDER BY p.next_review_due ASC NULLS FIRST",
            "LIMIT 50;",
        ],
        buggy_line_index=5,
        explanation=(
            "Treating p.next_review_due IS NULL identically to overdue reviews floods the "
            "review queue with every newly ingested unseen card ahead of genuinely due "
            "items. New cards must be budgeted via a separate daily_new_limit."
        ),
        fixed_line="  AND p.next_review_due IS NOT NULL AND p.next_review_due <= NOW()",
        concept_name="FSRS Spaced Repetition",
        tags=["fsrs", "spaced-repetition", "sql", "feed", "review-queue"],
    ),
    SpotTheBugCard(
        id="bug-retry-storm-429",
        title="Retry Storm Amplifying 429s and Retrying 400s",
        language="python",
        lines=[
            "def call_llm_with_retry(client, payload: dict) -> dict:",
            "    for attempt in range(5):",
            '        resp = client.post("/v1/generate", json=payload)',
            "        if resp.status_code == 200:",
            "            return resp.json()",
            "        time.sleep(1.0)",
            '    raise RuntimeError("LLM request failed")',
        ],
        buggy_line_index=6,
        explanation=(
            "A constant 1.0s sleep creates synchronized retry storms that worsen 429 rate "
            "limits, and blindly retrying non-429 4xx errors (like 400 Bad Request) wastes "
            "quota on deterministic client failures. Fail fast on non-429 4xx and use "
            "exponential backoff with jitter for 429/5xx."
        ),
        fixed_line=(
            "        if 400 <= resp.status_code < 500 and resp.status_code != 429: "
            "resp.raise_for_status(); "
            "time.sleep(min(30.0, (2 ** attempt) + random.uniform(0.0, 1.0)))"
        ),
        concept_name="API Retry and Backoff",
        tags=["reliability", "rate-limiting", "429", "backoff", "systems", "llm"],
    ),
    SpotTheBugCard(
        id="bug-binary-search-loop",
        title="Binary Search Upper-Bound Infinite Loop",
        language="python",
        lines=[
            "def upper_bound_last(nums: list[int], target: int) -> int:",
            "    lo, hi = 0, len(nums) - 1",
            "    while lo < hi:",
            "        mid = (lo + hi) // 2",
            "        if nums[mid] <= target:",
            "            lo = mid",
            "        else:",
            "            hi = mid - 1",
            "    return lo",
        ],
        buggy_line_index=4,
        explanation=(
            "Using floor midpoint (lo + hi) // 2 together with lo = mid stalls forever "
            "whenever hi == lo + 1 and nums[mid] <= target because mid equals lo. Pair "
            "lo = mid with upper midpoint (lo + hi + 1) // 2 so the search range shrinks."
        ),
        fixed_line="        mid = (lo + hi + 1) // 2",
        concept_name="Binary Search",
        tags=["leetcode", "algorithms", "binary-search", "loop-invariant"],
    ),
    SpotTheBugCard(
        id="bug-softmax-overflow",
        title="Softmax Numerical Overflow Without Max Subtraction",
        language="python",
        lines=[
            "import numpy as np",
            "def softmax(logits: np.ndarray) -> np.ndarray:",
            "    exp_vals = np.exp(logits)",
            "    probs = exp_vals / np.sum(exp_vals, axis=-1, keepdims=True)",
            "    return probs",
            "# Unnormalized attention scores:",
            "weights = softmax(np.array([1000.0, 1001.0, 999.0]))",
        ],
        buggy_line_index=3,
        explanation=(
            "Exponentiating large logits directly (e.g. exp(1000)) overflows float64 to "
            "inf, turning exp_vals / sum into inf / inf = NaN. Subtracting max(logits) "
            "keeps exponents <= 0 without changing the resulting probability distribution."
        ),
        fixed_line="    exp_vals = np.exp(logits - np.max(logits, axis=-1, keepdims=True))",
        concept_name="Softmax Numerical Stability",
        tags=["ml", "deep-learning", "numerical-stability", "softmax", "attention"],
    ),
]


def select_spot_the_bug(
    concept_names: Iterable[str],
    exclude_ids: Optional[Iterable[str]] = None,
) -> Optional[SpotTheBugCard]:
    """Select the best matching ``SpotTheBugCard`` for ``concept_names``."""
    excluded = set(exclude_ids or [])
    pool = [c for c in SPOT_THE_BUG_CARDS if c.id not in excluded]
    if not pool:
        return None
    names = list(concept_names or [])
    if not names:
        return pool[0]
    best = max(
        pool,
        key=lambda c: _match_score(names, title=c.title, concept_name=c.concept_name, tags=c.tags),
    )
    return best


def grade_spot_the_bug(card: SpotTheBugCard, selected_line: int) -> dict[str, Any]:
    """Grade a user's selected 1-based line against ``card.buggy_line_index``."""
    sel = int(selected_line)
    correct = sel == card.buggy_line_index
    return {
        "correct": correct,
        "selected_line": sel,
        "buggy_line_index": card.buggy_line_index,
        "explanation": card.explanation,
        "fixed_line": card.fixed_line,
        "evidence": {
            "signal_type": "quiz_correct" if correct else "quiz_wrong",
            "score": 0.85 if correct else 0.10,
            "concept_name": card.concept_name,
            "metadata": {
                "card_id": card.id,
                "card_type": card.card_type,
                "selected_line": sel,
                "buggy_line_index": card.buggy_line_index,
            },
        },
    }


# ---------------------------------------------------------------------------
# 3. Tradeoff Duel Cards
# ---------------------------------------------------------------------------

@dataclass
class TradeoffDuelCard:
    """System-design tradeoff comparison card between two concrete architectures."""

    id: str
    title: str
    scenario: str
    option_a: str
    option_b: str
    recommended: str  # "a" | "b" | "depends"
    winning_rationale: str
    when_other_wins: str
    concept_name: str
    tags: list[str] = field(default_factory=list)
    card_type: str = "tradeoff_duel"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


TRADEOFF_DUEL_CARDS: list[TradeoffDuelCard] = [
    TradeoffDuelCard(
        id="duel-pgvector-hnsw-vs-ivfflat",
        title="pgvector HNSW Iterative Scan vs IVFFlat",
        scenario=(
            "You run multi-tenant RAG in Postgres with per-user WHERE filters and "
            "continuous streaming note ingestions."
        ),
        option_a="pgvector HNSW with hnsw.iterative_scan",
        option_b="IVFFlat (lists=100)",
        recommended="a",
        winning_rationale=(
            "HNSW needs no k-means centroid training on a populated table and "
            "hnsw.iterative_scan keeps traversing graph neighbors until enough "
            "tenant-filtered rows satisfy LIMIT, avoiding post-filter recall collapse."
        ),
        when_other_wins=(
            "IVFFlat wins when RAM is tightly constrained, the corpus is mostly static "
            "or bulk-loaded, and faster index build times matter more than streaming recall."
        ),
        concept_name="Vector Indexing",
        tags=["pgvector", "hnsw", "ivfflat", "rag", "multi-tenant", "postgres"],
    ),
    TradeoffDuelCard(
        id="duel-redis-lua-vs-postgres-limiter",
        title="Redis Lua Sliding-Window Limiter vs Postgres Atomic Upsert",
        scenario=(
            "You need per-user API rate limiting and daily LLM quota enforcement across "
            "stateless backend workers."
        ),
        option_a="Redis Lua sliding-window limiter",
        option_b="Postgres atomic upsert limiter (INSERT ... ON CONFLICT DO UPDATE)",
        recommended="depends",
        winning_rationale=(
            "Redis Lua executes sub-millisecond atomic sliding windows without row-lock "
            "contention under high QPS, while Postgres atomic upserts eliminate an extra "
            "stateful dependency when traffic is moderate and quota must align with billing."
        ),
        when_other_wins=(
            "Choose Redis Lua above ~500 req/s or for strict burst smoothing; choose "
            "Postgres atomic upserts when zero-ops simplicity and ACID auditability win."
        ),
        concept_name="Rate Limiting",
        tags=["rate-limiting", "redis", "lua", "postgres", "systems", "quota"],
    ),
    TradeoffDuelCard(
        id="duel-cross-encoder-vs-rrf",
        title="Cross-Encoder Second-Stage Rerank vs RRF-Only Retrieval",
        scenario=(
            "Hybrid dense + BM25 search returns top-40 chunks for complex multi-hop "
            "technical questions in an interactive assistant."
        ),
        option_a="Cross-Encoder second-stage rerank over top-40 candidates",
        option_b="Reciprocal Rank Fusion (RRF) only",
        recommended="a",
        winning_rationale=(
            "A Cross-Encoder attends jointly across query and passage tokens, resolving "
            "negations, entity roles, and subtle phrasing mismatches that independent "
            "bi-encoder embeddings and rank-only RRF miss."
        ),
        when_other_wins=(
            "RRF-only wins when end-to-end retrieval latency must stay under ~25 ms or "
            "when GPU/reranker API budget and availability constraints preclude a second stage."
        ),
        concept_name="Hybrid Retrieval and Reranking",
        tags=["rag", "reranking", "cross-encoder", "rrf", "hybrid-search", "retrieval"],
    ),
    TradeoffDuelCard(
        id="duel-explicit-vs-implicit-prompt-cache",
        title="Explicit Gemini CachedContent vs Implicit Prompt-Prefix KV Caching",
        scenario=(
            "Your agent repeatedly answers questions over either a 100k-token reference "
            "textbook or evolving multi-turn conversation prefixes."
        ),
        option_a="Explicit Gemini CachedContent (pinned TTL handle)",
        option_b="Implicit Prompt-Prefix KV Caching",
        recommended="depends",
        winning_rationale=(
            "Explicit CachedContent guarantees pinned storage and predictable input-token "
            "discounts for huge static corpora (>32k tokens) shared across requests, "
            "whereas implicit KV caching works automatically with zero cache lifecycle code."
        ),
        when_other_wins=(
            "Explicit CachedContent wins for massive static books/system specs; implicit "
            "prefix caching wins for dynamic multi-turn chats and tool-calling loops."
        ),
        concept_name="LLM Prompt Caching",
        tags=["llm", "gemini", "prompt-caching", "kv-cache", "cost", "latency"],
    ),
    TradeoffDuelCard(
        id="duel-evidence-ledger-vs-mutable-score",
        title="Append-Only Evidence Ledger vs Single Mutable Mastery Score",
        scenario=(
            "You track user mastery across flashcards, coding problems, course grades, "
            "and self-ratings that decay at different half-lives."
        ),
        option_a="Append-only Evidence Ledger (concept_evidence / knowledge_evidence)",
        option_b="Single mutable mastery score column",
        recommended="a",
        winning_rationale=(
            "An append-only ledger preserves signal provenance, lets each evidence kind "
            "decay with its own half-life, prevents a single self-rating from overwriting "
            "tested mastery, and supports full recomputation when weights improve."
        ),
        when_other_wins=(
            "A single mutable score wins only for trivial counters or embedded devices "
            "where storage, auditability, and multi-source decay do not matter."
        ),
        concept_name="Knowledge Tracing and Mastery Modeling",
        tags=["knowledge-map", "fsrs", "postgres", "event-sourcing", "mastery"],
    ),
    TradeoffDuelCard(
        id="duel-wkwebview-vs-server-exec",
        title="On-Device WKWebView JS Sandbox vs Server-Side exec()",
        scenario=(
            "Your learning app renders interactive LLM-generated algorithm visualizers "
            "and user-editable code snippets inside iOS study cards."
        ),
        option_a="On-device WKWebView JS Sandbox (CSP + no host bridge)",
        option_b="Server-side Python exec() in backend API worker",
        recommended="a",
        winning_rationale=(
            "Running untrusted visualization code inside an isolated on-device WKWebView "
            "protects backend secrets, internal networks, and multi-tenant databases while "
            "delivering 60fps interactivity at zero server compute cost."
        ),
        when_other_wins=(
            "Server-side execution (in hardened ephemeral containers/microVMs, never raw "
            "exec() in the API process) wins when native Python/C++ toolchains or trusted "
            "deterministic grading is required."
        ),
        concept_name="Code Execution Sandboxing",
        tags=["security", "sandbox", "wkwebview", "ios", "exec", "systems"],
    ),
]


def select_tradeoff_duel(
    concept_names: Iterable[str],
    exclude_ids: Optional[Iterable[str]] = None,
) -> Optional[TradeoffDuelCard]:
    """Select the best matching ``TradeoffDuelCard`` for ``concept_names``."""
    excluded = set(exclude_ids or [])
    pool = [c for c in TRADEOFF_DUEL_CARDS if c.id not in excluded]
    if not pool:
        return None
    names = list(concept_names or [])
    if not names:
        return pool[0]
    return max(
        pool,
        key=lambda c: _match_score(
            names, title=c.title, concept_name=c.concept_name, tags=c.tags, extra=c.scenario
        ),
    )


# ---------------------------------------------------------------------------
# 4. Article Digest Pre-Processor ("Digest This")
# ---------------------------------------------------------------------------

_ACRONYM_STOP = {
    "THE", "AND", "FOR", "NOT", "BUT", "YOU", "ARE", "WITH", "FROM", "THIS",
    "THAT", "HAVE", "WILL", "CAN", "ALL", "NEW", "NOW", "ONE", "TWO", "USE",
    "HOW", "WHY", "WHAT", "WHEN", "WHO", "YES", "OUT", "OFF", "PER", "VIA",
    "HTTP", "HTTPS", "WWW", "COM", "ORG", "NET", "ETC", "FIG", "NOTE", "TODO",
}
_BOLD_TERM_RE = re.compile(r"\*\*([A-Za-z0-9][A-Za-z0-9 _/+.-]{1,48})\*\*")
_INLINE_CODE_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.:/-]{1,40})`")
_ACRONYM_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9})\b")
_BULLET_LINE_RE = re.compile(r"^\s*(?:[-*+•]|\d{1,2}[.)])\s+(.*\S)\s*$")


@dataclass
class DigestArticlePlan:
    """Bounded deterministic digest plan ready for ``agent_jobs`` or feed emission."""

    title: str
    source_url: Optional[str]
    diagram_cards: list[DiagramOcclusionCard] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    cards: list[dict[str, Any]] = field(default_factory=list)
    total_cards: int = 0
    max_cards: int = 8
    source_url_valid: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _extract_terms(title: str, markdown_text: str, claims: list[dict[str, Any]]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        cleaned = " ".join(term.split()).strip(" .:;,-")
        if not cleaned or len(cleaned) < 2 or len(cleaned) > 60:
            return
        if cleaned.upper() in _ACRONYM_STOP:
            return
        key = cleaned.lower()
        if key not in seen:
            seen.add(key)
            terms.append(cleaned)

    for claim in claims:
        if claim.get("anchor"):
            _add(str(claim["anchor"]))

    combined = f"{title}\n{markdown_text}"
    # Strip fenced code blocks before scanning prose bold/acronyms, but keep inline code.
    lines_no_fence: list[str] = []
    in_code = False
    for line in combined.replace("\r\n", "\n").split("\n"):
        if not in_code and _FENCE_OPEN_RE.match(line):
            in_code = True
            continue
        if in_code and _FENCE_CLOSE_RE.match(line):
            in_code = False
            continue
        if not in_code:
            lines_no_fence.append(line)
    prose = "\n".join(lines_no_fence)

    for m in _ACRONYM_RE.finditer(prose):
        _add(m.group(1))
    for m in _BOLD_TERM_RE.finditer(prose):
        if len(m.group(1).split()) <= 5:
            _add(m.group(1))
    for m in _INLINE_CODE_RE.finditer(prose):
        _add(m.group(1))

    return terms[:30]


def _extract_candidate_claims(markdown_text: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    seen_fronts: set[str] = set()

    for sc in extract_structure_cards(markdown_text):
        key = sc.front.lower()
        if key in seen_fronts:
            continue
        seen_fronts.add(key)
        claims.append(
            {
                "kind": sc.kind,
                "anchor": sc.anchor,
                "front": sc.front,
                "back": sc.back,
                "items": list(sc.items),
            }
        )

    # Also capture standalone informative bullet claims (>= 20 chars) not already covered.
    in_code = False
    current_heading = ""
    for line in (markdown_text or "").replace("\r\n", "\n").split("\n"):
        if not in_code and _FENCE_OPEN_RE.match(line):
            in_code = True
            continue
        if in_code and _FENCE_CLOSE_RE.match(line):
            in_code = False
            continue
        if in_code:
            continue
        h = _HEADING_RE.match(line)
        if h:
            current_heading = h.group(1).strip()
            continue
        bm = _BULLET_LINE_RE.match(line)
        if bm:
            body = re.sub(r"(\*\*|__|`)", "", bm.group(1)).strip()
            if len(body) >= 20 and ":" not in body[:45]:
                anchor = current_heading or "Key Point"
                front = f"{anchor}: {body[:120]}"
                if front.lower() not in seen_fronts and not any(
                    body in c.get("back", "") for c in claims
                ):
                    seen_fronts.add(front.lower())
                    claims.append(
                        {
                            "kind": "claim",
                            "anchor": anchor,
                            "front": front,
                            "back": body,
                            "items": [],
                        }
                    )
    return claims


def plan_article_digest(
    title: str,
    markdown_text: str,
    source_url: Optional[str] = None,
    max_cards: int = 8,
) -> DigestArticlePlan:
    """Pre-process an article deterministically into a bounded ``DigestArticlePlan``."""
    cap = max(0, int(max_cards))
    url_provided = source_url is not None and bool(str(source_url).strip())
    url_valid = is_safe_http_url(source_url) if url_provided else True
    safe_url = source_url.strip() if (url_provided and url_valid) else None

    all_diagrams = extract_diagram_cards_from_markdown(
        markdown_text,
        source_title=title,
        source_url=safe_url,
    )
    all_claims = _extract_candidate_claims(markdown_text)
    terms = _extract_terms(title, markdown_text, all_claims)

    # Bound total planned cards to <= max_cards (prioritize diagrams, then definition/list claims).
    bounded_diagrams = all_diagrams[:cap]
    remaining = max(0, cap - len(bounded_diagrams))
    bounded_claims = all_claims[:remaining]

    cards: list[dict[str, Any]] = [
        {"card_type": d.card_type, "kind": d.kind, "payload": d.as_dict()}
        for d in bounded_diagrams
    ] + [
        {"card_type": "structure_claim", "kind": c["kind"], "payload": c}
        for c in bounded_claims
    ]

    return DigestArticlePlan(
        title=(title or "").strip(),
        source_url=safe_url,
        diagram_cards=bounded_diagrams,
        claims=bounded_claims,
        terms=terms,
        cards=cards,
        total_cards=len(cards),
        max_cards=cap,
        source_url_valid=url_valid,
    )
