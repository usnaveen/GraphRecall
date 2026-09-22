"""Nodes Router - Manual node creation and AI-assisted linking."""

from typing import Optional
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth.middleware import get_current_user
from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.graphs.link_suggestion_graph import run_link_suggestions
from backend.config.llm import get_fast_model
from backend.services.graph_registry import resolve_graph
from backend.services.ingestion.embedding_service import EmbeddingService

logger = structlog.get_logger()

router = APIRouter(prefix="/api/nodes", tags=["Nodes"])

# Links the model is confident about attach on their own; the rest come back for
# review. Dumping a concept should not stop to ask about every edge, but the
# graph should not fill with guesses either.
AUTO_LINK_THRESHOLD = 0.7

# A relationship type cannot be a bind parameter in Cypher — it is interpolated
# into the query text. Since it arrives in a request body, only these pass.
ALLOWED_RELATIONSHIP_TYPES = {
    "PREREQUISITE_OF",
    "RELATED_TO",
    "SUBTOPIC_OF",
    "PART_OF",
    "BUILDS_ON",
}
DEFAULT_RELATIONSHIP_TYPE = "RELATED_TO"


def _safe_rel_type(raw: Optional[str]) -> str:
    """Normalize a relationship type to one we know, never to arbitrary Cypher."""
    candidate = (raw or "").upper().replace(" ", "_").replace("-", "_")
    if candidate in ALLOWED_RELATIONSHIP_TYPES:
        return candidate
    logger.warning("Nodes: rejected unknown relationship type", received=raw)
    return DEFAULT_RELATIONSHIP_TYPE


class CreateNodeRequest(BaseModel):
    name: str
    description: Optional[str] = None
    # Left unset, the graph is chosen by the LLM from the ones the user already
    # has — that is the normal path from the canvas.
    domain: Optional[str] = None
    parent_concept_id: Optional[str] = None  # ID of parent concept for SUBTOPIC_OF
    position: Optional[dict] = None  # {x,y,z}
    auto_link: bool = True  # suggest and attach links as part of creation


class LinkSuggestion(BaseModel):
    target_id: str
    relationship_type: str
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: Optional[str] = None


class ApplyLinksRequest(BaseModel):
    links: list[LinkSuggestion]


async def _describe_concept(name: str, domain: Optional[str]) -> str:
    """One or two sentences defining ``name``. Empty string if the model fails."""
    try:
        llm = get_fast_model(temperature=0.3)
        context = f" Domain: {domain}." if domain else ""
        response = await llm.ainvoke(
            f"Generate a brief 1-2 sentence educational description for "
            f"the concept: {name}.{context} Be concise and factual."
        )
        return response.text.strip()
    except Exception as e:
        # The concept is still worth saving undescribed; it just links less well.
        logger.warning("Nodes: AI description generation failed", error=str(e))
        return ""


