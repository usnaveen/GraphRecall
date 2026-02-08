"""Full-pipeline book ingestion for GraphRecall.

This script mirrors the complete ingestion pipeline that notes go through
when uploaded via the UI (ingestion_graph.py), but optimized for bulk book
ingestion with image-aware chunking.

Pipeline stages:
1. Chunk — Rule-based markdown chunking with image/caption pairing & 15% overlap
2. Embed — Generate vector embeddings via Google Gemini (free tier) or local model
3. Store — Insert note + parent/child chunk rows into PostgreSQL
4. Extract — Batch concept extraction to Neo4j (with parent_topic/subtopics)
5. Consolidate — Second pass: discover cross-chunk relationships (Microsoft GraphRAG)
6. Relationships — Create RELATED_TO, PREREQUISITE_OF, SUBTOPIC_OF, PART_OF edges
7. Flashcards — Generate cloze-deletion flashcards per concept
8. Quizzes — Generate MCQ quizzes per concept

This ensures ingested books produce the SAME output as notes uploaded through
the UI: embeddings, knowledge graph, flashcards, and quizzes.

Usage:
  python scripts/ingest_book.py \\
      --md-path "sample_content/book/book.md" \\
      --images-dir "sample_content/book/images" \\
      --note-title "My Book" --image-base-url /api/images

  # Skip only LLM-dependent stages (embeddings still generated):
  python scripts/ingest_book.py --md-path ... --images-dir ... --skip-concepts

  # Full dry run (parse only):
  python scripts/ingest_book.py --md-path ... --images-dir ... --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Iterable, List, Optional
from pathlib import Path

import structlog

from backend.services.book_chunker import BookChunker, Chunk
from backend.services.ingestion.embedding_service import EmbeddingService
from backend.agents.extraction import ExtractionAgent
from backend.agents.content_generator import ContentGeneratorAgent
from backend.db.postgres_client import get_postgres_client
from backend.db.neo4j_client import get_neo4j_client
from backend.services.storage_service import get_storage_service
from backend.models.schemas import ConceptCreate

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Optional local embeddings
# ---------------------------------------------------------------------------

class _LocalEmbedder:
    """Thin wrapper over sentence-transformers if available."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise ImportError(
                "sentence-transformers not installed; run `pip install sentence-transformers` or omit --local-embeddings"
            ) from e
        self.model = SentenceTransformer(model_name)

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        loop = asyncio.get_running_loop()

        def _encode():
            return self.model.encode(texts, convert_to_numpy=True).tolist()

        return await loop.run_in_executor(None, _encode)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Full-pipeline book ingestion for GraphRecall"
    )
    parser.add_argument("--md-path", required=True, help="Path to OCR-parsed markdown file")
    parser.add_argument("--images-dir", required=True, help="Directory containing figure images")
    parser.add_argument("--note-title", default=None, help="Title for the note record")
    parser.add_argument("--note-id", default=None, help="Existing note UUID to reuse")
    parser.add_argument("--user-id", default="default_user", help="User ID owner for the note/chunks")
    parser.add_argument("--chunk-size", type=int, default=1400, help="Max chars per chunk")
    parser.add_argument("--overlap", type=float, default=0.15, help="Chunk overlap ratio (default 0.15)")
    parser.add_argument("--image-base-url", default="/api/images", help="Base URL for chunk image metadata")
    parser.add_argument("--upload-images", action="store_true", help="Upload images via StorageService (S3/Supabase)")
    parser.add_argument("--local-embeddings", action="store_true", help="Use sentence-transformers locally")
    parser.add_argument("--skip-embeddings", action="store_true", help="Skip embedding generation")
    parser.add_argument("--skip-concepts", action="store_true", help="Skip concept extraction, consolidation, flashcards, and quizzes")
    parser.add_argument("--skip-flashcards", action="store_true", help="Skip flashcard generation only")
    parser.add_argument("--skip-quizzes", action="store_true", help="Skip quiz generation only")
    parser.add_argument("--concept-batch-size", type=int, default=10, help="Number of chunks per extraction call")
    parser.add_argument("--mcq-per-concept", type=int, default=2, help="Number of MCQs to generate per concept")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report without writing to DB")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------

