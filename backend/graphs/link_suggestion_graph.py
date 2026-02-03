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

logger = structlog.get_logger()


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

        candidates = await neo4j.execute_query(
            """
            MATCH (c:Concept {user_id: $user_id})
            WHERE c.id <> $id
            RETURN c.id AS id, c.name AS name, c.definition AS definition, c.domain AS domain
            LIMIT 60
            """,
            {"user_id": user_id, "id": node_id},
        )

        return {"node": node, "candidates": candidates}

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

    prompt = {
        "node": {
            "id": node.get("id"),
            "name": node.get("name"),
            "definition": node.get("definition", ""),
            "domain": node.get("domain", "General"),
        },
        "candidates": candidates,
    }
    system = (
        "You are a graph linking assistant. Given a node and candidate concepts, "
        "return up to 5 suggested links with relationship_type and strength (0-1). "
        "Use relationship types like RELATED_TO, PREREQUISITE_OF, DEPENDS_ON, EXPLAINS. "
        "Return JSON: {\"links\": [{\"target_id\": \"...\", \"relationship_type\": \"...\", "
        "\"strength\": 0.7, \"reason\": \"...\"}]}"
    )

    try:
        response = await llm.ainvoke(f"{system}\n\nData:\n{json.dumps(prompt)[:6000]}")
        raw = response.content.strip()
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
