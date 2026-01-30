"""Agent 3: Graph Builder Agent - Updates the Neo4j knowledge graph."""

import time
from typing import Any, Optional
from uuid import uuid4

import structlog
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from backend.db.neo4j_client import get_neo4j_client
from backend.models.schemas import (
    Conflict,
    ConflictDecision,
    GraphOperation,
    GraphOperationType,
    MergeStrategy,
    RelationshipType,
)

logger = structlog.get_logger()


class GraphBuilderAgent:
    """
    Agent 3: Graph Builder Agent.

    Responsible for creating and updating the Neo4j knowledge graph
    based on extracted concepts and synthesis decisions.

    This agent:
    1. Creates new Concept nodes
    2. Establishes relationships (PREREQUISITE_OF, RELATED_TO, BUILDS_ON)
    3. Links concepts to their source notes
    4. Handles merge operations for enhanced concepts
    """

    def __init__(
        self,
        embedding_model: str = "text-embedding-3-small",
    ):
        self.embeddings = OpenAIEmbeddings(model=embedding_model)

    async def _get_embedding(self, text: str) -> list[float]:
        """Get embedding vector for text."""
        return await self.embeddings.aembed_query(text)

    async def build(
        self,
        concepts: list[dict],
        conflicts: Optional[list[dict]] = None,
        note_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Build/update the knowledge graph with extracted concepts.

        Args:
            concepts: List of extracted concepts
            conflicts: Optional list of conflict decisions
            note_id: Optional note ID to link concepts to

        Returns:
            Dict with statistics about the operations performed
        """
        start_time = time.time()

        logger.info(
            "GraphBuilderAgent: Building graph",
            num_concepts=len(concepts),
            num_conflicts=len(conflicts) if conflicts else 0,
        )

        neo4j = await get_neo4j_client()

        concepts_created = 0
        concepts_updated = 0
        relationships_created = 0

        # Build a conflict lookup for faster access
        conflict_map = {}
        if conflicts:
            for c in conflicts:
                name = c.get("new_concept_name", "")
                conflict_map[name] = c

        # Process each concept
        concept_ids = []
        for concept in concepts:
            try:
                name = concept.get("name", "")
                conflict = conflict_map.get(name, {})
                decision = conflict.get("decision", ConflictDecision.NEW.value)
                strategy = conflict.get("merge_strategy", MergeStrategy.CREATE_NEW.value)

                # Handle based on merge strategy
                if strategy == MergeStrategy.SKIP.value:
                    # Skip duplicates
                    matched_id = conflict.get("matched_concept_id")
                    if matched_id:
                        concept_ids.append(matched_id)
                    logger.debug("GraphBuilderAgent: Skipping duplicate", name=name)
                    continue

                # Create or update the concept
                concept_id = concept.get("id") or str(uuid4())

                # Get embedding for the concept
                concept_text = f"{name}: {concept.get('definition', '')}"
                embedding = await self._get_embedding(concept_text)

                # Determine the definition to use
                definition = concept.get("definition", "")
                if strategy == MergeStrategy.MERGE.value:
                    updated_def = conflict.get("updated_definition")
                    if updated_def:
                        definition = updated_def

                # Create/update the concept in Neo4j
                await neo4j.create_concept(
                    concept_id=concept_id,
                    name=name,
                    definition=definition,
                    domain=concept.get("domain", "General"),
                    complexity_score=float(concept.get("complexity_score", 5.0)),
                    embedding=embedding,
                )

                concept_ids.append(concept_id)

                if decision == ConflictDecision.NEW.value or strategy == MergeStrategy.CREATE_NEW.value:
                    concepts_created += 1
                else:
                    concepts_updated += 1

                logger.debug(
                    "GraphBuilderAgent: Processed concept",
                    name=name,
                    id=concept_id,
                    decision=decision,
                )

            except Exception as e:
                logger.error(
                    "GraphBuilderAgent: Error processing concept",
                    name=concept.get("name"),
                    error=str(e),
                )

        # Create relationships between concepts
        relationships_created = await self._create_relationships(
            neo4j, concepts, concept_ids
        )

        # Link concepts to the source note
        if note_id and concept_ids:
            try:
                summary = self._generate_note_summary(concepts)
                await neo4j.link_note_to_concepts(
                    note_id=note_id,
                    concept_ids=concept_ids,
                    summary=summary,
                )
                logger.info(
                    "GraphBuilderAgent: Linked note to concepts",
                    note_id=note_id,
                    num_concepts=len(concept_ids),
                )
            except Exception as e:
                logger.error(
                    "GraphBuilderAgent: Error linking note",
                    note_id=note_id,
                    error=str(e),
                )

        processing_time = (time.time() - start_time) * 1000

        logger.info(
            "GraphBuilderAgent: Build complete",
            concepts_created=concepts_created,
            concepts_updated=concepts_updated,
            relationships_created=relationships_created,
            processing_time_ms=processing_time,
        )

        return {
            "concepts_created": concepts_created,
            "concepts_updated": concepts_updated,
            "relationships_created": relationships_created,
            "concept_ids": concept_ids,
            "processing_time_ms": processing_time,
        }

    async def _create_relationships(
        self,
        neo4j,
        concepts: list[dict],
        concept_ids: list[str],
    ) -> int:
        """
        Create relationships between concepts.

        Relationships are created based on:
        1. Prerequisites defined in the concepts
        2. Related concepts defined in the concepts
        3. Domain-based relationships
        """
        relationships_created = 0

        # Build a name->id lookup
        name_to_id = {}
        for concept, concept_id in zip(concepts, concept_ids):
            name_to_id[concept.get("name", "").lower()] = concept_id

        for concept, concept_id in zip(concepts, concept_ids):
            # Create PREREQUISITE_OF relationships
            for prereq in concept.get("prerequisites", []):
                prereq_lower = prereq.lower()
                if prereq_lower in name_to_id:
                    prereq_id = name_to_id[prereq_lower]
                    try:
                        await neo4j.create_relationship(
                            from_concept_id=prereq_id,
                            to_concept_id=concept_id,
                            relationship_type="PREREQUISITE_OF",
                            properties={"created_by": "auto"},
                        )
                        relationships_created += 1
                    except Exception as e:
                        logger.debug(
                            "GraphBuilderAgent: Prerequisite relationship exists or failed",
                            from_concept=prereq,
                            to_concept=concept.get("name"),
                            error=str(e),
                        )

            # Create RELATED_TO relationships
            for related in concept.get("related_concepts", []):
                related_lower = related.lower()
                if related_lower in name_to_id and related_lower != concept.get("name", "").lower():
                    related_id = name_to_id[related_lower]
                    try:
                        await neo4j.create_relationship(
                            from_concept_id=concept_id,
                            to_concept_id=related_id,
                            relationship_type="RELATED_TO",
                            properties={"strength": 0.8, "created_by": "auto"},
                        )
                        relationships_created += 1
                    except Exception as e:
                        logger.debug(
                            "GraphBuilderAgent: Related relationship exists or failed",
                            from_concept=concept.get("name"),
                            to_concept=related,
                            error=str(e),
                        )

        return relationships_created

    def _generate_note_summary(self, concepts: list[dict]) -> str:
        """Generate a summary of the note based on extracted concepts."""
        concept_names = [c.get("name", "") for c in concepts[:5]]
        return f"Note covering: {', '.join(concept_names)}"

    async def get_existing_concepts(
        self,
        limit: int = 100,
    ) -> list[dict]:
        """
        Get existing concepts from the graph for conflict detection.

        Returns:
            List of existing concept dictionaries
        """
        neo4j = await get_neo4j_client()

        query = """
        MATCH (c:Concept)
        RETURN c.id AS id, c.name AS name, c.definition AS definition, 
               c.domain AS domain, c.complexity_score AS complexity_score
        ORDER BY c.created_at DESC
        LIMIT $limit
        """

        try:
            results = await neo4j.execute_query(query, {"limit": limit})
            return results
        except Exception as e:
            logger.error(
                "GraphBuilderAgent: Error fetching existing concepts",
                error=str(e),
            )
            return []