@router.post("")
async def create_node(
    request: CreateNodeRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a manual concept node."""
    try:
        user_id = str(current_user["id"])
        neo4j = await get_neo4j_client()

        query = """
        MERGE (c:Concept {name: $name, user_id: $user_id})
        ON CREATE SET
            c.id = $id,
            c.definition = $definition,
            c.domain = $domain,
            c.complexity_score = $complexity_score,
            c.confidence = $confidence,
            c.x = $x,
            c.y = $y,
            c.z = $z,
            c.source = 'user_created',
            c.created_at = datetime()
        ON MATCH SET
            c.definition = coalesce(c.definition, $definition),
            c.confidence = coalesce(c.confidence, $confidence),
            c.x = coalesce(c.x, $x),
            c.y = coalesce(c.y, $y),
            c.z = coalesce(c.z, $z),
            c.updated_at = datetime()
        RETURN c
        """
        import uuid
        concept_id = str(uuid.uuid4())
        position = request.position or {}

        # Write the description BEFORE choosing the graph. From the canvas the
        # user types a bare name, and filing on a name alone is a coin toss —
        # "Scaled Dot-Product Attention" reads as generic AI without its
        # definition and as NLP with it. The definition also feeds the embedding
        # that link suggestion searches on, so it has to come first either way.
        node_definition = (request.description or "").strip()
        if not node_definition:
            node_definition = await _describe_concept(request.name, request.domain)

        # Which graph this belongs in is the LLM's call, against the graphs the
        # user already has, so a concept typed onto the canvas lands beside its
        # relatives instead of in a new one-node graph.
        graph_outcome = await resolve_graph(
            user_id,
            proposed=request.domain,
            concept_name=request.name,
            definition=node_definition,
        )
        domain = graph_outcome["graph"]

        result = await neo4j.execute_query(
            query,
            {
                "id": concept_id,
                "user_id": user_id,
                "name": request.name,
                "definition": node_definition,
                "domain": domain,
                "complexity_score": 5.0,
                "confidence": 1.0,  # User-created concepts have full confidence
                "x": position.get("x"),
                "y": position.get("y"),
                "z": position.get("z"),
            },
        )
        node = result[0]["c"] if result else {}
        # Convert Neo4j Node to plain dict if needed
        try:
            if hasattr(node, "_properties"):
                node = dict(node._properties)
        except Exception:
            pass

        # An existing concept keeps whatever definition it already had (the MERGE
        # coalesces), so reflect that back rather than the one we just wrote.
        if isinstance(node, dict) and node.get("definition"):
            node_definition = node["definition"]

        # Generate and store embedding for the concept (enables ingestion matching)
        try:
            embed_svc = EmbeddingService()
            embed_text = f"{request.name}: {node_definition}" if node_definition else request.name
            embeddings = await embed_svc.embed_batch([embed_text])
            if embeddings and embeddings[0]:
                await neo4j.execute_query(
                    """
                    MATCH (c:Concept {name: $name, user_id: $user_id})
                    SET c.embedding = $embedding
                    RETURN c.id
                    """,
                    {
                        "name": request.name,
                        "user_id": user_id,
                        "embedding": embeddings[0],
                    },
                )
        except Exception as e:
            logger.warning("Nodes: Embedding generation failed", error=str(e))

        # Create SUBTOPIC_OF relationship if parent specified
        if request.parent_concept_id:
            try:
                node_id = node.get("id") or concept_id
                await neo4j.execute_query(
                    """
                    MATCH (child:Concept {id: $child_id, user_id: $user_id})
                    MATCH (parent:Concept {id: $parent_id, user_id: $user_id})
                    MERGE (child)-[r:SUBTOPIC_OF]->(parent)
                    ON CREATE SET r.strength = 1.0,
                                  r.source = 'user_created',
                                  r.mention_count = 1,
                                  r.created_at = datetime()
                    ON MATCH SET r.mention_count = coalesce(r.mention_count, 1) + 1,
                                 r.updated_at = datetime()
                    RETURN type(r) as relationship
                    """,
                    {
                        "child_id": node_id,
                        "parent_id": request.parent_concept_id,
                        "user_id": user_id,
                    },
                )
            except Exception as e:
                logger.warning("Nodes: Failed to create SUBTOPIC_OF", error=str(e))

        # Initialize proficiency_scores (best-effort)
        try:
            pg_client = await get_postgres_client()
            await pg_client.execute_update(
                """
                INSERT INTO proficiency_scores (user_id, concept_id, score)
                VALUES (:user_id, :concept_id, 0.10)
                ON CONFLICT (user_id, concept_id) DO NOTHING
                """,
                {"user_id": user_id, "concept_id": node.get("id")},
            )
        except Exception as e:
            logger.warning("Nodes: Failed to init proficiency", error=str(e))

        node_id = node.get("id") or concept_id
        applied: list[dict] = []
        pending: list[dict] = []

        if request.auto_link:
            try:
                suggestion = await run_link_suggestions(node_id=node_id, user_id=user_id)
                for link in suggestion.get("links", []):
                    if float(link.get("strength", 0)) >= AUTO_LINK_THRESHOLD:
                        applied.append(link)
                    else:
                        pending.append(link)
                if applied:
                    await _create_links(
                        neo4j,
                        user_id=user_id,
                        node_id=node_id,
                        links=[
                            LinkSuggestion(
                                target_id=l["target_id"],
                                relationship_type=l.get("relationship_type", "RELATED_TO"),
                                strength=float(l.get("strength", 0.5)),
                                reason=l.get("reason"),
                            )
                            for l in applied
                        ],
                        source="auto_linked",
                    )
            except Exception as e:
                # A concept that is saved but unlinked is recoverable; one that
                # failed to save because linking broke is not.
                logger.warning("Nodes: auto-link failed", node_id=node_id, error=str(e))

        return {
            "status": "created",
            "node": node,
            "graph": {
                "name": domain,
                "created": graph_outcome.get("created", False),
                "reason": graph_outcome.get("reason"),
            },
            "links_applied": applied,
            "links_pending": pending,
        }
    except Exception as e:
        logger.error("Nodes: Error creating node", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def _create_links(
    neo4j,
    *,
    user_id: str,
    node_id: str,
    links: list[LinkSuggestion],
    source: str = "user_linked",
) -> list[dict]:
    """MERGE each suggested relationship from ``node_id``. Returns what was made."""
    created = []
    for link in links:
        rel = _safe_rel_type(link.relationship_type)
        await neo4j.execute_query(
            f"""
            MATCH (a:Concept {{id: $source_id, user_id: $user_id}})
            MATCH (b:Concept {{id: $target_id, user_id: $user_id}})
            MERGE (a)-[r:{rel}]->(b)
            ON CREATE SET r.strength = $strength,
                          r.source = $source,
                          r.mention_count = 1,
                          r.created_at = datetime()
            ON MATCH SET r.mention_count = coalesce(r.mention_count, 1) + 1,
                         r.strength = $strength,
                         r.updated_at = datetime()
            RETURN type(r) as relationship
            """,
            {
                "source_id": node_id,
                "target_id": link.target_id,
                "user_id": user_id,
                "strength": link.strength,
                "source": source,
            },
        )
        created.append({"target_id": link.target_id, "relationship_type": rel})
    return created


@router.post("/{node_id}/suggest-links")
async def suggest_links(
    node_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Suggest links for a node using LangGraph workflow."""
    try:
        user_id = str(current_user["id"])
        result = await run_link_suggestions(node_id=node_id, user_id=user_id)
        if result.get("error") == "Node not found":
            raise HTTPException(status_code=404, detail="Node not found")
        if result.get("error"):
            raise HTTPException(status_code=500, detail=result.get("error"))

        return {"node_id": node_id, "links": result.get("links", [])}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Nodes: Error suggesting links", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{node_id}/link")
async def apply_links(
    node_id: str,
    request: ApplyLinksRequest,
    current_user: dict = Depends(get_current_user),
):
    """Apply approved links to a node."""
    try:
        user_id = str(current_user["id"])
        neo4j = await get_neo4j_client()

        # Validate node exists
        node_result = await neo4j.execute_query(
            "MATCH (c:Concept {id: $id, user_id: $user_id}) RETURN c",
            {"id": node_id, "user_id": user_id},
        )
        if not node_result:
            raise HTTPException(status_code=404, detail="Node not found")

        created = await _create_links(
            neo4j, user_id=user_id, node_id=node_id, links=request.links
        )

        return {"status": "linked", "node_id": node_id, "links": created}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Nodes: Error applying links", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
