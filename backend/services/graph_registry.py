"""Graph registry: the set of named graphs a user's concepts are filed under.

A "graph" is the ``domain`` property on :Concept. Nothing else stores it, so the
registry is derived by reading the distinct domains back out of Neo4j.

The reason this module exists is drift. Extraction asks the LLM for a "Field/
subject area" per concept with no knowledge of what the user already has, so one
paper yields "Linear Algebra", the next "Mathematics" and a third "Math", and a
single subject ends up as three graphs that never connect. ``resolve_graph``
closes that loop: it shows the LLM the graphs that already exist and asks it to
reuse one unless the concept genuinely belongs somewhere new.
"""

from __future__ import annotations

import json
import re
from typing import Optional

import structlog

from backend.config.llm import get_fast_model
from backend.db.neo4j_client import get_neo4j_client

logger = structlog.get_logger()

DEFAULT_GRAPH = "General"

# A brand-new graph needs a name we can live with for years, so keep the shape
# tight: title case, no punctuation soup, short enough to sit in a tab.
_MAX_GRAPH_NAME_LEN = 48


def normalize_graph_name(name: Optional[str]) -> str:
    """Canonical spelling of a graph name: collapsed whitespace, title-ish case."""
    cleaned = re.sub(r"\s+", " ", (name or "").strip())
    if not cleaned:
        return DEFAULT_GRAPH
    cleaned = cleaned[:_MAX_GRAPH_NAME_LEN].strip()
    # Preserve deliberate acronyms (NLP, RL); title-case everything else.
    words = [w if w.isupper() and len(w) <= 5 else w.capitalize() for w in cleaned.split(" ")]
    return " ".join(words) or DEFAULT_GRAPH


async def list_graphs(user_id: str) -> list[dict]:
    """Every graph this user has, with how much is in it.

    Ordered by size so the switcher leads with the graphs they actually work in.
    """
    neo4j = await get_neo4j_client()
    rows = await neo4j.execute_query(
        """
        MATCH (c:Concept {user_id: $user_id})
        WITH coalesce(c.domain, $default) AS name, collect(c) AS concepts
        RETURN name,
               size(concepts) AS concept_count,
               reduce(s = 0.0, x IN concepts | s + coalesce(x.confidence, 0.0))
                 / size(concepts) AS avg_confidence
        ORDER BY concept_count DESC, name ASC
        """,
        {"user_id": user_id, "default": DEFAULT_GRAPH},
    )
    return [
        {
            "name": r["name"],
            "concept_count": r["concept_count"],
            "avg_confidence": round(float(r.get("avg_confidence") or 0.0), 3),
        }
        for r in rows
    ]


async def graph_names(user_id: str) -> list[str]:
    """Just the names, for prompting."""
    return [g["name"] for g in await list_graphs(user_id)]


def _match_existing(candidate: str, existing: list[str]) -> Optional[str]:
    """Exact match on normalized names, before spending an LLM call."""
    want = normalize_graph_name(candidate).lower()
    for name in existing:
        if normalize_graph_name(name).lower() == want:
            return name
    return None


async def resolve_graph(
    user_id: str,
    *,
    proposed: Optional[str] = None,
    concept_name: str = "",
    definition: str = "",
    existing: Optional[list[str]] = None,
) -> dict:
    """Decide which graph a concept belongs in, reusing an existing one where it fits.

    Returns ``{"graph": str, "created": bool, "reason": str}``. ``created`` is
    True when this is a graph the user did not already have, which callers can
    surface so a new subject appearing is visible rather than silent.

    Never raises: if the LLM is unavailable the proposed name (or ``General``)
    is used, because failing to file a concept is worse than filing it roughly.
    """
    names = existing if existing is not None else await graph_names(user_id)

    # Cheap paths first: an exact hit on what they already have, or nothing to
    # compare against at all.
    if proposed:
        hit = _match_existing(proposed, names)
        if hit:
            return {"graph": hit, "created": False, "reason": "exact match"}
    if not names:
        chosen = normalize_graph_name(proposed) if proposed else DEFAULT_GRAPH
        return {"graph": chosen, "created": chosen != DEFAULT_GRAPH, "reason": "first graph"}

    payload = {
        "concept": concept_name,
        "definition": (definition or "")[:400],
        "proposed_graph": proposed or None,
        "existing_graphs": names,
    }
    system = (
        "You file concepts into a user's knowledge graphs. Given a concept and the "
        "graphs that already exist, pick the ONE graph it belongs in.\n"
        "Strongly prefer reusing an existing graph: 'Linear Algebra' and 'Matrix "
        "Theory' are the same graph; 'Mathematics', 'Math' and 'Maths' are the same "
        "graph. Only invent a new graph when the concept is genuinely a different "
        "subject from every existing one.\n"
        "Graph names are broad subjects (Linear Algebra, Distributed Systems), never "
        "single topics (Eigenvectors, Raft).\n"
        'Return JSON: {"graph": "...", "is_new": false, "reason": "..."}'
    )

    try:
        llm = get_fast_model(temperature=0.0, json_mode=True)
        response = await llm.ainvoke(f"{system}\n\nData:\n{json.dumps(payload)}")
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            raw = raw[4:] if raw.startswith("json") else raw
            raw = raw.split("```")[0].strip()
        data = json.loads(raw)
    except Exception as e:
        logger.warning(
            "GraphRegistry: resolve failed, falling back",
            concept=concept_name,
            error=str(e),
        )
        fallback = normalize_graph_name(proposed) if proposed else DEFAULT_GRAPH
        hit = _match_existing(fallback, names)
        return {
            "graph": hit or fallback,
            "created": hit is None and fallback != DEFAULT_GRAPH,
            "reason": "llm unavailable",
        }

    chosen = normalize_graph_name(data.get("graph") if isinstance(data, dict) else None)
    reason = (data.get("reason") if isinstance(data, dict) else "") or ""

    # Trust the name over the LLM's is_new flag: if it matches something we
    # already have, it is not new no matter what the model claimed.
    hit = _match_existing(chosen, names)
    if hit:
        return {"graph": hit, "created": False, "reason": reason or "matched existing graph"}
    return {"graph": chosen, "created": True, "reason": reason or "new subject"}


async def rename_graph(user_id: str, old_name: str, new_name: str) -> int:
    """Move every concept in ``old_name`` to ``new_name``. Returns concepts moved.

    Merging is the same operation as renaming: point one graph's name at another
    that already exists and the two become one.
    """
    target = normalize_graph_name(new_name)
    neo4j = await get_neo4j_client()
    rows = await neo4j.execute_query(
        """
        MATCH (c:Concept {user_id: $user_id})
        WHERE coalesce(c.domain, $default) = $old
        SET c.domain = $new, c.updated_at = datetime()
        RETURN count(c) AS moved
        """,
        {
            "user_id": user_id,
            "old": old_name,
            "new": target,
            "default": DEFAULT_GRAPH,
        },
    )
    moved = rows[0]["moved"] if rows else 0
    logger.info("GraphRegistry: renamed graph", old=old_name, new=target, moved=moved)
    return moved
