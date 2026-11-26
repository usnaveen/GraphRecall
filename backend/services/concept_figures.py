"""Pick a figure from the user's own sources for a concept card.

A figure is used only when its caption is about the concept, because a wrong picture is worse than
none. Only the part of a caption that says what the figure shows counts: its first sentence, the
next one when the first is just a title ("New model architectures. The Skip-gram predicts ..."),
and panel descriptions ("(right) Multi-Head Attention consists of ..."). Later sentences add
conditions and contrasts ("... difficult to capture with a bag-of-words model"), which name things
the figure does not show. A match is scored by how much of its sentence the name takes up, and the
best-scoring figure wins:

- a multi-word name ("Multi-Head Attention") counts if it fills at least 8% of the sentence's words;
- a one-word name ("Softmax", "Transformer") counts only in the caption's first sentence, and only
  when that sentence has at most eight words ("The Transformer - model architecture"). One word
  in a long title ("Accuracy on the analogy task as function of ...") names what was measured,
  not what the figure explains.

Short all-caps acronyms match case-sensitively, so "GRU" never hits a lowercase "gru".
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

import structlog

from backend.models.feed_schemas import FeedItemType

logger = structlog.get_logger()

# Cards that teach the concept show the figure. Quiz-style cards (term, MCQ, fill-in) show it only
# after reveal, which the client decides; territory and code cards never get one (the figure could
# give the answer away, or has nothing to do with the code).
FIGURE_CARD_TYPES = {
    FeedItemType.CONCEPT_SHOWCASE,
    FeedItemType.TERM_CARD,
    FeedItemType.MCQ,
    FeedItemType.FILL_BLANK,
}

_TOKEN_SPLIT = re.compile(r"[\s\-_/]+")
_WORD = re.compile(r"\w+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.;:])\s+")
_MAX_SINGLE_WORD_TITLE = 8
_TITLE_ONLY_WORDS = 6
_PANEL = re.compile(r"^\((?:left|right|top|bottom|middle|centre|center|[a-h]|[ivx]{1,4})\)", re.IGNORECASE)
_MIN_MULTI_WORD_SHARE = 0.08


def _name_pattern(name: str) -> Optional[re.Pattern[str]]:
    name = (name or "").strip()
    tokens = [t for t in _TOKEN_SPLIT.split(name) if t]
    if not tokens:
        return None
    joined = r"[\s\-]+".join(re.escape(t) for t in tokens)
    acronym = len(tokens) == 1 and name.isupper() and 2 <= len(name) <= 6
    if not acronym and len(name) < 3:
        return None
    flags = 0 if acronym else re.IGNORECASE
    return re.compile(rf"(?<![A-Za-z0-9]){joined}(?:s|es)?(?![A-Za-z0-9])", flags)


def _match_share(pattern: re.Pattern[str], name_words: int, caption: str, single_word: bool) -> float:
    """Share of the best matching sentence's words that the name fills, or 0.0 for no usable match."""
    sentences = [x for x in _SENTENCE_SPLIT.split(caption.strip()) if x]
    if single_word:
        sentences = sentences[:1]
    elif sentences:
        lead = sentences[:2] if len(_WORD.findall(sentences[0])) <= _TITLE_ONLY_WORDS else sentences[:1]
        sentences = lead + [x for x in sentences[len(lead):] if _PANEL.match(x)]
    best = 0.0
    for sentence in sentences:
        if not pattern.search(sentence):
            continue
        words = len(_WORD.findall(sentence))
        if single_word and words > _MAX_SINGLE_WORD_TITLE:
            continue
        best = max(best, name_words / max(words, 1))
    if not single_word and best < _MIN_MULTI_WORD_SHARE:
        return 0.0
    return best


def best_figure(name: str, figures: Iterable[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """The figure whose caption is most about `name`, or None when none clearly is."""
    pattern = _name_pattern(name)
    if pattern is None:
        return None
    single_word = len([t for t in _TOKEN_SPLIT.split(name.strip()) if t]) == 1
    name_words = max(len(_WORD.findall(name)), 1)
    best: Optional[tuple[tuple, dict[str, Any]]] = None
    for fig in figures:
        caption = fig.get("caption") or ""
        share = _match_share(pattern, name_words, caption, single_word)
        if share <= 0.0:
            continue
        # Most about the name first; then the shorter (more specific) caption; then earlier pages.
        key = (-share, len(caption), int(fig.get("page") or 0))
        if best is None or key < best[0]:
            best = (key, fig)
    return best[1] if best else None


def figure_payload(fig: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(fig["id"]),
        "url": f"/api/figures/{fig['id']}",
        "label": fig.get("label") or "",
        "caption": fig.get("caption") or "",
        "source_title": fig.get("source_title") or "",
        "page": int(fig.get("page") or 0),
        "width": int(fig.get("width") or 0),
        "height": int(fig.get("height") or 0),
    }


async def load_figure_index(pg_client, user_id: str) -> list[dict[str, Any]]:
    """Every figure the user has, without the image bytes (a few hundred small rows at most)."""
    return await pg_client.execute_query(
        """
        SELECT f.id, f.page, f.label, f.caption, f.width, f.height, n.title AS source_title
        FROM source_figures f JOIN notes n ON n.id = f.note_id
        WHERE f.user_id = CAST(:u AS uuid)
        ORDER BY n.created_at, f.page
        """,
        {"u": user_id},
    )


async def attach_concept_figures(items: list, user_id: str, pg_client) -> int:
    """Set content["figure"] on concept cards whose concept a stored figure names. Returns the count.

    Never raises: a missing table (migration 033 not applied) or a query error leaves the cards
    exactly as they were.
    """
    wanted = [it for it in items if getattr(it, "item_type", None) in FIGURE_CARD_TYPES and getattr(it, "concept_name", None)]
    if not wanted or pg_client is None:
        return 0
    try:
        figures = await load_figure_index(pg_client, user_id)
    except Exception as e:  # noqa: BLE001
        logger.info("concept figures unavailable", error=str(e)[:200])
        return 0
    if not figures:
        return 0
    attached = 0
    cache: dict[str, Optional[dict[str, Any]]] = {}
    for item in wanted:
        if isinstance(item.content, dict) and item.content.get("figure"):
            continue
        key = item.concept_name.strip().lower()
        if key not in cache:
            cache[key] = best_figure(item.concept_name, figures)
        fig = cache[key]
        if fig is not None:
            item.content = {**(item.content or {}), "figure": figure_payload(fig)}
            attached += 1
    return attached