async def _upload_images(images_dir: str, filenames: Iterable[str], user_id: str) -> dict[str, str]:
    """Upload images to cloud storage and return filename->URL map."""
    storage = get_storage_service()
    url_map: dict[str, str] = {}
    for name in filenames:
        path = os.path.join(images_dir, name)
        if not os.path.exists(path):
            logger.warning("Image file not found, skipping", path=path)
            continue
        with open(path, "rb") as f:
            data = f.read()
        content_type = "image/png" if name.lower().endswith("png") else "image/jpeg"
        url = await storage.upload_file(data, name, content_type, user_id)
        url_map[name] = url
    return url_map


async def _embed_texts(texts: List[str], use_local: bool, skip: bool) -> List[Optional[List[float]]]:
    """Generate embeddings for a list of texts."""
    if skip:
        return [None] * len(texts)

    if use_local:
        embedder = _LocalEmbedder()
        embeddings = await embedder.embed_batch(texts)
        return [emb.tolist() if hasattr(emb, "tolist") else emb for emb in embeddings]

    service = EmbeddingService()
    embeddings = await service.embed_batch(texts)
    if not embeddings:
        logger.warning("Embedding service returned no embeddings; continuing without")
        return [None] * len(texts)
    return embeddings


async def _insert_note(pg_client, note_id: str, user_id: str, title: str, raw_text: str):
    """Insert or update the note record."""
    await pg_client.execute_insert(
        """
        INSERT INTO notes (id, user_id, title, content_text, created_at, updated_at)
        VALUES (:id, :user_id, :title, :content_text, NOW(), NOW())
        ON CONFLICT (id) DO UPDATE SET
            title = EXCLUDED.title,
            content_text = EXCLUDED.content_text,
            updated_at = NOW()
        """,
        {"id": note_id, "user_id": user_id, "title": title, "content_text": raw_text},
    )


async def _insert_chunks(
    pg_client,
    note_id: str,
    chunks: List[Chunk],
    embeddings: List[Optional[List[float]]],
    image_url_map: dict[str, str],
    image_base_url: str,
) -> int:
    """Insert parent+child chunk rows into PostgreSQL."""
    inserted = 0
    for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        parent_id = str(uuid.uuid4())
        child_id = str(uuid.uuid4())

        images_json = []
        for img in chunk.images:
            url = image_url_map.get(img.filename) or f"{image_base_url.rstrip('/')}/{img.filename}"
            images_json.append({
                "filename": img.filename,
                "caption": img.caption,
                "page": img.page,
                "url": url,
            })

        source_location = {
            "headings": chunk.headings,
            "page": chunk.images[0].page if chunk.images else None,
        }

        # Parent chunk (no embedding)
        await pg_client.execute_update(
            """
            INSERT INTO chunks (id, note_id, content, chunk_level, chunk_index, source_location, images, created_at)
            VALUES (:id, :note_id, :content, 'parent', :idx, :source_location::jsonb, :images::jsonb, NOW())
            ON CONFLICT (id) DO NOTHING
            """,
            {
                "id": parent_id,
                "note_id": note_id,
                "content": chunk.text,
                "idx": idx,
                "source_location": json.dumps(source_location),
                "images": json.dumps(images_json),
            },
        )

        # Child chunk (with embedding for vector search)
        # Format embedding as pgvector literal: [0.1,0.2,...]
        emb_str = None
        if emb is not None:
            emb_str = "[" + ",".join(str(v) for v in emb) + "]"

        await pg_client.execute_update(
            """
            INSERT INTO chunks (id, note_id, parent_chunk_id, content, chunk_level, chunk_index, source_location, images, embedding, created_at)
            VALUES (:id, :note_id, :parent_id, :content, 'child', 0, :source_location::jsonb, :images::jsonb, :embedding, NOW())
            ON CONFLICT (id) DO NOTHING
            """,
            {
                "id": child_id,
                "note_id": note_id,
                "parent_id": parent_id,
                "content": chunk.text,
                "source_location": json.dumps(source_location),
                "images": json.dumps(images_json),
                "embedding": emb_str,
            },
        )

        inserted += 2
    return inserted


# ---------------------------------------------------------------------------
# Stage 4: Concept extraction (batch)
# ---------------------------------------------------------------------------

