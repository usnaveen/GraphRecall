"""Bulk image-aware book ingestion (backend-only).

Features
- Rule-based chunking (no LLM) via `BookChunker`
- Figure detection + caption pairing; normalizes .jpeg/.png mismatches
- Optional local embeddings (sentence-transformers) or existing EmbeddingService
- Batch concept extraction (optional) to Neo4j
- Direct Postgres inserts for speed (bypasses LangGraph ingestion)
- Image URLs emitted so chat responses can render figures

Inputs
- Markdown file from OCR pass (see `notebooks/pdf_ocr_colab.ipynb` for the
  earlier parsing notebook that generated the provided sample markdown).
- Images directory containing the referenced figures.

Usage examples
  python scripts/ingest_book.py \\
      --md-path \"sample_content/The Hundred-Page Language Models Book /The Hundred-Page Language Models Book 2025 (1).md\" \\
      --images-dir \"sample_content/The Hundred-Page Language Models Book /images\" \\
      --note-title \"Hundred-Page LLM Book\" --image-base-url /api/images

  python scripts/ingest_book.py --upload-images --local-embeddings

Notes
- Designed to be cost-efficient for 100+ page books: no per-chunk LLM calls,
  optional concept extraction in batches, embeddings batched.
- Chunks are stored as parent+child rows; images JSON saved on both levels.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from typing import Iterable, List, Optional
from pathlib import Path

import structlog

from backend.services.book_chunker import BookChunker
from backend.services.ingestion.embedding_service import EmbeddingService
from backend.agents.extraction import ExtractionAgent
from backend.db.postgres_client import get_postgres_client
from backend.db.neo4j_client import get_neo4j_client
from backend.services.storage_service import get_storage_service

logger = structlog.get_logger()


# Optional local embeddings ---------------------------------------------------
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Image-aware book ingestion")
    parser.add_argument("--md-path", required=True, help="Path to OCR-parsed markdown file")
    parser.add_argument("--images-dir", required=True, help="Directory containing figure images")
    parser.add_argument("--note-title", default=None, help="Title for the note record")
    parser.add_argument("--note-id", default=None, help="Existing note UUID to reuse")
    parser.add_argument("--user-id", default="default_user", help="User ID owner for the note/chunks")
    parser.add_argument("--chunk-size", type=int, default=1400, help="Max chars per chunk")
    parser.add_argument("--image-base-url", default="/api/images", help="Base URL used in chunk image metadata")
    parser.add_argument("--upload-images", action="store_true", help="Upload images via StorageService (S3/Supabase)")
    parser.add_argument("--local-embeddings", action="store_true", help="Use sentence-transformers locally")
    parser.add_argument("--skip-embeddings", action="store_true", help="Do not generate embeddings")
    parser.add_argument("--extract-concepts", action="store_true", help="Run batch concept extraction to Neo4j")
    parser.add_argument("--concept-batch-size", type=int, default=10, help="Number of chunks per extraction call")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report without writing to DB")
    return parser.parse_args()


async def _upload_images(images_dir: str, filenames: Iterable[str], user_id: str) -> dict[str, str]:
    storage = get_storage_service()
    url_map: dict[str, str] = {}
    for name in filenames:
        path = os.path.join(images_dir, name)
        with open(path, "rb") as f:
            data = f.read()
        # Infer content type from extension
        content_type = "image/png" if name.lower().endswith("png") else "image/jpeg"
        url = await storage.upload_file(data, name, content_type, user_id)
        url_map[name] = url
    return url_map


async def _embed_texts(texts: List[str], use_local: bool, skip: bool) -> List[Optional[List[float]]]:
    if skip:
        return [None] * len(texts)

    if use_local:
        embedder = _LocalEmbedder()
        embeddings = await embedder.embed_batch(texts)
        return [emb.tolist() if hasattr(emb, "tolist") else emb for emb in embeddings]

    service = EmbeddingService()
    embeddings = await service.embed_batch(texts)
    if not embeddings:
        logger.warning("Embedding service returned no embeddings; continuing without embeddings")
        return [None] * len(texts)
    return embeddings


async def _insert_note(pg_client, note_id: str, user_id: str, title: str, raw_text: str):
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


async def _insert_chunks(pg_client, note_id: str, chunks, embeddings, image_url_map: dict, image_base_url: str):
    inserted = 0
    for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        parent_id = str(uuid.uuid4())
        child_id = str(uuid.uuid4())

        images_json = []
        for img in chunk.images:
            url = image_url_map.get(img.filename) or f"{image_base_url.rstrip('/')}/{img.filename}"
            images_json.append(
                {
                    "filename": img.filename,
                    "caption": img.caption,
                    "page": img.page,
                    "url": url,
                }
            )

        source_location = {"headings": chunk.headings, "page": chunk.images[0].page if chunk.images else None}

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
                "embedding": str(emb) if emb is not None else None,
            },
        )

        inserted += 2
    return inserted


async def _batch_extract_concepts(chunks, note_id: str, user_id: str, batch_size: int):
    agent = ExtractionAgent(temperature=0.2)
    neo4j = await get_neo4j_client()
    concepts_created = 0

    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        combined = "\n\n---\n\n".join(c.text for c in batch)
        result = await agent.extract(combined)
        for concept in result.concepts:
            created = await neo4j.create_concept(
                name=concept.name,
                definition=concept.definition,
                domain=concept.domain,
                complexity_score=float(concept.complexity_score),
                user_id=user_id,
                concept_id=None,
            )
            node = created.get("c", created) if isinstance(created, dict) else {}
            concept_id = node.get("id") if hasattr(node, "get") else None
            if concept_id:
                await neo4j.execute_query(
                    """
                    MERGE (n:NoteSource {id: $note_id})
                    WITH n
                    MATCH (c:Concept {id: $concept_id})
                    MERGE (n)-[:EXPLAINS]->(c)
                    """,
                    {"note_id": note_id, "concept_id": concept_id},
                )
                concepts_created += 1
    return concepts_created


async def main():
    args = _parse_args()

    md_path = os.path.expanduser(args.md_path)
    images_dir = os.path.expanduser(args.images_dir)

    book_chunker = BookChunker(max_chars=args.chunk_size)
    logger.info("Reading markdown", path=md_path)
    raw_text = Path(md_path).read_text(encoding="utf-8")
    chunks = book_chunker.chunk_markdown(Path(md_path), Path(images_dir))

    logger.info("Chunking complete", chunks=len(chunks))

    # Prepare image URLs (either upload or local base path)
    unique_filenames = {img.filename for chunk in chunks for img in chunk.images}
    image_url_map: dict[str, str] = {}
    if args.upload_images and unique_filenames:
        logger.info("Uploading images to storage", count=len(unique_filenames))
        image_url_map = await _upload_images(images_dir, unique_filenames, args.user_id)

    embeddings = await _embed_texts(
        [c.text for c in chunks],
        use_local=args.local_embeddings,
        skip=args.skip_embeddings,
    )
    if len(embeddings) != len(chunks):
        logger.warning("Embedding count mismatch; falling back to no embeddings")
        embeddings = [None] * len(chunks)

    note_id = args.note_id or str(uuid.uuid4())
    note_title = args.note_title or Path(md_path).stem

    if args.dry_run:
        logger.info(
            "Dry run complete",
            chunks=len(chunks),
            embeddings=len([e for e in embeddings if e is not None]),
            note_id=note_id,
        )
        return

    pg_client = await get_postgres_client()
    await _insert_note(pg_client, note_id, args.user_id, note_title, raw_text)
    inserted = await _insert_chunks(pg_client, note_id, chunks, embeddings, image_url_map, args.image_base_url)

    concepts_created = 0
    if args.extract_concepts:
        concepts_created = await _batch_extract_concepts(chunks, note_id, args.user_id, args.concept_batch_size)

    logger.info(
        "Ingestion complete",
        chunks=len(chunks),
        records_inserted=inserted,
        concepts_created=concepts_created,
        note_id=note_id,
    )
    print(f"Done. Note {note_id} | chunks={len(chunks)} | inserted_rows={inserted} | concepts={concepts_created}")


if __name__ == "__main__":
    asyncio.run(main())
