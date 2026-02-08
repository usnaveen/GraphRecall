"""Nodes Router - Manual node creation and AI-assisted linking."""

from typing import Optional
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth.middleware import get_current_user
from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.graphs.link_suggestion_graph import run_link_suggestions

logger = structlog.get_logger()

router = APIRouter(prefix="/api/nodes", tags=["Nodes"])


class CreateNodeRequest(BaseModel):
    name: str
    description: Optional[str] = None
    domain: Optional[str] = None  # e.g. "Machine Learning", "Mathematics"
    parent_concept_id: Optional[str] = None  # ID of parent concept for SUBTOPIC_OF
    position: Optional[dict] = None  # {x,y,z}


class LinkSuggestion(BaseModel):
    target_id: str
    relationship_type: str
    strength: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: Optional[str] = None


class ApplyLinksRequest(BaseModel):
    links: list[LinkSuggestion]


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
            c.x = $x,
            c.y = $y,
            c.z = $z,
            c.source = 'user_created',
            c.created_at = datetime()
        ON MATCH SET
            c.definition = coalesce(c.definition, $definition),
            c.x = coalesce(c.x, $x),
            c.y = coalesce(c.y, $y),
            c.z = coalesce(c.z, $z),
            c.updated_at = datetime()
        RETURN c
        """
        import uuid
        concept_id = str(uuid.uuid4())
        position = request.position or {}
        domain = request.domain or "General"
        result = await neo4j.execute_query(
            query,
            {
                "id": concept_id,
                "user_id": user_id,
                "name": request.name,
                "definition": request.description or "",
                "domain": domain,
                "complexity_score": 5.0,
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

        # Create SUBTOPIC_OF relationship if parent specified
        if request.parent_concept_id:
            try:
                node_id = node.get("id") or concept_id
                await neo4j.execute_query(
                    """
                    MATCH (child:Concept {id: $child_id, user_id: $user_id})
                    MATCH (parent:Concept {id: $parent_id, user_id: $user_id})
                    MERGE (child)-[r:SUBTOPIC_OF]->(parent)
                    SET r.strength = 1.0, r.source = 'user_created'
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

        return {
            "status": "created",
            "node": node,
        }
    except Exception as e:
        logger.error("Nodes: Error creating node", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


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

        created = []
        for link in request.links:
            rel = link.relationship_type.upper().replace(" ", "_")
            await neo4j.execute_query(
                f"""
                MATCH (a:Concept {{id: $source_id, user_id: $user_id}})
                MATCH (b:Concept {{id: $target_id, user_id: $user_id}})
                MERGE (a)-[r:{rel}]->(b)
                SET r.strength = $strength
                RETURN type(r) as relationship
                """,
                {
                    "source_id": node_id,
                    "target_id": link.target_id,
                    "user_id": user_id,
                    "strength": link.strength,
                },
            )
            created.append({"target_id": link.target_id, "relationship_type": rel})

        return {"status": "linked", "node_id": node_id, "links": created}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Nodes: Error applying links", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