async def _batch_extract_concepts(
    chunks: List[Chunk],
    batch_size: int,
    existing_concepts: list[str],
) -> List[ConceptCreate]:
    """Extract concepts from chunks in batches, returning all ConceptCreate objects."""
    agent = ExtractionAgent(temperature=0.2)
    all_concepts: List[ConceptCreate] = []

    for start in range(0, len(chunks), batch_size):
        batch = chunks[start: start + batch_size]
        combined = "\n\n---\n\n".join(c.text for c in batch)

        try:
            if existing_concepts:
                result = await agent.extract_with_context(combined, existing_concepts)
            else:
                result = await agent.extract(combined)

            all_concepts.extend(result.concepts)
            # Update running list of known concept names for context-aware extraction
            for c in result.concepts:
                if c.name not in existing_concepts:
                    existing_concepts.append(c.name)

            logger.info(
                "Concept extraction batch",
                batch_start=start,
                batch_size=len(batch),
                concepts_found=len(result.concepts),
            )
        except Exception as e:
            logger.error("Concept extraction batch failed", batch_start=start, error=str(e))

    # Deduplicate by name (keep first occurrence)
    seen: set[str] = set()
    deduped: List[ConceptCreate] = []
    for c in all_concepts:
        key = c.name.lower().strip()
        if key not in seen:
            seen.add(key)
            deduped.append(c)

    logger.info("Concept extraction complete", total=len(deduped), raw=len(all_concepts))
    return deduped


# ---------------------------------------------------------------------------
# Stage 5 & 6: Create concepts in Neo4j with relationships
# ---------------------------------------------------------------------------

async def _create_concepts_and_relationships(
    concepts: List[ConceptCreate],
    note_id: str,
    user_id: str,
    book_title: str,
) -> tuple[list[str], dict[str, str]]:
    """
    Create concept nodes in Neo4j, establish relationships, and run
    cross-chunk consolidation pass.

    Returns:
        (concept_ids, name_to_id mapping)
    """
    neo4j = await get_neo4j_client()
    agent = ExtractionAgent(temperature=0.2)

    concept_ids: list[str] = []
    name_to_id: dict[str, str] = {}

    # --- Create concept nodes ---
    for concept in concepts:
        try:
            result_node = await neo4j.create_concept(
                name=concept.name,
                definition=concept.definition,
                domain=concept.domain,
                complexity_score=float(concept.complexity_score),
                user_id=user_id,
                concept_id=None,
            )
            node_data = result_node.get("c", result_node) if isinstance(result_node, dict) else {}
            cid = node_data.get("id") if hasattr(node_data, "get") else None
            if cid:
                concept_ids.append(cid)
                name_to_id[concept.name.lower()] = cid
            else:
                concept_ids.append(concept.name)
                name_to_id[concept.name.lower()] = concept.name
        except Exception as e:
            logger.error("Failed to create concept", concept=concept.name, error=str(e))
            concept_ids.append(concept.name)
            name_to_id[concept.name.lower()] = concept.name

    # Also fetch ALL existing user concepts for cross-note linking
    try:
        existing = await neo4j.execute_query(
            "MATCH (c:Concept) WHERE c.user_id = $user_id RETURN c.id AS id, c.name AS name",
            {"user_id": user_id},
        )
        for c in existing:
            if c.get("name"):
                name_to_id.setdefault(c["name"].lower(), c["id"])
    except Exception:
        pass

    # --- Create per-concept relationships ---
    rels_created = 0
    for concept, cid in zip(concepts, concept_ids):
        # RELATED_TO
        for related_name in concept.related_concepts:
            r_name = related_name if isinstance(related_name, str) else related_name.get("name", "")
            r_id = name_to_id.get(r_name.lower())
            if r_id and r_id != cid:
                try:
                    await neo4j.create_relationship(cid, r_id, "RELATED_TO", user_id, {"strength": 0.8, "source": "extraction"})
                    rels_created += 1
                except Exception:
                    pass

        # PREREQUISITE_OF
        for prereq_name in concept.prerequisites:
            p_name = prereq_name if isinstance(prereq_name, str) else prereq_name.get("name", "")
            p_id = name_to_id.get(p_name.lower())
            if p_id and p_id != cid:
                try:
                    await neo4j.create_relationship(p_id, cid, "PREREQUISITE_OF", user_id, {"strength": 0.9, "source": "extraction"})
                    rels_created += 1
                except Exception:
                    pass

        # SUBTOPIC_OF (child -> parent)
        if concept.parent_topic:
            parent_id = name_to_id.get(concept.parent_topic.lower())
            if parent_id and parent_id != cid:
                try:
                    await neo4j.create_relationship(cid, parent_id, "SUBTOPIC_OF", user_id, {"strength": 1.0, "source": "extraction"})
                    rels_created += 1
                except Exception:
                    pass

        # PART_OF (subtopics -> this concept, stored as SUBTOPIC_OF for consistency)
        for sub_name in concept.subtopics:
            s_id = name_to_id.get(sub_name.lower())
            if s_id and s_id != cid:
                try:
                    await neo4j.create_relationship(s_id, cid, "SUBTOPIC_OF", user_id, {"strength": 1.0, "source": "extraction"})
                    rels_created += 1
                except Exception:
                    pass

    logger.info("Per-concept relationships created", count=rels_created)

    # --- Link note to concepts ---
    for cid in concept_ids:
        try:
            await neo4j.execute_query(
                """
                MERGE (n:NoteSource {id: $note_id})
                WITH n
                MATCH (c:Concept {id: $concept_id})
                MERGE (n)-[r:EXPLAINS]->(c)
                SET r.relevance = 0.9
                """,
                {"note_id": note_id, "concept_id": cid},
            )
        except Exception:
            pass

    # --- Stage 5: Consolidation pass (cross-chunk relationship discovery) ---
    logger.info("Starting consolidation pass (Microsoft GraphRAG second pass)...")
    try:
        consolidated_rels = await agent.consolidate_relationships(concepts, book_title)
        consolidated_created = 0
        for rel in consolidated_rels:
            from_name = rel.get("from_concept", "").lower()
            to_name = rel.get("to_concept", "").lower()
            rel_type = rel.get("type", "RELATED_TO").upper()

            # Validate relationship type
            valid_types = {"RELATED_TO", "PREREQUISITE_OF", "SUBTOPIC_OF", "PART_OF", "BUILDS_ON"}
            if rel_type not in valid_types:
                rel_type = "RELATED_TO"

            from_id = name_to_id.get(from_name)
            to_id = name_to_id.get(to_name)

            if from_id and to_id and from_id != to_id:
                try:
                    await neo4j.create_relationship(
                        from_id, to_id, rel_type, user_id,
                        {"strength": 0.7, "source": "consolidation", "reason": rel.get("reason", "")[:200]}
                    )
                    consolidated_created += 1
                except Exception:
                    pass

        logger.info("Consolidation relationships created", count=consolidated_created)
    except Exception as e:
        logger.error("Consolidation pass failed", error=str(e))

    return concept_ids, name_to_id


