"""Graph 3D Router - Endpoints for 3D Knowledge Graph Visualization."""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from backend.auth.middleware import get_current_user

from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.models.feed_schemas import (
    Graph3DNode,
    Graph3DEdge,
    Graph3DResponse,
    Graph3DFilterRequest,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/graph3d", tags=["3D Graph"])


# Domain to color mapping for consistent visualization
DOMAIN_COLORS = {
    "Machine Learning": "#7C3AED",  # Purple
    "Mathematics": "#3B82F6",  # Blue
    "Computer Science": "#10B981",  # Green
    "Database Systems": "#F59E0B",  # Amber
    "System Design": "#EF4444",  # Red
    "Programming": "#06B6D4",  # Cyan
    "Statistics": "#8B5CF6",  # Violet
    "General": "#6B7280",  # Gray
}


def get_domain_color(domain: str) -> str:
    """Get color for a domain, with fallback."""
    return DOMAIN_COLORS.get(domain, DOMAIN_COLORS["General"])


def calculate_node_size(complexity: float, relationship_count: int) -> float:
    """Calculate node size based on complexity and connectivity."""
    # Base size from complexity (1-10 scale)
    base_size = 0.5 + (complexity / 10) * 0.5
    
    # Boost for highly connected nodes
    connectivity_boost = min(relationship_count / 20, 0.5)
    
    return round(base_size + connectivity_boost, 2)


@router.get("", response_model=Graph3DResponse)
async def get_3d_graph(
    current_user: dict = Depends(get_current_user),
    center_concept_id: Optional[str] = Query(
        default=None,
        description="Focus on this concept and show its neighborhood",
    ),
    domains: Optional[str] = Query(
        default=None,
        description="Comma-separated domains to filter",
    ),
    min_mastery: Optional[float] = Query(
        default=None,
        ge=0.0,
        le=1.0,
        description="Filter concepts by minimum mastery level",
    ),
    max_depth: int = Query(
        default=3,
        ge=1,
        le=5,
        description="Maximum depth for graph traversal from center",
    ),
):
    """
    Get 3D graph data for visualization.
    
    Returns nodes and edges optimized for Three.js/React Three Fiber rendering.
    
    Features:
    - Filter by domain
    - Filter by mastery level
    - Focus on specific concept and its neighborhood
    - Cluster information for visual grouping
    
    Node properties include:
    - Position (optional, can be calculated client-side)
    - Size based on complexity and connectivity
    - Color based on domain
    - Mastery level for opacity/glow effects
    
    Edge properties include:
    - Relationship type
    - Strength for line thickness
    """
    try:
        neo4j_client = await get_neo4j_client()
        pg_client = await get_postgres_client()
        
        # Parse domains filter
        domain_list = None
        if domains:
            domain_list = [d.strip() for d in domains.split(",")]
        
        user_id = str(current_user["id"])
        
        # Build query based on filters
        if center_concept_id:
            # Get neighborhood around center concept
            # Note: For now, we assume concepts in Neo4j will have user_id, 
            # though current schema might not have it yet. We'll add it to queries.
            query = """
            MATCH path = (center:Concept {id: $center_id, user_id: $user_id})-[r*1..%d]-(related:Concept)
            WHERE center <> related AND related.user_id = $user_id
            WITH DISTINCT related, center,
                 min(length(path)) as distance
            %s
            RETURN related as concept, distance
            ORDER BY distance
            LIMIT 100
            """ % (
                max_depth,
                f"WHERE related.domain IN $domains" if domain_list else "",
            )
            
            params = {"center_id": center_concept_id, "user_id": user_id}
            if domain_list:
                params["domains"] = domain_list
            
            # Get center concept first
            center_result = await neo4j_client.execute_query(
                "MATCH (c:Concept {id: $id, user_id: $user_id}) RETURN c",
                {"id": center_concept_id, "user_id": user_id},
            )
            
            if not center_result:
                raise HTTPException(
                    status_code=404,
                    detail=f"Concept not found: {center_concept_id}",
                )
            
            # Get related concepts
            related_result = await neo4j_client.execute_query(query, params)
            
            concepts = [center_result[0]["c"]]
            for r in related_result:
                concepts.append(r["concept"])
                
        else:
            # Get all concepts (with optional filtering)
            where_clauses = ["c.user_id = $user_id"]
            params = {"user_id": user_id}
            
            if domain_list:
                where_clauses.append("c.domain IN $domains")
                params["domains"] = domain_list
            
            where_clause = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            
            query = f"""
            MATCH (c:Concept)
            {where_clause}
            RETURN c as concept
            ORDER BY c.created_at DESC
            LIMIT 200
            """
            
            result = await neo4j_client.execute_query(query, params)
            concepts = [r["concept"] for r in result]
            logger.info("Graph3D: Concepts found", count=len(concepts))
        
        # Get relationship counts for sizing
        relationship_counts = {}
        for concept in concepts:
            concept_id = concept.get("id")
            count_result = await neo4j_client.execute_query(
                """
                MATCH (c:Concept {id: $id, user_id: $user_id})-[r]-()
                RETURN count(r) as count
                """,
                {"id": concept_id, "user_id": user_id},
            )
            relationship_counts[concept_id] = (
                count_result[0]["count"] if count_result else 0
            )
        
        # Get mastery levels from PostgreSQL
        mastery_levels = {}
        concept_ids = [c.get("id") for c in concepts]
        
        if concept_ids:
            mastery_result = await pg_client.execute_query(
                """
                SELECT concept_id, score
                FROM proficiency_scores
                WHERE user_id = :user_id
                  AND concept_id = ANY(:concept_ids)
                """,
                {"user_id": user_id, "concept_ids": concept_ids},
            )
            
            for row in mastery_result:
                mastery_levels[row["concept_id"]] = row["score"]
        
        # Filter by mastery if specified
        if min_mastery is not None:
            concepts = [
                c for c in concepts
                if mastery_levels.get(c.get("id"), 0) >= min_mastery
            ]
        
        # Build nodes
        nodes = []
        for concept in concepts:
            concept_id = concept.get("id")
            domain = concept.get("domain", "General")
            complexity = concept.get("complexity_score", 5)
            mastery = mastery_levels.get(concept_id, 0)
            rel_count = relationship_counts.get(concept_id, 0)
            
            nodes.append(Graph3DNode(
                id=concept_id,
                name=concept.get("name", "Unknown"),
                definition=concept.get("definition", ""),
                domain=domain,
                complexity_score=complexity,
                mastery_level=mastery,
                size=calculate_node_size(complexity, rel_count),
                color=get_domain_color(domain),
            ))
        
        # Get edges
        node_ids = [n.id for n in nodes]
        
        edges_query = """
        MATCH (c1:Concept)-[r]->(c2:Concept)
        WHERE c1.id IN $node_ids AND c2.id IN $node_ids
          AND c1.user_id = $user_id AND c2.user_id = $user_id
        RETURN 
            c1.id as source,
            c2.id as target,
            type(r) as relationship_type,
            coalesce(r.strength, 1.0) as strength,
            elementId(r) as edge_id
        """

        if len(node_ids) > 0:
             logger.info("Graph3D: Querying edges for nodes", node_count=len(node_ids), sample_ids=node_ids[:5])
        
        edges_result = await neo4j_client.execute_query(
            edges_query,
            {"node_ids": node_ids, "user_id": user_id},
        )
        logger.info("Graph3D: Edges found", count=len(edges_result))
        
        edges = [
            Graph3DEdge(
                id=str(e["edge_id"]),
                source=e["source"],
                target=e["target"],
                relationship_type=e["relationship_type"],
                strength=e["strength"],
            )
            for e in edges_result
        ]
        
        # Build networkx graph for layout
        import networkx as nx
        G = nx.Graph()
        
        # Add nodes
        for node in nodes:
            G.add_node(node.id)
            
        # Add edges
        for edge in edges:
            G.add_edge(edge.source, edge.target, weight=edge.strength)
            
        # Calculate layout
        # usage of spring_layout for 3D
        # k=None (default 1/sqrt(n)), iterations=50
        pos = nx.spring_layout(G, dim=3, seed=42, iterations=50, scale=400)
        
        # Assign positions back to nodes
        for node in nodes:
            if node.id in pos:
                x, y, z = pos[node.id]
                node.x = float(x)
                node.y = float(y)
                node.z = float(z)
                

        
        # Calculate clusters based on domains
        unique_domains = {n.domain for n in nodes}
        clusters = [
            {
                "id": d,
                "label": d,
                "color": get_domain_color(d)
            }
            for d in unique_domains
        ]
                
        return Graph3DResponse(
            nodes=nodes,
            edges=edges,
            clusters=clusters,
            total_nodes=len(nodes),
            total_edges=len(edges),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Graph3D: Error getting graph", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/focus/{concept_id}")
async def focus_on_concept(
    concept_id: str,
    current_user: dict = Depends(get_current_user),
    depth: int = Query(default=2, ge=1, le=4),
):
    """
    Get focused view of a single concept and its immediate connections.
    
    Returns:
    - The center concept with full details
    - Directly connected concepts
    - Paths to prerequisites
    - Related concepts by domain
    
    Optimized for the "zoom into concept" animation.
    """
    try:
        neo4j_client = await get_neo4j_client()
        pg_client = await get_postgres_client()
        
        user_id = str(current_user["id"])
        # Get center concept
        center_result = await neo4j_client.execute_query(
            """
            MATCH (c:Concept {id: $id, user_id: $user_id})
            RETURN c
            """,
            {"id": concept_id, "user_id": user_id},
        )
        
        if not center_result:
            raise HTTPException(status_code=404, detail="Concept not found")
        
        center = center_result[0]["c"]
        
        # Get connected concepts with relationship info
        connected_result = await neo4j_client.execute_query(
            """
            MATCH (center:Concept {id: $id, user_id: $user_id})-[r]-(connected:Concept)
            WHERE connected.user_id = $user_id
            RETURN 
                connected,
                type(r) as relationship,
                CASE WHEN startNode(r) = center THEN 'outgoing' ELSE 'incoming' END as direction,
                coalesce(r.strength, 1.0) as strength
            ORDER BY strength DESC
            LIMIT 20
            """,
            {"id": concept_id, "user_id": user_id},
        )
        
        # Get prerequisite path (what to learn first)
        prereq_path = await neo4j_client.execute_query(
            """
            MATCH path = (prereq:Concept)-[:PREREQUISITE_OF*1..3]->(center:Concept {id: $id})
            WHERE prereq.user_id = $user_id AND center.user_id = $user_id
            WITH [n IN nodes(path) | {id: n.id, name: n.name}] as path_nodes
            RETURN path_nodes
            ORDER BY size(path_nodes) DESC
            LIMIT 1
            """,
            {"id": concept_id, "user_id": user_id},
        )
        
        # Get linked notes for this concept
        linked_notes_result = await neo4j_client.execute_query(
            """
            MATCH (n:NoteSource)-[r:EXPLAINS]->(c:Concept {id: $id, user_id: $user_id})
            RETURN n.id AS note_id, n.summary AS summary,
                   r.relevance AS relevance
            ORDER BY r.relevance DESC
            LIMIT 10
            """,
            {"id": concept_id, "user_id": user_id},
        )

        # Enrich linked notes with full note data from Postgres
        linked_notes = []
        for ln in linked_notes_result:
            note_data = await pg_client.execute_query(
                """
                SELECT id, title, content_text, resource_type, created_at
                FROM notes
                WHERE id = :note_id AND user_id = :user_id
                """,
                {"note_id": ln["note_id"], "user_id": user_id},
            )
            if note_data:
                nd = note_data[0]
                linked_notes.append({
                    "id": str(nd["id"]),
                    "title": nd.get("title", "Untitled"),
                    "preview": (nd.get("content_text", "") or "")[:150],
                    "resource_type": nd.get("resource_type", "note"),
                    "relevance": ln.get("relevance", 0),
                    "created_at": str(nd.get("created_at", "")),
                })

        # Get mastery for all concepts
        all_ids = [concept_id] + [c["connected"]["id"] for c in connected_result]

        mastery_result = await pg_client.execute_query(
            """
            SELECT concept_id, score
            FROM proficiency_scores
            WHERE user_id = :user_id
              AND concept_id = ANY(:ids)
            """,
            {"user_id": user_id, "ids": all_ids},
        )

        mastery_map = {r["concept_id"]: r["score"] for r in mastery_result}

        # Build response
        return {
            "center": {
                "id": center["id"],
                "name": center["name"],
                "definition": center.get("definition", ""),
                "domain": center.get("domain", "General"),
                "complexity_score": center.get("complexity_score", 5),
                "mastery_level": mastery_map.get(concept_id, 0),
                "color": get_domain_color(center.get("domain", "General")),
            },
            "connections": [
                {
                    "concept": {
                        "id": c["connected"]["id"],
                        "name": c["connected"]["name"],
                        "definition": c["connected"].get("definition", "")[:100],
                        "domain": c["connected"].get("domain", "General"),
                        "mastery_level": mastery_map.get(c["connected"]["id"], 0),
                    },
                    "relationship": c["relationship"],
                    "direction": c["direction"],
                    "strength": c["strength"],
                }
                for c in connected_result
            ],
            "prerequisite_path": prereq_path[0]["path_nodes"] if prereq_path else [],
            "linked_notes": linked_notes,
            "total_connections": len(connected_result),
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Graph3D: Error focusing on concept", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/domains")
async def get_domains(
    current_user: dict = Depends(get_current_user),
):
    """
    Get all domains with their colors and concept counts.
    
    Useful for building filter UI.
    """
    try:
        neo4j_client = await get_neo4j_client()
        
        result = await neo4j_client.execute_query(
            """
            MATCH (c:Concept)
            WHERE c.user_id = $user_id
            RETURN c.domain as domain, count(*) as count
            ORDER BY count DESC
            """,
            {"user_id": str(current_user["id"])},
        )
        
        domains = [
            {
                "domain": r["domain"] or "General",
                "count": r["count"],
                "color": get_domain_color(r["domain"] or "General"),
            }
            for r in result
        ]
        
        return {"domains": domains}
        
    except Exception as e:
        logger.error("Graph3D: Error getting domains", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search")
async def search_for_3d_navigation(
    query: str = Query(..., min_length=1),
    current_user: dict = Depends(get_current_user),
    limit: int = Query(default=10, le=20),
):
    """
    Search concepts for 3D graph navigation.
    
    Returns matching concepts with their positions in the graph
    for smooth navigation animation.
    """
    try:
        neo4j_client = await get_neo4j_client()
        
        user_id = str(current_user["id"])
        query_str = """
        MATCH (c:Concept)
        WHERE c.user_id = $user_id AND (
            toLower(c.name) CONTAINS toLower($query)
            OR toLower(c.definition) CONTAINS toLower($query)
        )
        RETURN c.id as id, c.name as name, c.domain as domain
        ORDER BY 
            CASE WHEN toLower(c.name) STARTS WITH toLower($query) THEN 0 ELSE 1 END,
            c.name
        LIMIT $limit
        """
        params = {"query": query, "limit": limit, "user_id": user_id}
        
        result = await neo4j_client.execute_query(query_str, params)
        
        return {
            "results": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "domain": r["domain"],
                    "color": get_domain_color(r["domain"] or "General"),
                }
                for r in result
            ],
        }
        
    except Exception as e:
        logger.error("Graph3D: Error searching", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
