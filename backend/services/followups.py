"""Suggested next questions after a chat answer, chosen from the user's own knowledge graph.

Chat apps usually make a second model call after the answer ("suggest 3 follow-up questions").
Here the graph decides *what* to suggest, so it costs no tokens and every suggestion points at a
real gap in what this user knows. Around the concepts the question names (then the ones the
answer was grounded in):

- **prerequisite**: something the concept needs, preferring ones the user is shaky on or has
  never been tested on  ((p)-[:PREREQUISITE_OF]->(seed))
- **subtopic**: a part of the concept they haven't studied yet  ((c)-[:SUBTOPIC_OF]->(seed))
- **next**: what the concept unlocks  ((seed)-[:PREREQUISITE_OF]->(n))

Short templates phrase them. Mastery comes from the knowledge map (`knowledge_map.assess`), the same
evidence model the Profile uses. BUILDS_ON edges are skipped: there are few and their direction is
inconsistent in today's graphs.

Which suggestion gets tapped is logged on the user message (`meta_json.from_suggestion`), so the
click-through rate per kind can be measured.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import structlog

logger = structlog.get_logger()

MAX_SEEDS = 3
MAX_SUGGESTIONS = 3
TIMEOUT_S = 1.5

# Concepts the question names outright ("Explain Multi-Query Attention"), longest names first.
MENTIONED_QUERY = """
MATCH (c:Concept {user_id: $u})
WHERE size(c.name) >= 3 AND $q CONTAINS toLower(c.name)
RETURN c.id AS id, c.name AS name
ORDER BY size(c.name) DESC
LIMIT $limit
"""

NEIGHBOURS_QUERY = """
UNWIND $ids AS sid
MATCH (s:Concept {id: sid, user_id: $u})
OPTIONAL MATCH (p:Concept {user_id: $u})-[:PREREQUISITE_OF]->(s)
WITH s, collect(DISTINCT {id: p.id, name: p.name}) AS prereqs
OPTIONAL MATCH (c:Concept {user_id: $u})-[:SUBTOPIC_OF]->(s)
WITH s, prereqs, collect(DISTINCT {id: c.id, name: c.name}) AS subs
OPTIONAL MATCH (s)-[:PREREQUISITE_OF]->(n:Concept {user_id: $u})
RETURN s.id AS seed_id, s.name AS seed_name, prereqs, subs,
       collect(DISTINCT {id: n.id, name: n.name}) AS nexts
