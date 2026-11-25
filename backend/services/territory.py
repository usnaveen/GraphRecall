"""Map-the-territory cards: "Supervised learning — name its parts."

The answer key is the graph itself: a concept's SUBTOPIC_OF children (child -> parent edges).
This card only exists because GraphRecall has a graph. You list what you remember (typed or
dictated); we match each item to the children without an LLM, then reveal the ones you missed.

Matching, per child, first hit wins:
  1. normalised equality ("Support Vector Machines" == "support vector machine")
  2. acronym ("SVM" for "Support Vector Machines"; "RNN" for "Recurrent Neural Network")
  3. content-word containment (all of the child's content words appear in the item, or vice versa
     when the item has at least two content words)
  4. fuzzy ratio >= 0.82 (typos and dictation slips: "regresion", "k means")
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

MIN_CHILDREN = 3
MAX_CHILDREN = 12
FUZZY = 0.82

_STOP = {"the", "a", "an", "of", "and", "or", "for", "to", "in", "on", "with", "by", "its", "their", "is",
         "are", "learning"}  # "learning" is noise in ML names ("reinforcement learning" vs "reinforcement")
_SPLIT = re.compile(r"[,;\n•·]+|\s+(?:and|or|then|also|plus)\s+|\s*\d+[.)]\s+", re.I)

TERRITORY_QUERY = """
MATCH (child:Concept)-[:SUBTOPIC_OF]->(p:Concept)
WHERE p.user_id = $user_id AND child.user_id = $user_id
  AND coalesce(child.confidence, 0.8) >= 0.4
WITH p, collect(DISTINCT {id: child.id, name: child.name, definition: child.definition}) AS children
WHERE size(children) >= $min_children
RETURN p.id AS id, p.name AS name, p.definition AS definition, p.domain AS domain,
       children[..$max_children] AS children, size(children) AS total
ORDER BY total DESC
LIMIT $limit
"""

ONE_TERRITORY_QUERY = """
MATCH (p:Concept {id: $concept_id, user_id: $user_id})
OPTIONAL MATCH (child:Concept)-[:SUBTOPIC_OF]->(p)
WHERE child.user_id = $user_id AND coalesce(child.confidence, 0.8) >= 0.4
WITH p, collect(DISTINCT {id: child.id, name: child.name, definition: child.definition}) AS children
RETURN p.id AS id, p.name AS name, p.definition AS definition, p.domain AS domain,
       children[..$max_children] AS children, size(children) AS total
"""


def _norm(text: str) -> str:
    text = re.sub(r"\(.*?\)", " ", text.lower())
    text = re.sub(r"[^a-z0-9+#]+", " ", text)
    words = [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in text.split()]
    return " ".join(words)


def _content_words(text: str) -> set[str]:
    return {w for w in _norm(text).split() if w not in _STOP}


def _acronym(text: str) -> str:
    words = [w for w in re.sub(r"\(.*?\)", " ", text).replace("-", " ").split() if w.lower() not in _STOP]
    return "".join(w[0] for w in words if w[0].isalnum()).lower()


def split_answer(answer: str) -> list[str]:
    items = [i.strip(" .:-") for i in _SPLIT.split(answer or "")]
    return [i for i in items if i and len(i) <= 120]


def _matches(item: str, child: str) -> bool:
    ni, nc = _norm(item), _norm(child)
    if not ni or not nc:
        return False
    if ni == nc:
        return True
    explicit = re.findall(r"\(([A-Za-z0-9-]{2,8})\)", child)  # "Support Vector Machine (SVM)"
    compact_item = ni.replace(" ", "")
    if compact_item in {a.lower() for a in explicit}:
        return True
    acro = _acronym(child)
    if len(acro) >= 2 and compact_item in {acro, acro + "s"}:
        return True
    wi, wc = _content_words(item), _content_words(child)
    if wc and wc <= wi:
        return True
    if len(wi) >= 2 and wi <= wc:
        return True
    return SequenceMatcher(None, ni, nc).ratio() >= FUZZY


@dataclass
class TerritoryGrade:
    matched: list[dict] = field(default_factory=list)   # children you named: {id, name, said}
    missed: list[dict] = field(default_factory=list)    # children you didn't
    extras: list[str] = field(default_factory=list)     # things you said that aren't children
    score: float = 0.0
    suggested: str = "again"                            # feed difficulty to pre-position the slider


def grade(children: list[dict], answer: str) -> TerritoryGrade:
    items = split_answer(answer)
    used: set[int] = set()
    result = TerritoryGrade()
    for child in children:
        hit = next((k for k, item in enumerate(items) if k not in used and _matches(item, child["name"])), None)
        if hit is None:
            result.missed.append({"id": child.get("id"), "name": child["name"]})
        else:
            used.add(hit)
            result.matched.append({"id": child.get("id"), "name": child["name"], "said": items[hit]})
    result.extras = [item for k, item in enumerate(items) if k not in used]
    total = len(children)
    result.score = round(len(result.matched) / total, 3) if total else 0.0
    s = result.score
    result.suggested = "easy" if s >= 0.85 else "good" if s >= 0.6 else "hard" if s >= 0.3 else "again"
    return result


def card_content(territory: dict) -> dict:
    """Feed-card payload. Children ship with the card so grading can also run offline on device."""
    children = [c for c in territory.get("children") or [] if c.get("name")]
    return {
        "prompt": f"{territory['name']}: name its parts",
        "parent": territory["name"],
        "parent_definition": (territory.get("definition") or "")[:280],
        "count": len(children),
        "children": [{"id": c.get("id"), "name": c["name"],
                      "definition": (c.get("definition") or "")[:200]} for c in children],
        "hint": f"{len(children)} subtopics in your graph",
    }


async def territories(neo4j, user_id: str, limit: int = 5) -> list[dict]:
    rows = await neo4j.execute_query(TERRITORY_QUERY, {
        "user_id": user_id, "min_children": MIN_CHILDREN, "max_children": MAX_CHILDREN, "limit": limit})
    return [dict(r) for r in rows or []]


async def territory(neo4j, user_id: str, concept_id: str) -> Optional[dict]:
    rows = await neo4j.execute_query(ONE_TERRITORY_QUERY, {
        "user_id": user_id, "concept_id": concept_id, "max_children": MAX_CHILDREN})
    return dict(rows[0]) if rows else None
