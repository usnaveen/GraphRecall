"""Recall cards made from a note's own structure, with no LLM.

Handwritten and typed notes are mostly headings, bullet lists and "Term: definition" lines. That
structure already says what is worth recalling, so these cards hide it:

* list card:        "Supervised learning, 3 points: [___] [___] [___]" -> the bullets
* definition card:  "Overfitting: [___]" -> the definition

They use the same flashcards table and "[___]" cloze convention as the LLM cards, so the feed and
review flow need no changes. Because they need no model call, a note still gets cards when Gemini is
out of quota. Scanned pages go through Vision OCR first; OCR keeps line breaks and bullet glyphs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

BLANK = "[___]"
MAX_LIST_ITEMS = 8
MIN_LIST_ITEMS = 2
MAX_ITEM_CHARS = 220
MAX_TERM_WORDS = 6
MIN_DEF_WORDS = 3
MAX_CARDS = 12

_BULLET = re.compile(r"^\s*(?:[-*+•·▪◦‣–]|\d{1,2}[.)]|[a-hA-H][.)])\s+(.*\S)\s*$")
_ORDERED = re.compile(r"^\s*\d{1,2}[.)]\s+")
_HEADING = re.compile(r"^\s*#{1,6}\s+(.*\S)\s*$")
# "**Term**: def", "Term: def", "Term - def", "Term — def", "Term = def"
_DEF = re.compile(
    r"^\s*(?:[-*+•]\s+)?(?:\*\*|__)?(?P<term>[A-Za-z0-9][^:=\n]{0,60}?)(?:\*\*|__)?\s*"
    r"(?::|\s[-–—=]\s|\s?=\s?)\s*(?P<def>\S.*\S)\s*$"
)
_NOT_TERM = re.compile(r"^(note|eg|e\.g|ie|i\.e|example|examples|see|source|ref|tip|todo|q|a|answer|question)$", re.I)


@dataclass
class StructureCard:
    kind: str  # "list" | "definition"
    front: str
    back: str
    anchor: str  # heading/term used to attach the card to a concept
    items: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    text = re.sub(r"(\*\*|__|`)", "", text)
    return " ".join(text.split()).strip(" .;")


def _lead_for(lines: list[str], start: int) -> Optional[str]:
    """The line introducing a list: a heading, or a non-bullet line ending in ':' just above it."""
    j = start - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if j < 0:
        return None
    line = lines[j]
    h = _HEADING.match(line)
    if h:
        return _clean(h.group(1))
    s = line.strip()
    if not _BULLET.match(line) and s.endswith(":") and len(s.split()) <= 14:
        return _clean(s[:-1])
    return None


def _definition(line: str) -> Optional[tuple[str, str]]:
    if _HEADING.match(line):
        return None
    m = _DEF.match(line)
    if not m:
        return None
    term, definition = _clean(m.group("term")), _clean(m.group("def"))
    words = term.split()
    if not words or len(words) > MAX_TERM_WORDS or _NOT_TERM.match(term.rstrip(".")):
        return None
    if len(definition.split()) < MIN_DEF_WORDS or definition.endswith(":"):
        return None
    if re.match(r"^(https?|www)\b", definition) or term.lower().startswith(("http", "www")):
        return None
    return term, definition


def extract_structure_cards(text: str, max_cards: int = MAX_CARDS) -> list[StructureCard]:
    lines = (text or "").replace("\r\n", "\n").split("\n")
    cards: list[StructureCard] = []
    seen: set[str] = set()
    in_code = False
    i = 0
    while i < len(lines) and len(cards) < max_cards:
        line = lines[i]
        if line.strip().startswith("```"):
            in_code = not in_code
            i += 1
            continue
        if in_code:
            i += 1
            continue

        if _BULLET.match(line):
            start = i
            items: list[str] = []
            ordered = bool(_ORDERED.match(line))
            indent = len(line) - len(line.lstrip())
            while i < len(lines):
                cur = lines[i]
                m = _BULLET.match(cur)
                if m and len(cur) - len(cur.lstrip()) <= indent + 1:
                    items.append(_clean(m.group(1)))
                    i += 1
                elif m or (cur.strip() and cur.startswith((" " * (indent + 2), "\t"))):
                    i += 1  # nested bullets / wrapped lines belong to the previous item
                else:
                    break
            lead = _lead_for(lines, start)
            items = [it for it in items if it and len(it) <= MAX_ITEM_CHARS]
            defs = [_definition(f"- {it}") for it in items]
            if lead and MIN_LIST_ITEMS <= len(items) <= MAX_LIST_ITEMS:
                key = f"list:{lead.lower()}"
                if key not in seen:
                    seen.add(key)
                    order = " (in order)" if ordered else ""
                    blanks = "\n".join(f"{n}. {BLANK}" if ordered else f"• {BLANK}"
                                       for n in range(1, len(items) + 1))
                    back = "\n".join(f"{n}. {it}" if ordered else f"• {it}"
                                     for n, it in enumerate(items, 1))
                    cards.append(StructureCard("list", f"{lead}: {len(items)} points{order}\n{blanks}", back,
                                               lead, items))
            # Bullets shaped like "Term: definition" also make definition cards.
            for d in defs:
                if d and len(cards) < max_cards:
                    _add_definition(cards, seen, *d)
            continue

        d = _definition(line)
        if d:
            _add_definition(cards, seen, *d)
        i += 1
    return cards


def _add_definition(cards: list[StructureCard], seen: set[str], term: str, definition: str) -> None:
    key = f"def:{term.lower()}"
    if key in seen:
        return
    seen.add(key)
    cards.append(StructureCard("definition", f"{term}: {BLANK}", definition, term))


def pick_concept_id(anchor: str, concepts: list[dict], fallback: Optional[str]) -> Optional[str]:
    """Attach a card to the concept whose name best matches its heading/term, else the fallback."""
    a = anchor.lower()
    best, best_len = None, 0
    for c in concepts:
        name = str(c.get("name") or "").strip().lower()
        cid = c.get("id")
        if not name or not cid:
            continue
        if name == a:
            return str(cid)
        if (name in a or a in name) and len(name) > best_len:
            best, best_len = str(cid), len(name)
    return best or fallback


async def save_structure_cards(
    pg,
    *,
    user_id: str,
    note_id: Optional[str],
    text: str,
    concepts: list[dict],
    fallback_concept_id: Optional[str],
    replace: bool = False,
) -> list[str]:
    """Extract and store structure cards for one note. Returns the new card ids.

    ``replace`` deletes this note's earlier structure cards first (regenerate). Otherwise a card whose
    front already exists for this note is skipped, so re-running is idempotent.
    """
    import uuid
    from datetime import datetime, timezone

    cards = extract_structure_cards(text)
    if not cards:
        return []
    note_ids = [note_id] if note_id else []
    existing: set[str] = set()
    if note_id:
        if replace:
            await pg.execute_update(
                "DELETE FROM flashcards WHERE user_id = :u AND source = 'structure' "
                "AND CAST(:n AS uuid) = ANY(source_note_ids)",
                {"u": user_id, "n": note_id},
            )
        else:
            rows = await pg.execute_query(
                "SELECT front_content FROM flashcards WHERE user_id = :u AND source = 'structure' "
                "AND CAST(:n AS uuid) = ANY(source_note_ids)",
                {"u": user_id, "n": note_id},
            )
            existing = {r.get("front_content") for r in rows or []}
    ids: list[str] = []
    for card in cards:
        if card.front in existing:
            continue
        concept_id = pick_concept_id(card.anchor, concepts, fallback_concept_id)
        if not concept_id:
            continue
        card_id = str(uuid.uuid4())
        await pg.execute_update(
            """
            INSERT INTO flashcards (id, user_id, concept_id, front_content, back_content,
                                    difficulty, source_note_ids, created_at, source)
            VALUES (:id, :user_id, :concept_id, :front, :back, :difficulty, :note_ids, :created_at, 'structure')
            """,
            {
                "id": card_id, "user_id": user_id, "concept_id": concept_id,
                "front": card.front, "back": card.back,
                "difficulty": 0.6 if card.kind == "list" else 0.5,
                "note_ids": note_ids, "created_at": datetime.now(timezone.utc),
            },
        )
        ids.append(card_id)
    return ids
