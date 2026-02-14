"""Community detection and persistence service.

Implements Microsoft GraphRAG-style multi-level community hierarchy:
- Level 0: Fine-grained communities (high Louvain resolution)
- Level 1: Medium communities (default resolution)
- Level 2: Coarse communities (low resolution)

Each level's communities are linked to their parent in the level above.
Community reports are LLM-generated summaries used for Global Search.
"""

import uuid
import structlog
from typing import Any

import networkx as nx

from backend.config.llm import get_chat_model
from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client

logger = structlog.get_logger()

# Resolution configs for multi-level hierarchy (higher = more granular)
LEVEL_RESOLUTIONS = [
    (0, 2.0),   # Level 0: Fine-grained (many small communities)
    (1, 1.0),   # Level 1: Default (balanced)
    (2, 0.5),   # Level 2: Coarse (few large communities)
]


class CommunityService:
    async def compute_communities(self, user_id: str) -> list[dict[str, Any]]:
        """Compute multi-level communities using Louvain at multiple resolutions."""
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

        if len(G.nodes) == 0:
            return []

        domain_map = {n["id"]: n.get("domain") or "General" for n in nodes_result if n.get("id")}
        name_map = {n["id"]: n.get("name") or "" for n in nodes_result if n.get("id")}

        # Run Louvain at each resolution level
        level_partitions: list[dict[str, int]] = []

        for _level, resolution in LEVEL_RESOLUTIONS:
            try:
                communities_sets = nx.algorithms.community.louvain_communities(
                    G, weight="weight", resolution=resolution, seed=42
                )
            except Exception as e:
                logger.warning("Louvain failed at resolution", resolution=resolution, error=str(e))
                communities_sets = list(nx.connected_components(G))

            partition: dict[str, int] = {}
            for idx, members in enumerate(communities_sets):
                for node_id in members:
                    partition[node_id] = idx
            level_partitions.append(partition)

        # Build community objects per level, from coarsest to finest
        level_communities: dict[int, list[dict]] = {}

        for level_idx in reversed(range(len(LEVEL_RESOLUTIONS))):
            level, _resolution = LEVEL_RESOLUTIONS[level_idx]
            partition = level_partitions[level_idx]

            community_groups: dict[int, list[str]] = {}
            for node_id, comm_idx in partition.items():
                community_groups.setdefault(comm_idx, []).append(node_id)

            communities_at_level = []
            for comm_idx, member_ids in community_groups.items():
                if not member_ids:
                    continue

                domain_counts: dict[str, int] = {}
                for m in member_ids:
                    d = domain_map.get(m, "General")
                    domain_counts[d] = domain_counts.get(d, 0) + 1
                top_domain = max(domain_counts, key=domain_counts.get) if domain_counts else "General"

                rep_names = sorted(
                    [name_map.get(m, "") for m in member_ids if name_map.get(m)],
                    key=lambda x: len(x),
                )[:3]
                title_suffix = ", ".join(rep_names) if rep_names else f"Cluster {comm_idx}"
                title = f"{top_domain}: {title_suffix}" if level <= 1 else f"{top_domain} Group"

                communities_at_level.append({
                    "id": str(uuid.uuid4()),
                    "title": title,
                    "level": level,
                    "parent_id": None,
                    "entity_ids": member_ids,
                    "size": len(member_ids),
                })

            level_communities[level] = communities_at_level

        # Link parent relationships
        for level_idx in range(len(LEVEL_RESOLUTIONS) - 1):
            level = LEVEL_RESOLUTIONS[level_idx][0]
            parent_level = LEVEL_RESOLUTIONS[level_idx + 1][0]

            child_comms = level_communities.get(level, [])
            parent_comms = level_communities.get(parent_level, [])
            if not parent_comms:
                continue

            node_to_parent: dict[str, str] = {}
            for pc in parent_comms:
                for nid in pc["entity_ids"]:
                    node_to_parent[nid] = pc["id"]

            for cc in child_comms:
                parent_votes: dict[str, int] = {}
                for nid in cc["entity_ids"]:
                    pid = node_to_parent.get(nid)
                    if pid:
                        parent_votes[pid] = parent_votes.get(pid, 0) + 1
                if parent_votes:
                    cc["parent_id"] = max(parent_votes, key=parent_votes.get)

        # Flatten all levels
        all_communities: list[dict[str, Any]] = []
        for lvl, _ in LEVEL_RESOLUTIONS:
            all_communities.extend(level_communities.get(lvl, []))

        logger.info(
            "compute_communities: Done",
            total=len(all_communities),
            by_level={lvl: len(level_communities.get(lvl, [])) for lvl, _ in LEVEL_RESOLUTIONS},
        )
        return all_communities

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
                    "parent_id": community.get("parent_id"),
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

            # Sync community_id to Neo4j — use level 0 (finest) for node-level queries
            if community["entity_ids"] and community["level"] == 0:
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

    async def generate_community_summaries(self, user_id: str, force: bool = False) -> None:
        """Generate rich LLM community reports for Global Search.

        Reports are richer at higher levels (coarser communities).
        Skips communities that already have a summary unless force=True.
        Uses parallel LLM calls for efficiency.
        """
        import asyncio

        communities = await self.get_communities(user_id)
        if not communities:
            return

        # Filter: skip communities that already have summaries (caching)
        if not force:
            communities = [c for c in communities if not c.get("summary")]
            if not communities:
                logger.info("generate_community_summaries: All summaries cached, skipping")
                return

        neo4j = await get_neo4j_client()
        pg = await get_postgres_client()
        llm = get_chat_model(temperature=0.1)

        async def _summarize_one(community: dict) -> None:
            concept_ids = community.get("entity_ids", [])
            if not concept_ids or len(concept_ids) < 2:
                return

            concepts = await neo4j.execute_query(
                """
                MATCH (c:Concept)
                WHERE c.id IN $ids AND c.user_id = $uid
                RETURN c.name AS name, c.definition AS definition,
                       c.domain AS domain, c.confidence AS confidence
                """,
                {"ids": concept_ids[:30], "uid": user_id},
            )
            if not concepts:
                return

            relationships = await neo4j.execute_query(
                """
                MATCH (c1:Concept)-[r]->(c2:Concept)
                WHERE c1.id IN $ids AND c2.id IN $ids
                  AND c1.user_id = $uid AND c2.user_id = $uid
                RETURN c1.name AS from_name, type(r) AS rel_type, c2.name AS to_name,
                       r.strength AS strength
                ORDER BY r.strength DESC
                LIMIT 15
                """,
                {"ids": concept_ids[:30], "uid": user_id},
            )

            concepts_text = "\n".join(
                f"- {c['name']}: {(c.get('definition') or '')[:150]}"
                f" [confidence: {c.get('confidence', 0.8):.1f}]"
                for c in concepts
            )

            rels_text = "\n".join(
                f"- {r['from_name']} --[{r['rel_type']}]--> {r['to_name']}"
                f" (strength: {r.get('strength', 1.0):.1f})"
                for r in (relationships or [])
            )

            level = community.get("level", 0)
            if level >= 2:
                detail_instruction = (
                    "Write a comprehensive 4-6 sentence summary. This is a high-level theme. "
                    "Explain the overarching narrative, why these concepts cluster together, "
                    "and what someone studying this area should understand."
                )
            elif level == 1:
                detail_instruction = (
                    "Write a 3-4 sentence summary. Focus on the theme, "
                    "the key concepts, and how they interconnect."
                )
            else:
                detail_instruction = (
                    "Write a 2-3 sentence summary focusing on what connects these "
                    "specific concepts and their practical significance."
                )

            prompt = f"""{detail_instruction}

Community: {community.get('title', 'Unknown')} (Level {level}, {len(concept_ids)} concepts)

Concepts:
{concepts_text}

Key Relationships:
{rels_text if rels_text else 'No internal relationships found.'}

Summary:"""

            try:
                response = await llm.ainvoke(prompt)
                summary = response.content.strip()
                if not summary:
                    return

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

        # Run all community summaries in parallel
        await asyncio.gather(
            *[_summarize_one(c) for c in communities],
            return_exceptions=True,
        )

    async def get_communities(self, user_id: str) -> list[dict[str, Any]]:
        """Fetch communities and node mappings from Postgres."""
        pg = await get_postgres_client()
        community_rows = await pg.execute_query(
            """
            SELECT id, title, level, parent_id, size, summary
            FROM communities
            WHERE user_id = :user_id
            ORDER BY level ASC, size DESC
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

        # Build children lists
        id_map = {c["id"]: c for c in communities}
        for c in communities:
            if c["parent"] and c["parent"] in id_map:
                id_map[c["parent"]]["children"].append(c["id"])

        return communities

    async def get_community_summaries_by_level(
        self, user_id: str, level: int | None = None
    ) -> list[dict[str, Any]]:
        """Get community summaries, optionally filtered by level.

        Used by Global Search to get all summaries at a given hierarchy level.
        """
        pg = await get_postgres_client()
        if level is not None:
            rows = await pg.execute_query(
                """
                SELECT id, title, level, size, summary
                FROM communities
                WHERE user_id = :user_id AND level = :level AND summary IS NOT NULL
                ORDER BY size DESC
                """,
                {"user_id": user_id, "level": level},
            )
        else:
            rows = await pg.execute_query(
                """
                SELECT id, title, level, size, summary
                FROM communities
                WHERE user_id = :user_id AND summary IS NOT NULL
                ORDER BY level DESC, size DESC
                """,
                {"user_id": user_id},
            )
        return [dict(r) for r in (rows or [])]
