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

# An absolute floor is nearly useless on its own here. gemini-embedding-001
# cosine scores sit in a narrow high band — measured against a real graph,
# "Photosynthesis in C4 Plants" scored 0.846 against "Multi-Head Attention",
# while a true match ("Matrix Factorization into Orthogonal Bases" against
# "Singular Value Decomposition") scored 0.935. Cutting anywhere below ~0.88
# connects everything to everything, and cutting above it is brittle and
# specific to this model.
#
# What separates them is the SHAPE of the result, not its height. A genuine
# match stands clear of the rest of the pool; an unrelated concept sits flat
# against the crowd:
#
#   Matrix Factorization  top 0.935, pool median 0.884  → gap 0.051  real
#   Query-Key Scoring     top 0.926, pool median 0.891  → gap 0.035  real
#   Steepest Descent      top 0.899, pool median 0.894  → gap 0.005  nothing
#   Photosynthesis        top 0.846, pool median 0.841  → gap 0.005  nothing
#
# So a match must clear the pool's own median by a margin. The floor stays only
# to reject obvious noise.
DEFAULT_MIN_SCORE = 0.70

# How far above the candidate pool's median a score must sit to count as a real
# match rather than the general hum of the embedding space.
DEFAULT_MIN_MARGIN = 0.02

# The pool the median is computed over. Too small and one strong match drags the
# median up and hides the others behind it.
_BASELINE_POOL = 25

# Fallback over-fetch multiplier when running on Neo4j <2025.x without in-index filtering.
_OVERFETCH = 5
_FALLBACK_OVERFETCH_MULT = 10
_FALLBACK_OVERFETCH_MIN = 250


async def ensure_vector_index() -> bool:
    """Create (or upgrade) the concept vector index with user_id in-index pre-filtering."""
    neo4j = await get_neo4j_client()
    dims = get_embedding_dims()
    if hasattr(neo4j, "ensure_concept_vector_index"):
        return await neo4j.ensure_concept_vector_index(CONCEPT_VECTOR_INDEX, dims)

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
        logger.warning("ConceptSimilarity: vector index unavailable", error=str(e))
        return False


async def _query_concept_candidates(
    neo4j,
    user_id: str,
    embedding: list[float],
    pool_size: int,
    min_score: float,
) -> list[dict]:
    """Query Neo4j concept vector index using native Cypher 25 pre-filtering when available."""
    filtered_cypher = f"""
        CYPHER 25
        MATCH (c:Concept)
        SEARCH c IN (
          VECTOR INDEX `{CONCEPT_VECTOR_INDEX}`
          FOR $embedding
          WHERE c.user_id = $user_id
          LIMIT $k
        )
        SCORE AS score
        WHERE score >= $min_score
        RETURN c.id AS id, c.name AS name, c.definition AS definition,
               c.domain AS domain, score
        ORDER BY score DESC
    """
    filtered_params = {
        "k": pool_size,
        "embedding": embedding,
        "user_id": user_id,
        "min_score": min_score,
    }

    try:
        return await neo4j.execute_query(filtered_cypher, filtered_params)
    except Exception as err:
        msg = str(err)
        if any(code in msg for code in ("22ND3", "51N63", "additional property", "not ready")):
            try:
                if await ensure_vector_index():
                    return await neo4j.execute_query(filtered_cypher, filtered_params)
            except Exception as retry_err:
                logger.debug("ConceptSimilarity: Cypher 25 retry failed, falling back", error=str(retry_err))
        else:
            logger.debug("ConceptSimilarity: Cypher 25 SEARCH unavailable, falling back", error=msg)

    fallback_k = max(pool_size * _FALLBACK_OVERFETCH_MULT, _FALLBACK_OVERFETCH_MIN)
    return await neo4j.execute_query(
        f"""
        CALL db.index.vector.queryNodes('{CONCEPT_VECTOR_INDEX}', $k, $embedding)
        YIELD node, score
        WHERE node.user_id = $user_id AND score >= $min_score
        RETURN node.id AS id, node.name AS name, node.definition AS definition,
               node.domain AS domain, score
        ORDER BY score DESC
        """,
        {
            "k": fallback_k,
            "embedding": embedding,
            "user_id": user_id,
            "min_score": min_score,
        },
    )


async def similar_to_embedding(
    user_id: str,
    embedding: list[float],
    *,
    limit: int = 10,
    min_score: float = DEFAULT_MIN_SCORE,
    min_margin: float = DEFAULT_MIN_MARGIN,
    exclude_ids: Optional[list[str]] = None,
) -> list[dict]:
    """Concepts closest in meaning to ``embedding``, best first.

    Keeps only those standing clear of the candidate pool's own median by
    ``min_margin``. Pass ``min_margin=0`` to take everything over the floor,
    which is what callers offering suggestions for a human to judge want.
    """
    if not embedding:
        return []

    neo4j = await get_neo4j_client()
    exclude = set(exclude_ids or [])

    # Always pull a pool big enough to have a meaningful median, even when the
    # caller only wants the top few.
    pool_size = max(limit * _OVERFETCH, _BASELINE_POOL)
    try:
        rows = await _query_concept_candidates(neo4j, user_id, embedding, pool_size, min_score)
    except Exception as e:
        logger.warning("ConceptSimilarity: vector query failed", error=str(e))
        return []

    candidates = [r for r in rows if r["id"] not in exclude]
    if not candidates:
        return []

    threshold = min_score
    if min_margin > 0:
        scores = sorted(float(r["score"]) for r in candidates)
        # A pool too small to have a crowd has no baseline to stand out from;
        # fall back to the floor rather than inventing a median from 2 points.
        if len(scores) >= 5:
            mid = len(scores) // 2
            median = (
                scores[mid]
                if len(scores) % 2
                else (scores[mid - 1] + scores[mid]) / 2
            )
            threshold = max(min_score, median + min_margin)

    out = []
    for r in candidates:
        score = float(r["score"])
        if score < threshold:
            break  # rows are score-ordered, so nothing after this clears it
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "definition": r.get("definition") or "",
                "domain": r.get("domain") or "General",
                "score": round(score, 4),
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
    min_margin: float = DEFAULT_MIN_MARGIN,
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
            user_id,
            vector,
            limit=per_concept,
            min_score=min_score,
            min_margin=min_margin,
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
