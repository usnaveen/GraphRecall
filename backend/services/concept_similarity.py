"""Find concepts that mean the same thing, by embedding rather than by spelling.

Ingestion used to decide whether a new paper touched the existing graph by
substring and word-overlap matching on concept names, capped at the first 100
concepts. "Gradient Descent" and "Steepest Descent Optimization" never matched,
so papers landed as islands.

Concepts already carry a 768-d embedding, written when they are created. This
module puts a Neo4j vector index over it and searches that instead, so relatedness
follows meaning and the whole graph is in scope.
"""

from __future__ import annotations

from typing import Optional

import structlog

from backend.config.llm import get_embedding_dims
from backend.db.neo4j_client import get_neo4j_client
from backend.services.ingestion.embedding_service import EmbeddingService

logger = structlog.get_logger()

CONCEPT_VECTOR_INDEX = "concept_embedding"

# Below this cosine score two concepts are not the same idea. Tuned so that
# rephrasings ("Self-Attention" / "Scaled Dot-Product Attention") match while
# merely same-field concepts ("Attention" / "Backpropagation") do not.
DEFAULT_MIN_SCORE = 0.72

# The vector index cannot filter by user inside the CALL, so over-fetch and
# filter after. Multiplier covers a graph shared by a handful of users.
_OVERFETCH = 5


async def ensure_vector_index() -> bool:
    """Create the concept vector index if it is missing. Safe to call repeatedly."""
    neo4j = await get_neo4j_client()
    dims = get_embedding_dims()
    try:
        await neo4j.execute_query(
            f"""
            CREATE VECTOR INDEX {CONCEPT_VECTOR_INDEX} IF NOT EXISTS
            FOR (c:Concept) ON (c.embedding)
            OPTIONS {{ indexConfig: {{
                `vector.dimensions`: {int(dims)},
                `vector.similarity_function`: 'cosine'
            }} }}
            """,
            {},
        )
        return True
    except Exception as e:
        # An older Neo4j without vector indexes should degrade, not crash the app.
        logger.warning("ConceptSimilarity: vector index unavailable", error=str(e))
        return False


async def similar_to_embedding(
    user_id: str,
    embedding: list[float],
    *,
    limit: int = 10,
    min_score: float = DEFAULT_MIN_SCORE,
    exclude_ids: Optional[list[str]] = None,
) -> list[dict]:
    """Concepts closest in meaning to ``embedding``, best first."""
    if not embedding:
        return []

    neo4j = await get_neo4j_client()
    exclude = set(exclude_ids or [])
    try:
        rows = await neo4j.execute_query(
            f"""
            CALL db.index.vector.queryNodes('{CONCEPT_VECTOR_INDEX}', $k, $embedding)
            YIELD node, score
            WHERE node.user_id = $user_id AND score >= $min_score
            RETURN node.id AS id, node.name AS name, node.definition AS definition,
                   node.domain AS domain, score
            ORDER BY score DESC
            """,
            {
                "k": max(limit * _OVERFETCH, limit),
                "embedding": embedding,
                "user_id": user_id,
                "min_score": min_score,
            },
        )
    except Exception as e:
        logger.warning("ConceptSimilarity: vector query failed", error=str(e))
        return []

    out = []
    for r in rows:
        if r["id"] in exclude:
            continue
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "definition": r.get("definition") or "",
                "domain": r.get("domain") or "General",
                "score": round(float(r["score"]), 4),
            }
        )
        if len(out) >= limit:
            break
    return out


async def similar_to_text(
    user_id: str,
    text: str,
    *,
    limit: int = 10,
    min_score: float = DEFAULT_MIN_SCORE,
    exclude_ids: Optional[list[str]] = None,
) -> list[dict]:
    """Embed ``text`` and find the concepts closest to it."""
    if not (text or "").strip():
        return []
    try:
        vector = await EmbeddingService().embed_query(text)
    except Exception as e:
        logger.warning("ConceptSimilarity: embed_query failed", error=str(e))
        return []
    return await similar_to_embedding(
        user_id, vector, limit=limit, min_score=min_score, exclude_ids=exclude_ids
    )


