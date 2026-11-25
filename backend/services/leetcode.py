"""LeetCode recall: turn a solved problem into cards that test the pattern, not the code.

Each logged problem becomes a Concept in the user's "Coding Interviews" graph, with its pattern as a
prerequisite (so a lapse on the problem backtracks to the pattern in the feed). Three card kinds, all
built from the user's own words with no LLM:

* pattern     "Longest Substring Without Repeating Characters: which pattern, and why?"
* pseudocode  the user's pseudocode with its key lines hidden: "[___]"
* mistake     one per logged mistake: "Last time you slipped here (off-by-one). What's the trap?"

Logging a failed attempt makes the problem due now, so the mistake comes back while it's fresh.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

GRAPH = "Coding Interviews"
BLANK = "[___]"
MAX_HIDDEN_LINES = 3

_TRIVIAL = re.compile(r"^\s*(?:def |function |class |}|\)|end\b|else:?$|pass$|#|//|$)", re.I)
_KEY = re.compile(r"\b(while|for|if|elif|return|push|pop|append|max|min|heap|swap|\+=|-=|=)\b|[<>]=?|=", re.I)

MISTAKE_TAGS = {
    "wrong_pattern": "picked the wrong pattern",
    "edge_case": "missed an edge case",
    "off_by_one": "off-by-one",
    "complexity": "too slow (complexity)",
    "bug": "implementation bug",
    "forgot": "couldn't recall the approach",
    "other": "other",
}


@dataclass
class Card:
    kind: str  # pattern | pseudocode | mistake
    front: str
    back: str


def _score_line(line: str) -> int:
    """How much a line carries the algorithm: control flow and state updates score highest."""
    s = line.strip()
    if _TRIVIAL.match(s):
        return -1
    return len(_KEY.findall(s)) * 10 + min(len(s), 60)


def pseudocode_cloze(pseudocode: str, max_hidden: int = MAX_HIDDEN_LINES) -> tuple[str, int]:
    """Hide the most informative lines (keeping indentation), first line kept as the anchor."""
    lines = (pseudocode or "").strip("\n").split("\n")
    if len(lines) < 3:
        return "", 0
    candidates = sorted(((i, _score_line(l)) for i, l in enumerate(lines) if i > 0),
                        key=lambda t: (-t[1], t[0]))
    hide = {i for i, score in candidates[:max_hidden] if score > 0}
    if not hide:
        return "", 0
    out = []
    for i, line in enumerate(lines):
        if i in hide:
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f"{indent}{BLANK}")
        else:
            out.append(line)
    return "\n".join(out), len(hide)


def build_cards(problem: dict, attempts: list[dict]) -> list[Card]:
    title = problem["title"].strip()
    cards: list[Card] = []
    pattern = (problem.get("pattern") or "").strip()
    insight = (problem.get("key_insight") or "").strip()
    complexity = (problem.get("complexity") or "").strip()
    if pattern or insight:
        back = "\n".join(x for x in (
            f"Pattern: {pattern}" if pattern else "",
            f"Key insight: {insight}" if insight else "",
            f"Complexity: {complexity}" if complexity else "",
        ) if x)
        cards.append(Card("pattern", f"{title}\nWhich pattern solves it, and what's the key insight?", back))
    cloze, hidden = pseudocode_cloze(problem.get("pseudocode") or "")
    if hidden:
        cards.append(Card("pseudocode", f"{title}: fill in the {hidden} missing lines\n{cloze}",
                          problem["pseudocode"].strip()))
    for a in attempts:
        mistake = (a.get("mistake") or "").strip()
        if not mistake:
            continue
        tag = MISTAKE_TAGS.get(a.get("mistake_tag") or "", "")
        label = f" ({tag})" if tag and tag != "other" else ""
        cards.append(Card("mistake", f"{title}\nLast time you slipped here{label}. What's the trap?", mistake))
    return cards


async def upsert_graph(neo4j, user_id: str, problem: dict) -> tuple[str, Optional[str]]:
    """MERGE the problem concept (and its pattern, as a prerequisite). Returns (problem_id, pattern_id)."""
    title = problem["title"].strip()
    pattern = (problem.get("pattern") or "").strip()
    parts = [f"Coding problem ({problem.get('difficulty') or 'unrated'})."]
    if pattern:
        parts.append(f"Pattern: {pattern}.")
    if problem.get("key_insight"):
        parts.append(f"Key insight: {problem['key_insight'].strip()}")
    definition = " ".join(parts)
    # Reuse a concept the user already has under this name (any capitalisation) and never overwrite
    # its definition: "LRU Cache" from a note keeps the note's definition.
    rows = await neo4j.execute_query(
        "MATCH (c:Concept {user_id: $user_id}) WHERE toLower(c.name) = toLower($name) "
        "SET c.definition = CASE WHEN c.source = 'leetcode' THEN $definition ELSE coalesce(c.definition, $definition) END, "
        "c.updated_at = datetime() "
        "RETURN c.id AS id ORDER BY coalesce(c.confidence, 0) DESC LIMIT 1",
        {"name": title, "user_id": user_id, "definition": definition},
    )
    if not rows:
        new_id = str(uuid.uuid4())
        await neo4j.execute_query(
            """
            CREATE (c:Concept {id: $id, user_id: $user_id, name: $name, domain: $graph, definition: $definition,
                               confidence: 1.0, complexity_score: 5.0, source: 'leetcode', created_at: datetime()})
            """,
            {"name": title, "user_id": user_id, "id": new_id, "graph": GRAPH, "definition": definition},
        )
        rows = [{"id": new_id}]
    problem_id = str(rows[0]["id"])
    pattern_id = None
    if pattern:
        found = await neo4j.execute_query(
            "MATCH (c:Concept {user_id: $user_id}) WHERE toLower(c.name) = toLower($pattern) "
            "RETURN c.id AS id ORDER BY coalesce(c.confidence, 0) DESC LIMIT 1",
            {"user_id": user_id, "pattern": pattern},
        )
        if found:
            pattern_id = str(found[0]["id"])
        else:
            pattern_id = str(uuid.uuid4())
            await neo4j.execute_query(
                """
                CREATE (n:Concept {id: $id, user_id: $user_id, name: $pattern, domain: $graph,
                                   definition: 'Problem-solving pattern for coding interviews.',
                                   confidence: 1.0, complexity_score: 5.0, source: 'leetcode',
                                   created_at: datetime()})
                """,
                {"id": pattern_id, "user_id": user_id, "pattern": pattern, "graph": GRAPH},
            )
        await neo4j.execute_query(
            """
            MATCH (pat:Concept {id: $pat_id, user_id: $user_id}), (p:Concept {id: $pid, user_id: $user_id})
            MERGE (pat)-[r:PREREQUISITE_OF]->(p)
            ON CREATE SET r.strength = 0.9, r.source = 'leetcode'
            """,
            {"pat_id": pattern_id, "pid": problem_id, "user_id": user_id},
        )
    return problem_id, pattern_id


async def ensure_scheduled(pg, user_id: str, concept_ids: list[str]) -> None:
    for cid in concept_ids:
        if cid:
            await pg.execute_update(
                "INSERT INTO proficiency_scores (user_id, concept_id, score) VALUES (CAST(:u AS uuid), :c, 0.10) "
                "ON CONFLICT (user_id, concept_id) DO NOTHING",
                {"u": user_id, "c": cid},
            )


async def make_due_now(pg, user_id: str, concept_id: str) -> None:
    await pg.execute_update(
        "UPDATE proficiency_scores SET next_review_due = :now, next_review = :now WHERE user_id = CAST(:u AS uuid) AND concept_id = :c",
        {"u": user_id, "c": concept_id, "now": datetime.now(timezone.utc)},
    )


async def rebuild_cards(pg, user_id: str, problem: dict, attempts: list[dict]) -> list[str]:
    """Replace this problem's generated cards. Flashcards keep their own review history per id, so
    unchanged cards keep their id: only cards whose text changed are replaced."""
    concept_id = problem["concept_id"]
    existing = await pg.execute_query(
        "SELECT id::text AS id, front_content, back_content FROM flashcards "
        "WHERE user_id = CAST(:u AS uuid) AND concept_id = :c AND source = 'leetcode'",
        {"u": user_id, "c": concept_id},
    )
    by_text = {(r["front_content"], r["back_content"]): r["id"] for r in existing or []}
    keep: list[str] = []
    for card in build_cards(problem, attempts):
        key = (card.front, card.back)
        if key in by_text:
            keep.append(by_text.pop(key))
            continue
        cid = str(uuid.uuid4())
        await pg.execute_update(
            """
            INSERT INTO flashcards (id, user_id, concept_id, front_content, back_content, difficulty,
                                    source_note_ids, created_at, source)
            VALUES (:id, CAST(:u AS uuid), :c, :front, :back, :d, '{}', :now, 'leetcode')
            """,
            {"id": cid, "u": user_id, "c": concept_id, "front": card.front, "back": card.back,
             "d": 0.7 if card.kind == "mistake" else 0.6, "now": datetime.now(timezone.utc)},
        )
        keep.append(cid)
    stale = list(by_text.values())
    if stale:
        await pg.execute_update(
            "DELETE FROM flashcards WHERE user_id = CAST(:u AS uuid) AND id::text = ANY(:ids)",
            {"u": user_id, "ids": stale},
        )
    return keep