# ---------------------------------------------------------------------------
# Stage 7: Flashcard generation
# ---------------------------------------------------------------------------

async def _generate_flashcards(
    concepts: List[ConceptCreate],
    concept_ids: list[str],
    note_id: str,
    user_id: str,
    raw_content: str,
) -> int:
    """Generate flashcards for extracted concepts."""
    content_gen = ContentGeneratorAgent(temperature=0.7)
    pg_client = await get_postgres_client()
    cards_created = 0

    concept_names = [c.name for c in concepts]

    # Generate cloze flashcards in batch using raw content
    prompt = f"""Generate flashcards from this note.

Content:
{raw_content[:3000]}

Key concepts:
{', '.join(concept_names[:20])}

Instructions:
1. Create 3-5 CLOZE DELETION flashcards
2. Hide important terms with [___]
3. Make context clear enough to answer
4. Focus on key facts and concepts

Return ONLY valid JSON:
{{
    "flashcards": [
        {{
            "front": "Text with [___] for the missing term",
            "back": "The missing term",
            "concept": "Related concept name"
        }}
    ]
}}
"""

    flashcards_dicts: list[dict] = []

    try:
        from backend.config.llm import get_chat_model
        llm = get_chat_model(temperature=0.7, json_mode=True)
        response = await llm.ainvoke(prompt)
        content = response.content.strip()

        if content.startswith("```json"):
            content = content.split("```json")[1].split("```")[0].strip()
        elif content.startswith("```"):
            content = content.split("```")[1].split("```")[0].strip()

        data = json.loads(content)
        flashcards_dicts = data.get("flashcards", [])
    except Exception as e:
        logger.error("Cloze flashcard generation failed", error=str(e))

    # Also generate concept-specific flashcards for the first 10 concepts
    for concept in concepts[:10]:
        try:
            cards = await content_gen.generate_flashcards(
                concept_name=concept.name,
                concept_definition=concept.definition,
                related_concepts=concept.related_concepts[:3],
                num_cards=2,
            )
            for card in cards:
                card["concept"] = concept.name
            flashcards_dicts.extend(cards)
        except Exception as e:
            logger.warning("Flashcard gen failed for concept", concept=concept.name, error=str(e))

    # Save to DB
    name_to_cid = {c.name.lower(): cid for c, cid in zip(concepts, concept_ids)}

    for card in flashcards_dicts:
        card_id = str(uuid.uuid4())
        concept_name = card.get("concept", "")
        concept_id = name_to_cid.get(concept_name.lower(), concept_name)

        try:
            await pg_client.execute_update(
                """
                INSERT INTO flashcards (id, user_id, concept_id, front_content, back_content,
                                        difficulty, source_note_ids, created_at)
                VALUES (:id, :user_id, :concept_id, :front_content, :back_content,
                        :difficulty, :source_note_ids, :created_at)
                """,
                {
                    "id": card_id,
                    "user_id": user_id,
                    "concept_id": concept_id,
                    "front_content": card.get("front") or card.get("question", ""),
                    "back_content": card.get("back") or card.get("answer", ""),
                    "difficulty": 0.5,
                    "source_note_ids": [note_id] if note_id else [],
                    "created_at": datetime.now(timezone.utc),
                },
            )
            cards_created += 1
        except Exception as e:
            logger.warning("Failed to insert flashcard", error=str(e))

    return cards_created


