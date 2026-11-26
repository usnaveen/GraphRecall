"""
LangGraph Link Suggestion Workflow

Replaces direct Gemini calls with a LangGraph StateGraph pipeline.

Flow:
START → fetch_context → generate_links → END
"""

import json
from typing import Optional

import structlog
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict

from backend.config.llm import get_chat_model
from backend.db.neo4j_client import get_neo4j_client
from backend.services.concept_similarity import similar_to_embedding

logger = structlog.get_logger()

# How many nearby concepts the model gets to choose links from.
_CANDIDATE_LIMIT = 40
# Deliberately looser than the dedup threshold: a prerequisite is related to a
# concept without being the same idea, so cutting at 0.72 would hide exactly the
# links worth drawing.
_CANDIDATE_MIN_SCORE = 0.45
# Safe JSON character budget sent to the LLM (keeps payload valid JSON instead of slicing mid-string).
_MAX_PROMPT_CHARS = 14000


class LinkSuggestionState(TypedDict, total=False):
    """State for suggesting links between concepts."""

    node_id: str
    user_id: str
    node: dict
    candidates: list[dict]
    links: list[dict]
    error: Optional[str]


async def fetch_context_node(state: LinkSuggestionState) -> dict:
    """Load the target node and candidate concepts from Neo4j."""
    node_id = state.get("node_id")
    user_id = state.get("user_id")

    if not node_id or not user_id:
        return {"error": "Missing node_id or user_id"}

    try:
        neo4j = await get_neo4j_client()

        node_result = await neo4j.execute_query(
            "MATCH (c:Concept {id: $id, user_id: $user_id}) RETURN c",
            {"id": node_id, "user_id": user_id},
        )
        if not node_result:
            return {"error": "Node not found"}

        node = node_result[0]["c"]
        if hasattr(node, "_properties"):
            node = dict(node._properties)

        # Exclude already-connected neighbors so suggestions propose genuinely new links.
        neighbor_rows = await neo4j.execute_query(
            """
            MATCH (c:Concept {id: $id, user_id: $user_id})--(n:Concept {user_id: $user_id})
            RETURN DISTINCT n.id AS id
            """,
            {"id": node_id, "user_id": user_id},
        )
        exclude_ids = [node_id] + [
            r["id"] for r in (neighbor_rows or []) if r.get("id") and r["id"] != node_id
        ]

        # Candidates are the concepts nearest in meaning, not an arbitrary slice.
        vector_candidates = await similar_to_embedding(
            user_id,
            node.get("embedding") or [],
            limit=_CANDIDATE_LIMIT,
            min_score=_CANDIDATE_MIN_SCORE,
            min_margin=0.0,
            exclude_ids=exclude_ids,
        )

        # Reserve slots for domain/hub concepts (e.g. legacy nodes without embeddings
        # such as canonical hub concepts like "Machine Learning") and always check for
        # same-domain hubs even when vector search returned sparse or full hits.
        fallback_rows = await neo4j.execute_query(
            """
            MATCH (c:Concept {user_id: $user_id})
            WHERE NOT c.id IN $exclude_ids
            WITH c,
                 CASE WHEN toLower(coalesce(c.name, '')) = toLower(coalesce($domain, '')) THEN 2
                      WHEN coalesce(c.domain, '') = coalesce($domain, '') THEN 1
                      ELSE 0 END AS domain_rank,
                 COUNT { (c)--() } AS degree
            RETURN c.id AS id, c.name AS name, c.definition AS definition,
                   c.domain AS domain, domain_rank
            ORDER BY domain_rank DESC, degree DESC, c.created_at DESC
            LIMIT $limit
            """,
            {
                "user_id": user_id,
                "exclude_ids": exclude_ids,
                "domain": node.get("domain"),
                "limit": _CANDIDATE_LIMIT,
            },
        )

        domain_hubs = [r for r in (fallback_rows or []) if r.get("domain_rank") == 2]
        remaining_fallback = [r for r in (fallback_rows or []) if r.get("domain_rank") != 2]

        # Order: exact domain-name hub(s) first, then top vector matches (up to 25 if
        # we still have same-domain/high-degree fallback concepts to include), then
        # remaining domain/hub concepts up to _CANDIDATE_LIMIT.
        vec_cap = 25 if remaining_fallback else _CANDIDATE_LIMIT
        merged: list[dict] = []
        seen_ids: set[str] = set()

        def _append_unique(items: list[dict], cap: int) -> None:
            for item in items:
                if len(merged) >= cap:
                    break
                cid = item.get("id")
                if not cid or cid in seen_ids:
                    continue
                seen_ids.add(cid)
                merged.append(item)

        _append_unique(domain_hubs, _CANDIDATE_LIMIT)
        _append_unique(vector_candidates[:vec_cap], _CANDIDATE_LIMIT)
        _append_unique(remaining_fallback, _CANDIDATE_LIMIT)

        return {"node": node, "candidates": merged}

    except Exception as e:
        logger.error("LinkSuggestion: fetch_context failed", error=str(e))
        return {"error": str(e)}


