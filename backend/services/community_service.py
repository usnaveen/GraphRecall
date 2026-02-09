"""Community detection and persistence service."""

import uuid
import structlog
from typing import Any

import networkx as nx

from backend.config.llm import get_chat_model
from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client

logger = structlog.get_logger()


class CommunityService:
    async def compute_communities(self, user_id: str) -> list[dict[str, Any]]:
        """Compute communities using Louvain and return list of communities with member ids."""
        neo4j = await get_neo4j_client()

        nodes_result = await neo4j.execute_query(
            """
            MATCH (c:Concept {user_id: $user_id})
            RETURN c.id AS id, c.name AS name, c.domain AS domain
            """,
            {"user_id": user_id},
        )
        edges_result = await neo4j.execute_query(
            """
            MATCH (c1:Concept)-[r]->(c2:Concept)
            WHERE c1.user_id = $user_id AND c2.user_id = $user_id
            RETURN c1.id AS source, c2.id AS target, coalesce(r.strength, 1.0) AS strength
            """,
            {"user_id": user_id},
        )

        if not nodes_result:
            return []

        G = nx.Graph()
        for n in nodes_result:
            if n.get("id"):
                G.add_node(n["id"])
        for e in edges_result:
            if e.get("source") and e.get("target"):
                G.add_edge(e["source"], e["target"], weight=float(e.get("strength") or 1.0))

        # Louvain community detection
        try:
            communities = nx.algorithms.community.louvain_communities(G, weight="weight", resolution=1.0)
        except Exception as e:
            logger.warning("CommunityService: Louvain failed, using connected components", error=str(e))
            communities = list(nx.connected_components(G))

        domain_map = {n["id"]: n.get("domain") or "General" for n in nodes_result if n.get("id")}
        results = []
        for idx, members in enumerate(communities):
            domain_counts: dict[str, int] = {}
            for m in members:
                d = domain_map.get(m, "General")
                domain_counts[d] = domain_counts.get(d, 0) + 1
            top_domain = max(domain_counts, key=domain_counts.get) if domain_counts else "General"
            results.append(
                {
                    "id": str(uuid.uuid4()),
                    "title": f"{top_domain} Cluster",
                    "level": 0,
                    "parent_id": None,
                    "entity_ids": list(members),
                    "size": len(members),
                }
            )
        return results

    async def persist_communities(self, user_id: str, communities: list[dict[str, Any]]) -> None:
        """Persist communities to Postgres and sync community_id to Neo4j Concept nodes."""
        pg = await get_postgres_client()
        neo4j = await get_neo4j_client()

        await pg.execute_update(
            "DELETE FROM community_nodes WHERE user_id = :user_id",
            {"user_id": user_id},
        )
        await pg.execute_update(
            "DELETE FROM communities WHERE user_id = :user_id",
            {"user_id": user_id},
        )

        # Clear existing community_id from Neo4j (in case concepts moved between communities)
        try:
            await neo4j.execute_query(
                """
                MATCH (c:Concept {user_id: $uid})
                WHERE c.community_id IS NOT NULL
                REMOVE c.community_id
                """,
                {"uid": user_id},
            )
        except Exception as e:
            logger.warning("persist_communities: Failed to clear Neo4j community_id", error=str(e))

        for community in communities:
            await pg.execute_update(
                """
                INSERT INTO communities (id, user_id, title, level, parent_id, size)
                VALUES (:id, :user_id, :title, :level, :parent_id, :size)
                """,
                {
                    "id": community["id"],
                    "user_id": user_id,
                    "title": community["title"],
                    "level": community["level"],
                    "parent_id": community["parent_id"],
                    "size": community["size"],
                },
            )
            for concept_id in community["entity_ids"]:
                await pg.execute_update(
                    """
                    INSERT INTO community_nodes (community_id, user_id, concept_id)
                    VALUES (:community_id, :user_id, :concept_id)
                    """,
                    {
                        "community_id": community["id"],
                        "user_id": user_id,
                        "concept_id": concept_id,
                    },
                )

            # Sync community_id to Neo4j Concept nodes for graph-level queries
            if community["entity_ids"]:
                try:
                    await neo4j.execute_query(
                        """
                        MATCH (c:Concept {user_id: $uid})
                        WHERE c.id IN $concept_ids
                        SET c.community_id = $community_id
                        """,
                        {
                            "uid": user_id,
                            "concept_ids": community["entity_ids"],
                            "community_id": community["id"],
                        },
                    )
                except Exception as e:
                    logger.warning(
                        "persist_communities: Failed to sync community_id to Neo4j",
                        community_id=community["id"],
                        error=str(e),
                    )

    async def generate_community_summaries(self, user_id: str) -> None:
        """Generate LLM summaries for each community and persist to Postgres."""
        communities = await self.get_communities(user_id)
        if not communities:
            return

        neo4j = await get_neo4j_client()
        pg = await get_postgres_client()
        llm = get_chat_model(temperature=0.1)

        for community in communities:
            concept_ids = community.get("entity_ids", [])
            if not concept_ids or len(concept_ids) < 2:
                continue

            concepts = await neo4j.execute_query(
                """
                MATCH (c:Concept)
                WHERE c.id IN $ids AND c.user_id = $uid
                RETURN c.name AS name, c.definition AS definition
                """,
                {"ids": concept_ids[:20], "uid": user_id},
            )
            if not concepts:
                continue

            concepts_text = "\n".join(
                f"- {c['name']}: {(c.get('definition') or '')[:120]}"
                for c in concepts
            )

            prompt = (
                "Summarize this cluster of related concepts in 2-3 sentences. "
                "Focus on the overarching theme and how the concepts connect.\n\n"
                f"Concepts:\n{concepts_text}\n\nSummary:"
            )

            try:
                response = await llm.ainvoke(prompt)
                summary = response.content.strip()
                if not summary:
                    continue

                await pg.execute_update(
                    "UPDATE communities SET summary = :summary WHERE id = :id",
                    {"summary": summary, "id": community["id"]},
                )
            except Exception as e:
                logger.warning(
                    "generate_community_summaries: Failed for community",
                    community_id=community["id"],
                    error=str(e),
                )
                continue

    async def get_communities(self, user_id: str) -> list[dict[str, Any]]:
        """Fetch communities and node mappings from Postgres."""
        pg = await get_postgres_client()
        community_rows = await pg.execute_query(
            """
            SELECT id, title, level, parent_id, size, summary
            FROM communities
            WHERE user_id = :user_id
            ORDER BY size DESC
            """,
            {"user_id": user_id},
        )
        if not community_rows:
            return []

        mapping_rows = await pg.execute_query(
            """
            SELECT community_id, concept_id
            FROM community_nodes
            WHERE user_id = :user_id
            """,
            {"user_id": user_id},
        )
        mapping: dict[str, list[str]] = {}
        for row in mapping_rows:
            cid = str(row["community_id"])
            mapping.setdefault(cid, []).append(row["concept_id"])

        communities = []
        for row in community_rows:
            cid = str(row["id"])
            communities.append(
                {
                    "id": cid,
                    "title": row["title"],
                    "level": row["level"] or 0,
                    "parent": str(row["parent_id"]) if row.get("parent_id") else None,
                    "children": [],
                    "entity_ids": mapping.get(cid, []),
                    "size": row.get("size") or len(mapping.get(cid, [])),
                    "summary": row.get("summary"),
                }
            )
        return communities