async def find_related_concepts(
    user_id: str,
    extracted: list[dict],
    *,
    per_concept: int = 5,
    min_score: float = DEFAULT_MIN_SCORE,
) -> tuple[list[dict], dict[str, list[dict]]]:
    """Match freshly extracted concepts against everything the user already has.

    Returns ``(related, by_concept)`` — the deduplicated set of existing concepts
    the new material touches, and a per-extracted-name map of its matches, which
    the caller uses to build edges rather than guess at them.
    """
    if not extracted:
        return [], {}

    texts, keys = [], []
    for c in extracted:
        name = (c.get("name") or "").strip()
        if not name:
            continue
        definition = (c.get("definition") or c.get("description") or "").strip()
        texts.append(f"{name}: {definition}" if definition else name)
        keys.append(name)

    if not texts:
        return [], {}

    try:
        vectors = await EmbeddingService().embed_batch(texts)
    except Exception as e:
        logger.warning("ConceptSimilarity: batch embed failed", error=str(e))
        return [], {}

    if not vectors:
        logger.warning("ConceptSimilarity: no embeddings returned", count=len(texts))
        return [], {}

    by_concept: dict[str, list[dict]] = {}
    seen: dict[str, dict] = {}

    for i, key in enumerate(keys):
        vector = vectors[i] if i < len(vectors) else None
        if not vector:
            continue
        matches = await similar_to_embedding(
            user_id, vector, limit=per_concept, min_score=min_score
        )
        if matches:
            by_concept[key] = matches
            for m in matches:
                # Keep the strongest score seen for each existing concept.
                prev = seen.get(m["id"])
                if prev is None or m["score"] > prev["score"]:
                    seen[m["id"]] = m

    related = sorted(seen.values(), key=lambda m: m["score"], reverse=True)
    logger.info(
        "ConceptSimilarity: matched extracted concepts",
        extracted=len(keys),
        matched=len(by_concept),
        related=len(related),
    )
    return related, by_concept


async def backfill_concept_embeddings(user_id: str, *, batch_size: int = 50) -> dict:
    """Embed every concept that is missing a vector.

    Concepts created before embeddings were written — or whose embedding call
    failed — are invisible to similarity search, which silently degrades every
    link suggestion. This makes that recoverable.
    """
    neo4j = await get_neo4j_client()
    rows = await neo4j.execute_query(
        """
        MATCH (c:Concept {user_id: $user_id})
        WHERE c.embedding IS NULL
        RETURN c.id AS id, c.name AS name, c.definition AS definition
        """,
        {"user_id": user_id},
    )
    if not rows:
        return {"missing": 0, "embedded": 0, "failed": 0}

    service = EmbeddingService()
    embedded = failed = 0

    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        texts = [
            f"{r['name']}: {r['definition']}" if r.get("definition") else r["name"]
            for r in batch
        ]
        try:
            vectors = await service.embed_batch(texts)
        except Exception as e:
            logger.warning("ConceptSimilarity: backfill batch failed", error=str(e))
            failed += len(batch)
            continue

        for i, row in enumerate(batch):
            vector = vectors[i] if i < len(vectors) else None
            if not vector:
                failed += 1
                continue
            try:
                await neo4j.execute_query(
                    """
                    MATCH (c:Concept {id: $id, user_id: $user_id})
                    SET c.embedding = $embedding
                    RETURN c.id
                    """,
                    {"id": row["id"], "user_id": user_id, "embedding": vector},
                )
                embedded += 1
            except Exception as e:
                logger.warning(
                    "ConceptSimilarity: backfill write failed",
                    concept=row["name"],
                    error=str(e),
                )
                failed += 1

    logger.info(
        "ConceptSimilarity: backfill complete",
        missing=len(rows),
        embedded=embedded,
        failed=failed,
    )
    return {"missing": len(rows), "embedded": embedded, "failed": failed}