"""

# Lower is better. "unexposed" means in the graph but never tested; "seen" means studied, untested.
_PRIORITY = {
    "prerequisite": {"shaky": 0, "unexposed": 1, "seen": 2, "strong": 9},
    "subtopic": {"unexposed": 0, "seen": 1, "shaky": 1, "strong": 9},
    "next": {"unexposed": 0, "seen": 1, "shaky": 2, "strong": 3},
}

_REASON = {
    ("prerequisite", "shaky"): "A prerequisite you're shaky on",
    ("prerequisite", "unexposed"): "A prerequisite you haven't been tested on",
    ("prerequisite", "seen"): "A prerequisite",
    ("subtopic", "unexposed"): "A part you haven't studied",
    ("subtopic", "seen"): "A part you've only read about",
    ("subtopic", "shaky"): "A part you're shaky on",
}


def _phrase(kind: str, seed: str, other: str) -> str:
    # Worded to stay true when an extracted edge is loose ("needs" would overclaim).
    if kind == "prerequisite":
        return f"What role does {other} play in {seed}?"
    if kind == "subtopic":
        return f"How does {other} work in {seed}?"
    return f"How does {seed} show up in {other}?"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def pick(
    rows: list[dict],
    status_by_id: dict[str, str],
    question: str,
    *,
    limit: int = MAX_SUGGESTIONS,
) -> list[dict]:
    """Choose up to `limit` suggestions, at most one per kind first, from neighbour rows.

    Pure (no I/O) so the ranking is unit-tested. Skips concepts named in the question, the seeds
    themselves, and strong prerequisites/subtopics (nothing to learn there).
    """
    asked = _norm(question)
    seed_ids = {r.get("seed_id") for r in rows}
    candidates: list[tuple[int, int, int, dict]] = []
    for seed_rank, row in enumerate(rows):
        seed = row.get("seed_name") or ""
        for kind_rank, (kind, key) in enumerate((("prerequisite", "prereqs"), ("subtopic", "subs"), ("next", "nexts"))):
            for cand in row.get(key) or []:
                cid, name = cand.get("id"), cand.get("name")
                if not cid or not name or cid in seed_ids:
                    continue
                if _norm(name) and _norm(name) in asked:
                    continue
                status = status_by_id.get(cid, "unexposed")
                prio = _PRIORITY[kind].get(status, 5)
                if prio >= 9:
                    continue
                candidates.append((prio, seed_rank, kind_rank, {
                    "text": _phrase(kind, seed, name),
                    "kind": kind,
                    "concept_id": cid,
                    "concept_name": name,
                    "seed_name": seed,
                    "reason": _REASON.get((kind, status), "What this unlocks" if kind == "next" else "Related"),
                }))
    # Greedy: the question's own concept first, then by priority; one per kind, each concept once.
    candidates.sort(key=lambda t: (t[1], t[0], t[2]))
    out, kinds, used = [], set(), set()
    for _, _, _, s in candidates:
        if s["kind"] in kinds or s["concept_id"] in used:
            continue
        kinds.add(s["kind"])
        used.add(s["concept_id"])
        out.append(s)
        if len(out) == limit:
            break
    return out


async def _suggest(user_id: str, question: str, related_concepts: list[dict], neo4j, pg) -> list[dict]:
    from backend.services import knowledge_map

    # Seeds: what the question is about first, then what grounded the answer (retrieval order).
    mentioned = await neo4j.execute_query(
        MENTIONED_QUERY, {"u": user_id, "q": (question or "").lower(), "limit": MAX_SEEDS}
    ) or []
    seed_ids: list[str] = []
    for c in [*mentioned, *(related_concepts or [])]:
        cid = c.get("id") if isinstance(c, dict) else None
        if cid and cid not in seed_ids:
            seed_ids.append(cid)
    seed_ids = seed_ids[:MAX_SEEDS]
    if not seed_ids:
        return []
    rows = await neo4j.execute_query(NEIGHBOURS_QUERY, {"ids": seed_ids, "u": user_id})
    # Keep the answer's own ranking of seeds.
    order = {sid: i for i, sid in enumerate(seed_ids)}
    rows = sorted(rows or [], key=lambda r: order.get(r.get("seed_id"), 99))
    names = {c["name"] for r in rows for k in ("prereqs", "subs", "nexts") for c in (r.get(k) or []) if c.get("name")}
    if not names:
        return []
    assessed = await knowledge_map.assess(user_id, sorted(names), pg=pg, neo4j=neo4j, max_names=60)
    status_by_id = {a.concept_id: a.status for a in assessed if a.concept_id}
    return pick(rows, status_by_id, question)


async def suggest_followups(
    user_id: str,
    question: str,
    related_concepts: list[dict],
    *,
    neo4j: Any = None,
    pg: Any = None,
    timeout_s: float = TIMEOUT_S,
) -> list[dict]:
    """Up to three next questions grounded in the user's graph. Never raises; [] on any problem."""
    try:
        if neo4j is None:
            from backend.db.neo4j_client import get_neo4j_client
            neo4j = await get_neo4j_client()
        if pg is None:
            from backend.db.postgres_client import get_postgres_client
            pg = await get_postgres_client()
        return await asyncio.wait_for(_suggest(user_id, question, related_concepts, neo4j, pg), timeout_s)
    except Exception as e:  # suggestions are a nicety: never fail or slow down a chat turn
        logger.info("followups: skipped", error=str(e)[:200])
        return []


def suggestion_click_meta(from_suggestion: Optional[dict]) -> Optional[dict]:
    """The part of a tapped suggestion worth logging on the user message (for click-through rates)."""
    if not isinstance(from_suggestion, dict):
        return None
    kind = from_suggestion.get("kind")
    if kind not in _PRIORITY:
        return None
    cid = from_suggestion.get("concept_id")
    return {"kind": kind, "concept_id": cid if isinstance(cid, str) else None}