async def generate_links_node(state: LinkSuggestionState) -> dict:
    """Use Gemini (via LangGraph) to suggest semantic links."""
    if state.get("error"):
        return {}

    node = state.get("node") or {}
    candidates = state.get("candidates") or []
    if not candidates:
        return {"links": []}

    llm = get_chat_model(temperature=0.2, json_mode=True)

    node_payload = {
        "id": node.get("id"),
        "name": node.get("name"),
        "definition": (node.get("definition") or "")[:300],
        "domain": node.get("domain", "General"),
    }
    base_len = len(json.dumps({"node": node_payload, "candidates": []}))
    running_len = base_len
    trimmed_candidates: list[dict] = []
    for c in candidates:
        entry = {
            "id": c.get("id"),
            "name": c.get("name"),
            "definition": (c.get("definition") or "")[:140],
            "domain": c.get("domain", "General"),
        }
        entry_len = len(json.dumps(entry)) + 2
        if running_len + entry_len > _MAX_PROMPT_CHARS and trimmed_candidates:
            break
        trimmed_candidates.append(entry)
        running_len += entry_len

    prompt = {
        "node": node_payload,
        "candidates": trimmed_candidates,
    }
    payload_json = json.dumps(prompt)
    system = (
        "You are a graph linking assistant. Given a node and candidate concepts, "
        "return up to 5 suggested links directed from `node` -> `target_id` with "
        "relationship_type and strength (0-1). "
        "Use relationship types:\n"
        "- SUBTOPIC_OF: `node` is a subtopic or branch of `target_id` "
        "(e.g., Supervised Learning SUBTOPIC_OF Machine Learning).\n"
        "- PART_OF: `node` is a component of `target_id`.\n"
        "- BUILDS_ON: `node` builds on `target_id`.\n"
        "- PREREQUISITE_OF: `node` is a prerequisite needed before learning `target_id`.\n"
        "- RELATED_TO: peer or closely related concept.\n"
        "Return JSON: {\"links\": [{\"target_id\": \"...\", \"relationship_type\": \"...\", "
        "\"strength\": 0.7, \"reason\": \"...\"}]}"
    )

    try:
        response = await llm.ainvoke(f"{system}\n\nData:\n{payload_json}")
        raw = response.text.strip()
        if raw.startswith("```json"):
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif raw.startswith("```"):
            raw = raw.split("```")[1].split("```")[0].strip()
        data = json.loads(raw)
    except Exception as e:
        logger.error("LinkSuggestion: LLM parsing failed", error=str(e))
        return {"links": []}

    links = data.get("links", []) if isinstance(data, dict) else []
    candidate_map = {c["id"]: c for c in candidates if c.get("id")}
    filtered = []
    for link in links:
        target_id = link.get("target_id")
        if not target_id or target_id not in candidate_map:
            continue
        relationship_type = str(link.get("relationship_type", "RELATED_TO")).upper().replace(" ", "_")
        try:
            strength = float(link.get("strength", 0.5))
        except (TypeError, ValueError):
            strength = 0.5
        strength = min(max(strength, 0.0), 1.0)
        filtered.append(
            {
                "target_id": target_id,
                "target_name": candidate_map[target_id].get("name"),
                "relationship_type": relationship_type,
                "strength": strength,
                "reason": link.get("reason"),
            }
        )

    return {"links": filtered[:5]}


link_suggestion_graph = StateGraph(LinkSuggestionState)
link_suggestion_graph.add_node("fetch_context", fetch_context_node)
link_suggestion_graph.add_node("generate_links", generate_links_node)
link_suggestion_graph.add_edge(START, "fetch_context")
link_suggestion_graph.add_edge("fetch_context", "generate_links")
link_suggestion_graph.add_edge("generate_links", END)
link_suggestion_graph = link_suggestion_graph.compile()


async def run_link_suggestions(node_id: str, user_id: str) -> dict:
    """Run the link suggestion graph and return results."""
    result = await link_suggestion_graph.ainvoke({"node_id": node_id, "user_id": user_id})
    return result