# ---------------------------------------------------------------------------
# Stage 8: Quiz generation
# ---------------------------------------------------------------------------

async def _generate_quizzes(
    concepts: List[ConceptCreate],
    concept_ids: list[str],
    user_id: str,
    mcq_per_concept: int = 2,
) -> int:
    """Generate MCQ quizzes for extracted concepts."""
    content_gen = ContentGeneratorAgent(temperature=0.7)
    pg_client = await get_postgres_client()

    # Prepare concept dicts for batch MCQ generation
    valid_concepts = []
    for concept, cid in zip(concepts, concept_ids):
        if concept.name and concept.definition:
            valid_concepts.append({
                "id": cid,
                "name": concept.name,
                "definition": concept.definition,
                "related_concepts": concept.related_concepts[:5],
                "complexity_score": concept.complexity_score,
                "propositions": [],  # No propositions in book ingestion
            })

    # Limit to first 15 concepts to avoid excessive LLM calls
    valid_concepts = valid_concepts[:15]

    if not valid_concepts:
        return 0

    try:
        mcqs = await content_gen.generate_mcq_batch(valid_concepts, num_per_concept=mcq_per_concept)

        quiz_ids = []
        for mcq in mcqs:
            q_id = str(uuid.uuid4())

            # Resolve concept_id
            concept_id = mcq.concept_id or "unknown"
            for vc in valid_concepts:
                if vc["name"] == mcq.concept_id:
                    concept_id = vc["id"]
                    break

            await pg_client.execute_update(
                """
                INSERT INTO quizzes (id, user_id, concept_id, question_text, question_type,
                                     options_json, correct_answer, explanation, created_at)
                VALUES (:id, :user_id, :concept_id, :question_text, 'mcq',
                        :options_json, :correct_answer, :explanation, :created_at)
                """,
                {
                    "id": q_id,
                    "user_id": user_id,
                    "concept_id": concept_id,
                    "question_text": mcq.question,
                    "options_json": json.dumps([o.model_dump() for o in mcq.options]),
                    "correct_answer": next((o.id for o in mcq.options if o.is_correct), "A"),
                    "explanation": mcq.explanation,
                    "created_at": datetime.now(timezone.utc),
                },
            )
            quiz_ids.append(q_id)

        logger.info("Quiz generation complete", count=len(quiz_ids))
        return len(quiz_ids)

    except Exception as e:
        logger.error("Quiz generation failed", error=str(e))
        return 0


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

