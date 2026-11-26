"""A small picture of where a concept sits in the user's own knowledge graph, for feed cards.

Every concept card gets a visual. Most concepts have no figure from the user's sources
(concept_figures.py covers a few percent), but every concept has links in the graph, so the card
can always draw the concept with what it needs, what it unlocks, what it is part of and what it
contains. Read-only: one Neo4j query per feed, never raises.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

from backend.services.concept_figures import FIGURE_CARD_TYPES

logger = structlog.get_logger()

# How a relationship reads from the card's concept, by direction.
# (relation type, card concept is the start node) -> role of the neighbour
_ROLES: dict[tuple[str, bool], str] = {
    ("PREREQUISITE_OF", True): "unlocks",   # card concept is a prerequisite of the neighbour
    ("PREREQUISITE_OF", False): "needs",    # neighbour is a prerequisite of the card concept
    ("BUILDS_ON", True): "needs",           # card concept builds on the neighbour
    ("BUILDS_ON", False): "unlocks",
    ("SUBTOPIC_OF", True): "part_of",       # card concept is a subtopic of the neighbour
    ("SUBTOPIC_OF", False): "includes",
    ("PART_OF", True): "part_of",
    ("PART_OF", False): "includes",
}
# At most this many neighbours per role, and in total; typed links first, "related" fills up.
_ROLE_CAPS = {"part_of": 1, "needs": 2, "unlocks": 2, "includes": 2, "related": 3}
_MAX_NODES = 7
_ROLE_ORDER = ("part_of", "needs", "unlocks", "includes", "related")


def neighbour_role(rel_type: Optional[str], card_is_start: bool) -> str:
    return _ROLES.get(((rel_type or "").upper(), bool(card_is_start)), "related")


def build_concept_map(center: str, links: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """{"center": name, "nodes": [{"name", "role"}]} with typed links first, or None if no links."""
    by_role: dict[str, list[str]] = {r: [] for r in _ROLE_ORDER}
    seen = {center.strip().lower()}
    for link in links:
        name = (link.get("name") or "").strip()
        if not name or name.lower() in seen:
            continue
        role = neighbour_role(link.get("rel"), link.get("out"))
        if len(by_role[role]) >= _ROLE_CAPS[role]:
            continue
        seen.add(name.lower())
        by_role[role].append(name)
    nodes = [{"name": n, "role": r} for r in _ROLE_ORDER for n in by_role[r]][:_MAX_NODES]
    if not nodes:
        return None
    return {"center": center, "nodes": nodes}


_QUERY = """
UNWIND $ids AS cid
MATCH (c:Concept {id: cid, user_id: $uid})
OPTIONAL MATCH (c)-[r]-(n:Concept {user_id: $uid})
WITH c, r, n
ORDER BY CASE type(r)
  WHEN 'SUBTOPIC_OF' THEN 0 WHEN 'PREREQUISITE_OF' THEN 1 WHEN 'BUILDS_ON' THEN 2
  WHEN 'PART_OF' THEN 3 ELSE 4 END
WITH c, collect(CASE WHEN n IS NULL THEN NULL
                     ELSE {name: n.name, rel: type(r), out: startNode(r) = c} END)[0..40] AS links
RETURN c.id AS id, c.name AS name, links
"""


async def attach_concept_maps(items: list, user_id: str, neo4j_client) -> int:
    """Set content["concept_map"] on concept cards. Returns how many got one; never raises."""
    wanted = [it for it in items
              if getattr(it, "item_type", None) in FIGURE_CARD_TYPES and getattr(it, "concept_id", None)]
    if not wanted or neo4j_client is None:
        return 0
    ids = list(dict.fromkeys(str(it.concept_id) for it in wanted))
    try:
        rows = await neo4j_client.execute_query(_QUERY, {"ids": ids, "uid": user_id})
    except Exception as e:  # noqa: BLE001
        logger.info("concept maps unavailable", error=str(e)[:200])
        return 0
    maps: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        built = build_concept_map(row.get("name") or "", row.get("links") or [])
        if built:
            maps[str(row.get("id"))] = built
    attached = 0
    for item in wanted:
        m = maps.get(str(item.concept_id))
        if m is None or (isinstance(item.content, dict) and item.content.get("concept_map")):
            continue
        item.content = {**(item.content or {}), "concept_map": m}
        attached += 1
    return attached
