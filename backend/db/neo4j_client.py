"""Neo4j database client with connection management."""

import asyncio
from typing import Any, Optional

import structlog
from neo4j import AsyncGraphDatabase, AsyncDriver
from pydantic_settings import BaseSettings

logger = structlog.get_logger()


class Neo4jSettings(BaseSettings):
    """Neo4j connection settings."""

    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str

    model_config = {"env_prefix": "", "extra": "ignore"}


class Neo4jClient:
    """Async Neo4j client with connection management."""

    def __init__(self, settings: Optional[Neo4jSettings] = None):
        self.settings = settings or Neo4jSettings()
        self._driver: Optional[AsyncDriver] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the Neo4j driver."""
        if self._initialized:
            return

        self._driver = AsyncGraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            max_connection_lifetime=200,
            max_connection_pool_size=50,
            connection_acquisition_timeout=30,
            keep_alive=True,
        )

        # Verify connectivity
        await self._driver.verify_connectivity()

        self._initialized = True
        logger.info(
            "Neo4j client initialized",
            uri=self.settings.neo4j_uri,
        )

        # Initialize schema constraints and indexes
        await self._initialize_schema()

    async def _initialize_schema(self) -> None:
        """Create Neo4j constraints and indexes for the knowledge graph."""
        schema_queries = [
            # Unique constraints
            "CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.id IS UNIQUE",
            "CREATE CONSTRAINT note_source_id IF NOT EXISTS FOR (n:NoteSource) REQUIRE n.id IS UNIQUE",
            # Indexes for common lookups
            "CREATE INDEX concept_name IF NOT EXISTS FOR (c:Concept) ON (c.name)",
            "CREATE INDEX concept_domain IF NOT EXISTS FOR (c:Concept) ON (c.domain)",
            "CREATE INDEX note_source_note_id IF NOT EXISTS FOR (n:NoteSource) ON (n.note_id)",
        ]

        async with self._driver.session() as session:
            for query in schema_queries:
                try:
                    await session.run(query)
                except Exception as e:
                    # Constraints might already exist
                    logger.debug("Schema query result", query=query[:50], info=str(e))

        logger.info("Neo4j schema initialized")

    async def close(self) -> None:
        """Close the Neo4j driver."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            self._initialized = False
            logger.info("Neo4j client closed")

    async def health_check(self) -> dict:
        """Check database connectivity and return health status."""
        try:
            if not self._driver:
                raise RuntimeError("Driver not initialized")

            await self._driver.verify_connectivity()

            async with self._driver.session() as session:
                result = await session.run("RETURN 1 AS health")
                record = await result.single()
                if record and record["health"] == 1:
                    return {
                        "status": "healthy",
                        "database": "neo4j",
                        "connected": True,
                    }

            return {
                "status": "unhealthy",
                "database": "neo4j",
                "connected": False,
                "error": "Health check query failed",
            }
        except Exception as e:
            logger.error("Neo4j health check failed", error=str(e))
            return {
                "status": "unhealthy",
                "database": "neo4j",
                "connected": False,
                "error": str(e),
            }

    async def execute_query(
        self,
        query: str,
        parameters: Optional[dict] = None,
        database: str = "neo4j",
    ) -> list[dict[str, Any]]:
        """Execute a Cypher query and return results."""
        if not self._driver:
            raise RuntimeError("Neo4j driver not initialized")

        async with self._driver.session(database=database) as session:
            result = await session.run(query, parameters or {})
            records = await result.data()
            return records

    async def execute_write(
        self,
        query: str,
        parameters: Optional[dict] = None,
        database: str = "neo4j",
    ) -> list[dict[str, Any]]:
        """Execute a write Cypher query within a transaction."""
        if not self._driver:
            raise RuntimeError("Neo4j driver not initialized")

        async with self._driver.session(database=database) as session:
            result = await session.execute_write(
                lambda tx: tx.run(query, parameters or {})
            )
            # For write operations, we need to consume the result
            records = [record.data() async for record in result]
            return records

    async def create_concept(
        self,
        name: str,
        definition: str,
        domain: str,
        complexity_score: float,
        user_id: str,
        concept_id: Optional[str] = None,
        embedding: Optional[list[float]] = None,
    ) -> dict:
        """Create or update a Concept node, merging by name/user_id."""
        import uuid
        
        # Identity for merging should be (name, user_id)
        # c.id is a property we set, but not the merge key if we want name uniqueness
        query = """
        MERGE (c:Concept {name: $name, user_id: $user_id})
        ON CREATE SET
            c.id = $id,
            c.definition = $definition,
            c.domain = $domain,
            c.complexity_score = $complexity_score,
            c.embedding = $embedding,
            c.created_at = datetime()
        ON MATCH SET
            c.definition = $definition,
            c.complexity_score = $complexity_score,
            c.embedding = $embedding,
            c.updated_at = datetime()
        RETURN c
        """
        params = {
            "id": concept_id or str(uuid.uuid4()),
            "user_id": user_id,
            "name": name,
            "definition": definition,
            "domain": domain,
            "complexity_score": complexity_score,
            "embedding": embedding,
        }
        result = await self.execute_query(query, params)
        node_data = result[0]["c"] if result else {}
        return {"c": node_data} # Return in standard format expected by ingestion graph

    async def create_relationship(
        self,
        from_concept_id: str,
        to_concept_id: str,
        relationship_type: str,
        user_id: str,
        properties: Optional[dict] = None,
    ) -> dict:
        """Create a relationship between two concepts."""
        # Sanitize relationship type (must be valid Neo4j relationship type)
        import re
        if not re.match(r"^[A-Z0-9_]+$", relationship_type.upper()):
             raise ValueError("Invalid relationship type")
        
        rel_type = relationship_type.upper().replace(" ", "_")

        query = f"""
        MATCH (from:Concept {{id: $from_id, user_id: $user_id}})
        MATCH (to:Concept {{id: $to_id, user_id: $user_id}})
        MERGE (from)-[r:{rel_type}]->(to)
        SET r += $properties
        RETURN from.name AS from_name, type(r) AS relationship, to.name AS to_name
        """
        params = {
            "from_id": from_concept_id,
            "to_id": to_concept_id,
            "user_id": user_id,
            "properties": properties or {},
        }
        result = await self.execute_query(query, params)
        return result[0] if result else {}

    async def get_concept(self, concept_id: str, user_id: str) -> Optional[dict]:
        """Get a concept by ID."""
        query = """
        MATCH (c:Concept {id: $id, user_id: $user_id})
        RETURN c
        """
        result = await self.execute_query(query, {"id": concept_id, "user_id": user_id})
        return result[0]["c"] if result else None

    async def k_hop_context(
        self,
        concept_ids: list[str],
        user_id: str,
        max_hops: int = 2,
        max_nodes: int = 20,
        relationship_types: Optional[list[str]] = None,
        allowed_concept_ids: Optional[list[str]] = None,
    ) -> dict:
        """Return a k-hop neighborhood (nodes + edges) for seed concepts."""
        if not concept_ids:
            return {"nodes": [], "edges": []}

        rel_types = relationship_types or [
            "PREREQUISITE_OF",
            "RELATED_TO",
            "SUBTOPIC_OF",
            "BUILDS_ON",
            "PART_OF",
        ]
        max_hops = max(1, min(int(max_hops), 4))
        max_nodes = max(1, min(int(max_nodes), 100))

        seed_query = """
        MATCH (c:Concept)
        WHERE c.user_id = $user_id AND c.id IN $concept_ids
        RETURN c.id AS id, c.name AS name, c.definition AS definition,
               c.domain AS domain, c.complexity_score AS complexity,
               c.confidence AS confidence
        """
        seeds = await self.execute_query(
            seed_query, {"concept_ids": concept_ids, "user_id": user_id}
        )
        if not seeds:
            return {"nodes": [], "edges": []}

        neighbor_limit = max(max_nodes - len(seeds), 0)
        neighbors: list[dict[str, Any]] = []
        if neighbor_limit > 0 and max_hops > 0:
            allowed_clause = "AND neighbor.id IN $allowed_ids" if allowed_concept_ids else ""
            neighbor_query = f"""
            MATCH (seed:Concept {{user_id: $user_id}})
            WHERE seed.id IN $concept_ids
            MATCH path = (seed)-[rels*1..$max_hops]-(neighbor:Concept {{user_id: $user_id}})
            WHERE ALL(rel IN rels WHERE type(rel) IN $rel_types)
            {allowed_clause}
            WITH neighbor, min(length(path)) AS hops
            RETURN neighbor.id AS id, neighbor.name AS name, neighbor.definition AS definition,
                   neighbor.domain AS domain, neighbor.complexity_score AS complexity,
                   neighbor.confidence AS confidence, hops AS hops
            ORDER BY hops ASC
            LIMIT $neighbor_limit
            """
            neighbor_params = {
                "concept_ids": concept_ids,
                "user_id": user_id,
                "max_hops": max_hops,
                "neighbor_limit": neighbor_limit,
                "rel_types": rel_types,
            }
            if allowed_concept_ids:
                neighbor_params["allowed_ids"] = allowed_concept_ids
            neighbors = await self.execute_query(neighbor_query, neighbor_params)

        nodes_by_id: dict[str, dict[str, Any]] = {}
        for seed in seeds:
            nodes_by_id[seed["id"]] = {
                "id": seed["id"],
                "name": seed.get("name"),
                "definition": seed.get("definition"),
                "domain": seed.get("domain"),
                "complexity": seed.get("complexity"),
                "confidence": seed.get("confidence"),
                "hops": 0,
            }

        for neighbor in neighbors:
            nid = neighbor.get("id")
            if not nid:
                continue
            hops = int(neighbor.get("hops") or 1)
            existing = nodes_by_id.get(nid)
            if existing and existing.get("hops", 99) <= hops:
                continue
            nodes_by_id[nid] = {
                "id": nid,
                "name": neighbor.get("name"),
                "definition": neighbor.get("definition"),
                "domain": neighbor.get("domain"),
                "complexity": neighbor.get("complexity"),
                "confidence": neighbor.get("confidence"),
                "hops": hops,
            }

        nodes = list(nodes_by_id.values())
        nodes.sort(key=lambda n: (n.get("hops", 99), n.get("name") or ""))
        nodes = nodes[:max_nodes]
        node_ids = [n["id"] for n in nodes if n.get("id")]

        edges: list[dict[str, Any]] = []
        if node_ids:
            edges_query = """
            MATCH (c1:Concept)-[r]->(c2:Concept)
            WHERE c1.id IN $node_ids AND c2.id IN $node_ids
              AND c1.user_id = $user_id AND c2.user_id = $user_id
              AND type(r) IN $rel_types
            RETURN c1.id AS src, c1.name AS src_name,
                   c2.id AS tgt, c2.name AS tgt_name,
                   type(r) AS type,
                   coalesce(r.strength, 1.0) AS strength
            """
            edge_results = await self.execute_query(
                edges_query,
                {"node_ids": node_ids, "user_id": user_id, "rel_types": rel_types},
            )
            seen: set[tuple[str, str, str]] = set()
            for edge in edge_results:
                key = (edge.get("src"), edge.get("tgt"), edge.get("type"))
                if not key[0] or not key[1] or key in seen:
                    continue
                seen.add(key)
                edges.append(edge)

        return {"nodes": nodes, "edges": edges}

    async def get_concepts_by_name(self, name: str, user_id: str) -> list[dict]:
        """Search concepts by name (case-insensitive partial match)."""
        query = """
        MATCH (c:Concept)
        WHERE c.user_id = $user_id AND toLower(c.name) CONTAINS toLower($name)
        RETURN c
        ORDER BY c.name
        LIMIT 20
        """
        result = await self.execute_query(query, {"name": name, "user_id": user_id})
        return [r["c"] for r in result]

    async def get_graph_for_user(self, user_id: str, depth: int = 2) -> dict:
        """Get the knowledge graph structure for visualization."""
        query = """
        MATCH (c:Concept {user_id: $user_id})
        OPTIONAL MATCH (c)-[r]->(related:Concept {user_id: $user_id})
        WITH c, collect({
            target: related.id,
            type: type(r),
            properties: properties(r)
        }) AS relationships
        RETURN {
            id: c.id,
            name: c.name,
            domain: c.domain,
            complexity_score: c.complexity_score,
            relationships: [rel IN relationships WHERE rel.target IS NOT NULL]
        } AS node
        """
        result = await self.execute_query(query, {"user_id": user_id})
        nodes = [r["node"] for r in result]

        # Build edges from relationships
        edges = []
        for node in nodes:
            for rel in node.get("relationships", []):
                edges.append({
                    "source": node["id"],
                    "target": rel["target"],
                    "type": rel["type"],
                    "properties": rel.get("properties", {}),
                })

        return {
            "nodes": nodes,
            "edges": edges,
        }

    async def link_note_to_concepts(
        self,
        note_id: str,
        concept_ids: list[str],
        summary: str,
        user_id: str,
    ) -> dict:
        """Create a NoteSource node and link it to concepts."""
        # Create NoteSource
        create_query = """
        MERGE (n:NoteSource {id: $note_id, user_id: $user_id})
        ON CREATE SET
            n.note_id = $note_id,
            n.summary = $summary,
            n.created_at = datetime()
        ON MATCH SET
            n.summary = $summary,
            n.updated_at = datetime()
        RETURN n
        """
        await self.execute_query(
            create_query, {"note_id": note_id, "summary": summary, "user_id": user_id}
        )

        # Link to concepts
        link_query = """
        MATCH (n:NoteSource {id: $note_id, user_id: $user_id})
        MATCH (c:Concept {id: $concept_id, user_id: $user_id})
        MERGE (n)-[r:EXPLAINS]->(c)
        SET r.relevance = 1.0
        RETURN n.id AS note_id, c.name AS concept_name
        """

        links = []
        for concept_id in concept_ids:
            result = await self.execute_query(
                link_query,
                {"note_id": note_id, "concept_id": concept_id, "user_id": user_id},
            )
            if result:
                links.append(result[0])

        return {"note_id": note_id, "linked_concepts": links}


# Global client instance
_neo4j_client: Optional[Neo4jClient] = None
_client_lock = asyncio.Lock()


async def get_neo4j_client() -> Neo4jClient:
    """Get or create the global Neo4j client instance."""
    global _neo4j_client

    async with _client_lock:
        if _neo4j_client is None:
            _neo4j_client = Neo4jClient()
            await _neo4j_client.initialize()

    return _neo4j_client


async def close_neo4j_client() -> None:
    """Close the global Neo4j client."""
    global _neo4j_client

    async with _client_lock:
        if _neo4j_client:
            await _neo4j_client.close()
            _neo4j_client = None