async def main():
    args = _parse_args()

    md_path = os.path.expanduser(args.md_path)
    images_dir = os.path.expanduser(args.images_dir)

    # --- Stage 1: Chunk ---
    logger.info("=" * 60)
    logger.info("STAGE 1: Chunking", path=md_path)
    logger.info("=" * 60)

    book_chunker = BookChunker(max_chars=args.chunk_size, overlap_ratio=args.overlap)
    raw_text = Path(md_path).read_text(encoding="utf-8")
    chunks = book_chunker.chunk_markdown(Path(md_path), Path(images_dir))
    note_title = args.note_title or Path(md_path).stem

    logger.info("Chunking complete", chunks=len(chunks), title=note_title)

    # Prepare image URLs
    unique_filenames = {img.filename for chunk in chunks for img in chunk.images}
    image_url_map: dict[str, str] = {}
    if args.upload_images and unique_filenames:
        logger.info("Uploading images to storage", count=len(unique_filenames))
        image_url_map = await _upload_images(images_dir, unique_filenames, args.user_id)

    # --- Stage 2: Embed ---
    logger.info("=" * 60)
    logger.info("STAGE 2: Embedding", skip=args.skip_embeddings)
    logger.info("=" * 60)

    embeddings = await _embed_texts(
        [c.text for c in chunks],
        use_local=args.local_embeddings,
        skip=args.skip_embeddings,
    )
    if len(embeddings) != len(chunks):
        logger.warning("Embedding count mismatch; falling back to no embeddings")
        embeddings = [None] * len(chunks)

    emb_count = len([e for e in embeddings if e is not None])
    logger.info("Embedding complete", total=len(chunks), embedded=emb_count)

    note_id = args.note_id or str(uuid.uuid4())

    if args.dry_run:
        logger.info(
            "DRY RUN complete",
            chunks=len(chunks),
            embeddings=emb_count,
            note_id=note_id,
        )
        return

    # --- Stage 3: Store ---
    logger.info("=" * 60)
    logger.info("STAGE 3: Storing note + chunks in PostgreSQL")
    logger.info("=" * 60)

    pg_client = await get_postgres_client()
    await _insert_note(pg_client, note_id, args.user_id, note_title, raw_text)
    inserted = await _insert_chunks(pg_client, note_id, chunks, embeddings, image_url_map, args.image_base_url)

    logger.info("Storage complete", records_inserted=inserted)

    # --- Stages 4-8: Concept extraction + relationships + flashcards + quizzes ---
    concepts_created = 0
    flashcards_created = 0
    quizzes_created = 0

    if not args.skip_concepts:
        # --- Stage 4: Extract concepts ---
        logger.info("=" * 60)
        logger.info("STAGE 4: Extracting concepts (batch)", batch_size=args.concept_batch_size)
        logger.info("=" * 60)

        all_concepts = await _batch_extract_concepts(
            chunks, args.concept_batch_size, existing_concepts=[]
        )
        concepts_created = len(all_concepts)

        if all_concepts:
            # --- Stage 5 & 6: Create concepts + relationships + consolidation ---
            logger.info("=" * 60)
            logger.info("STAGE 5-6: Creating concepts, relationships, and consolidation pass")
            logger.info("=" * 60)

            concept_ids, name_to_id = await _create_concepts_and_relationships(
                all_concepts, note_id, args.user_id, note_title
            )

            # --- Stage 7: Flashcards ---
            if not args.skip_flashcards:
                logger.info("=" * 60)
                logger.info("STAGE 7: Generating flashcards")
                logger.info("=" * 60)

                flashcards_created = await _generate_flashcards(
                    all_concepts, concept_ids, note_id, args.user_id, raw_text
                )

            # --- Stage 8: Quizzes ---
            if not args.skip_quizzes:
                logger.info("=" * 60)
                logger.info("STAGE 8: Generating quizzes (MCQ)")
                logger.info("=" * 60)

                quizzes_created = await _generate_quizzes(
                    all_concepts, concept_ids, args.user_id, args.mcq_per_concept
                )

    # --- Summary ---
    logger.info("=" * 60)
    logger.info(
        "INGESTION COMPLETE",
        note_id=note_id,
        chunks=len(chunks),
        records_inserted=inserted,
        embeddings=emb_count,
        concepts=concepts_created,
        flashcards=flashcards_created,
        quizzes=quizzes_created,
    )
    logger.info("=" * 60)

    print(
        f"\nDone. Note {note_id}\n"
        f"  chunks={len(chunks)} | db_rows={inserted} | embeddings={emb_count}\n"
        f"  concepts={concepts_created} | flashcards={flashcards_created} | quizzes={quizzes_created}"
    )


if __name__ == "__main__":
    asyncio.run(main())
