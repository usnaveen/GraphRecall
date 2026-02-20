"""Concepts Router - Delete, merge concepts and related data."""

import json
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from backend.auth.middleware import get_current_user
from backend.db.postgres_client import get_postgres_client
from backend.db.neo4j_client import get_neo4j_client
from backend.services.ingestion.embedding_service import EmbeddingService

logger = structlog.get_logger()

router = APIRouter(prefix="/api/concepts", tags=["Concepts"])

embedding_service = EmbeddingService()


@router.delete("/{concept_id}")
async def delete_concept(
    concept_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a concept and its related data for the current user."""
    try:
        user_id = str(current_user["id"])
        neo4j = await get_neo4j_client()

        # Verify concept exists
        result = await neo4j.execute_query(
            "MATCH (c:Concept {id: $id, user_id: $user_id}) RETURN c.id AS id",
            {"id": concept_id, "user_id": user_id},
        )
        if not result:
            raise HTTPException(status_code=404, detail="Concept not found")

        # Delete concept node + relationships
        await neo4j.execute_query(
            "MATCH (c:Concept {id: $id, user_id: $user_id}) DETACH DELETE c",
            {"id": concept_id, "user_id": user_id},
        )

        # Clean up related relational data
        pg_client = await get_postgres_client()
        await pg_client.execute_update(
            "DELETE FROM proficiency_scores WHERE user_id = :user_id AND concept_id = :concept_id",
            {"user_id": user_id, "concept_id": concept_id},
        )
        await pg_client.execute_update(
            "DELETE FROM flashcards WHERE user_id = :user_id AND concept_id = :concept_id",
            {"user_id": user_id, "concept_id": concept_id},
        )
        await pg_client.execute_update(
            "DELETE FROM quizzes WHERE user_id = :user_id AND concept_id = :concept_id",
            {"user_id": user_id, "concept_id": concept_id},
        )
        await pg_client.execute_update(
            "DELETE FROM generated_content WHERE user_id = :user_id AND concept_id = :concept_id",
            {"user_id": user_id, "concept_id": concept_id},
        )
        await pg_client.execute_update(
            "DELETE FROM study_sessions WHERE user_id = :user_id AND concept_id = :concept_id",
            {"user_id": user_id, "concept_id": concept_id},
        )
        await pg_client.execute_update(
            """
            UPDATE user_uploads
            SET linked_concepts = array_remove(linked_concepts, :concept_id)
            WHERE user_id = :user_id
            """,
            {"user_id": user_id, "concept_id": concept_id},
        )

        return {"status": "deleted", "concept_id": concept_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Concepts: Error deleting concept", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Merge Concepts
# ---------------------------------------------------------------------------

class MergeRequest(BaseModel):
    source_ids: List[str]
    target_id: str


@router.post("/merge")
async def merge_concepts(
    request: MergeRequest,
    current_user: dict = Depends(get_current_user),
):
    """Merge multiple source concepts into a target concept.

    - All relationships from source nodes are transferred to the target.
    - Definitions are combined if the target's is shorter.
    - Source nodes are deleted after merge.
    """
    try:
        user_id = str(current_user["id"])
        neo4j = await get_neo4j_client()
        pg_client = await get_postgres_client()

        if request.target_id in request.source_ids:
            raise HTTPException(
                status_code=400, detail="Target cannot be in source_ids"
            )

        # Verify target exists
        target = await neo4j.execute_query(
            "MATCH (c:Concept {id: $id, user_id: $uid}) RETURN c",
            {"id": request.target_id, "uid": user_id},
        )
        if not target:
            raise HTTPException(status_code=404, detail="Target concept not found")

        merged_count = 0
        for source_id in request.source_ids:
            # Verify source exists
            source = await neo4j.execute_query(
                "MATCH (c:Concept {id: $id, user_id: $uid}) RETURN c",
                {"id": source_id, "uid": user_id},
            )
            if not source:
                continue

            # Transfer outgoing relationships (source)-[r]->(other) to (target)-[r]->(other)
            # Using pure Cypher per rel type (AuraDB has no APOC)
            _KNOWN_REL_TYPES = [
                "PREREQUISITE_OF", "RELATED_TO", "SUBTOPIC_OF", "BUILDS_ON", "PART_OF"
            ]
            outgoing_rels = await neo4j.execute_query(
                """
                MATCH (src:Concept {id: $src_id, user_id: $uid})-[r]->(other)
                WHERE other.id <> $tgt_id
                RETURN type(r) AS rtype, properties(r) AS props, other.id AS other_id
                """,
                {"src_id": source_id, "tgt_id": request.target_id, "uid": user_id},
            )
            for row in (outgoing_rels or []):
                rtype = row.get("rtype", "")
                if rtype not in _KNOWN_REL_TYPES:
                    continue
                other_id = row.get("other_id")
                props = row.get("props") or {}
                query = f"""
                MATCH (tgt:Concept {{id: $tgt_id, user_id: $uid}})
                MATCH (other {{id: $other_id}})
                MERGE (tgt)-[r:{rtype}]->(other)
                SET r += $props
                """
                await neo4j.execute_query(
                    query,
                    {"tgt_id": request.target_id, "uid": user_id, "other_id": other_id, "props": props},
                )
            # Delete source outgoing rels
            await neo4j.execute_query(
                """
                MATCH (src:Concept {id: $src_id, user_id: $uid})-[r]->()
                WHERE NOT type(r) = 'EXPLAINS'
                DELETE r
                """,
                {"src_id": source_id, "uid": user_id},
            )

            # Transfer incoming relationships (other)-[r]->(source) to (other)-[r]->(target)
            incoming_rels = await neo4j.execute_query(
                """
                MATCH (other)-[r]->(src:Concept {id: $src_id, user_id: $uid})
                WHERE other.id <> $tgt_id
                RETURN type(r) AS rtype, properties(r) AS props, other.id AS other_id
                """,
                {"src_id": source_id, "tgt_id": request.target_id, "uid": user_id},
            )
            for row in (incoming_rels or []):
                rtype = row.get("rtype", "")
                if rtype not in _KNOWN_REL_TYPES:
                    continue
                other_id = row.get("other_id")
                props = row.get("props") or {}
                query = f"""
                MATCH (other {{id: $other_id}})
                MATCH (tgt:Concept {{id: $tgt_id, user_id: $uid}})
                MERGE (other)-[r:{rtype}]->(tgt)
                SET r += $props
                """
                await neo4j.execute_query(
                    query,
                    {"other_id": other_id, "tgt_id": request.target_id, "uid": user_id, "props": props},
                )
            # Delete source incoming rels
            await neo4j.execute_query(
                """
                MATCH ()-[r]->(src:Concept {id: $src_id, user_id: $uid})
                WHERE NOT type(r) = 'EXPLAINS'
                DELETE r
                """,
                {"src_id": source_id, "uid": user_id},
            )

            # Transfer NoteSource EXPLAINS relationships
            await neo4j.execute_query(
                """
                MATCH (n:NoteSource)-[r:EXPLAINS]->(src:Concept {id: $src_id, user_id: $uid})
                MATCH (tgt:Concept {id: $tgt_id, user_id: $uid})
                MERGE (n)-[r2:EXPLAINS]->(tgt)
                ON CREATE SET r2.relevance = r.relevance
                DELETE r
                """,
                {"src_id": source_id, "tgt_id": request.target_id, "uid": user_id},
            )

            # Combine definitions: keep the longer one
            source_def = source[0]["c"].get("definition", "")
            target_def = target[0]["c"].get("definition", "")
            if source_def and len(source_def) > len(target_def or ""):
                await neo4j.execute_query(
                    "MATCH (c:Concept {id: $id, user_id: $uid}) SET c.definition = $def",
                    {"id": request.target_id, "uid": user_id, "def": source_def},
                )

            # Delete source concept node
            await neo4j.execute_query(
                "MATCH (c:Concept {id: $id, user_id: $uid}) DETACH DELETE c",
                {"id": source_id, "uid": user_id},
            )

            # Migrate PostgreSQL references
            for table in ["proficiency_scores", "flashcards", "quizzes", "generated_content", "study_sessions"]:
                await pg_client.execute_update(
                    f"UPDATE {table} SET concept_id = :tgt_id WHERE user_id = :uid AND concept_id = :src_id",
                    {"tgt_id": request.target_id, "uid": user_id, "src_id": source_id},
                )

            merged_count += 1

        logger.info("Concepts: Merged", merged=merged_count, target=request.target_id)
        return {
            "status": "merged",
            "target_id": request.target_id,
            "merged_count": merged_count,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Concepts: Error merging", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Get Notes/Chunks for a Concept
# ---------------------------------------------------------------------------

@router.get("/{concept_id}/notes")
async def get_concept_notes(
    concept_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get notes and chunks linked to a concept via NoteSource EXPLAINS relationship."""
    try:
        user_id = str(current_user["id"])
        neo4j = await get_neo4j_client()
        pg_client = await get_postgres_client()

        # Get linked note IDs from Neo4j
        note_links = await neo4j.execute_query(
            """
            MATCH (n:NoteSource)-[r:EXPLAINS]->(c:Concept {id: $id, user_id: $uid})
            RETURN n.id AS note_id, r.relevance AS relevance, r.evidence_span AS evidence_span
            ORDER BY r.relevance DESC
            """,
            {"id": concept_id, "uid": user_id},
        )

        if not note_links:
            return {"notes": []}

        note_ids = [r["note_id"] for r in note_links]
        note_link_map = {r["note_id"]: r for r in note_links}

        # Get note metadata
        notes_result = await pg_client.execute_query(
            """
            SELECT id, title, resource_type, created_at
            FROM notes
            WHERE id = ANY(:note_ids) AND user_id = :uid
            """,
            {"note_ids": note_ids, "uid": user_id},
        )

        # Get the concept title to use as fallback matching
        concept_res = await neo4j.execute_query(
            "MATCH (c:Concept {id: $id}) RETURN c.title AS title",
            {"id": concept_id}
        )
        concept_title = concept_res[0]["title"] if concept_res else ""

        notes = []
        for note_row in notes_result or []:
            note = dict(note_row)
            note_id = note["id"]
            evidence_span = note_link_map.get(note_id, {}).get("evidence_span")

            # Get chunks for this note, ordered by index
            chunks_query = """
                SELECT c.id, c.content, c.chunk_level, c.chunk_index,
                       c.page_start, c.page_end, c.images,
                       p.content as parent_content
                FROM chunks c
                LEFT JOIN chunks p ON c.parent_chunk_id = p.id
                WHERE c.note_id = :note_id
            """
            
            chunks_result = await pg_client.execute_query(
                chunks_query + "\nORDER BY c.chunk_level DESC, c.chunk_index",
                {"note_id": note_id},
            )

            chunks = []
            matched_evidence = False
            for chunk_row in chunks_result or []:
                chunk = dict(chunk_row)
                images = chunk.get("images")
                if isinstance(images, str):
                    try:
                        images = json.loads(images)
                    except Exception:
                        images = []
                chunk["images"] = images or []
                
                # Filter logic: if evidence_span exists, show the chunk that contains it.
                # If evidence_span is missing, show chunks that mention the concept title!
                has_images = len(chunk["images"]) > 0
                is_match = False
                
                if evidence_span and chunk["content"] and evidence_span.lower()[:50] in chunk["content"].lower():
                    is_match = True
                    matched_evidence = True
                elif not evidence_span and concept_title and chunk["content"] and concept_title.lower() in chunk["content"].lower():
                    is_match = True
                    matched_evidence = True
                    
                if has_images or is_match:
                    chunks.append(chunk)

            # If we had an evidence span but didn't match any chunk, prepend it as a synthetic chunk
            if evidence_span and not matched_evidence:
                synthetic_chunk = {
                    "id": f"evidence-{note_id}",
                    "content": evidence_span,
                    "chunk_level": "parent",
                    "chunk_index": -1,
                    "images": []
                }
                chunks.insert(0, synthetic_chunk)
                
            # Limit chunks to avoid freezing the UI for book type notes if not using evidence span
            if not evidence_span and len(chunks) > 20:
                chunks = chunks[:20]

            notes.append({
                "id": note_id,
                "title": note["title"],
                "resource_type": note.get("resource_type"),
                "evidence_span": evidence_span,
                "chunks": chunks,
            })

        return {"notes": notes}
    except Exception as e:
        logger.error("Concepts: Error getting notes", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Backfill Missing Embeddings
# ---------------------------------------------------------------------------

@router.post("/backfill-embeddings")
async def backfill_embeddings(
    current_user: dict = Depends(get_current_user),
):
    """Find chunks missing embeddings and generate them."""
    try:
        user_id = str(current_user["id"])
        pg_client = await get_postgres_client()

        # Find child chunks without embeddings
        missing = await pg_client.execute_query(
            """
            SELECT c.id, c.content
            FROM chunks c
            JOIN notes n ON c.note_id = n.id
            WHERE n.user_id = :uid
              AND c.chunk_level = 'child'
              AND c.embedding IS NULL
            ORDER BY c.created_at
            LIMIT 200
            """,
            {"uid": user_id},
        )

        if not missing:
            return {"status": "ok", "message": "No chunks missing embeddings", "backfilled": 0}

        texts = [row["content"] for row in missing]
        ids = [row["id"] for row in missing]

        embeddings = await embedding_service.embed_batch(texts)

        updated = 0
        for chunk_id, emb in zip(ids, embeddings):
            if emb:
                embedding_literal = "[" + ",".join(str(x) for x in emb) + "]"
                await pg_client.execute_update(
                    """
                    UPDATE chunks SET embedding = cast(:emb as vector)
                    WHERE id = :id
                    """,
                    {"id": chunk_id, "emb": embedding_literal},
                )
                updated += 1

        logger.info("Backfill: Complete", total_missing=len(missing), updated=updated)
        return {
            "status": "ok",
            "total_missing": len(missing),
            "backfilled": updated,
            "still_missing": len(missing) - updated,
        }
    except Exception as e:
        logger.error("Backfill: Error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
