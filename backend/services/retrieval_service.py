"""Hybrid Retrieval Service: chunk-level Vector + Postgres FTS + Graph RRF.

Combines three retrieval signals in the shared `chunk_id` ID space using Reciprocal Rank Fusion (RRF),
deduplicates by `parent_chunk_id`, and extracts child-centered context windows instead of blind prefix cuts.
"""

from __future__ import annotations

import asyncio
import os
import json
from typing import Any, Dict, List, Optional

import structlog

from backend.db.neo4j_client import get_neo4j_client
from backend.db.postgres_client import get_postgres_client
from backend.services.ingestion.embedding_service import EmbeddingService

logger = structlog.get_logger()

RRF_K = 60
_UNSET: Any = object()


def _parse_images(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
            return decoded if isinstance(decoded, list) else []
        except Exception:
            return []
    return []


async def run_vector_sql(
    pg: Any,
    sql: str,
    params: dict[str, Any],
    *,
    ef_search: Optional[int] = None,
) -> list:
    """Execute a pgvector HNSW query with iterative scan when backed by PostgresClient."""
    if hasattr(pg, "execute_vector_query"):
        return await pg.execute_vector_query(sql, params, ef_search=ef_search)
    return await pg.execute_query(sql, params)


# Lexical leg query: the question's terms joined with OR, ranked by ts_rank_cd (cover density).
# websearch_to_tsquery joins every word with AND, so a whole question ("What combination of symptoms
# and test results would suggest...") matched almost no 300-character chunk: recall@5 0.06 on the
# retrieval golden set. Phrases ("<->") and the parser's stop-word handling are kept.
_OR_TSQUERY = "replace(websearch_to_tsquery('english', :query)::text, ' & ', ' | ')::tsquery"


def _ef_search() -> Optional[int]:
    """HNSW candidate-list size (VECTOR_EF_SEARCH). Unset = pgvector's default (40). Measured 27 Nov
    on 2,353 vectors: recall@20 vs exact search is 1.000 at 40, 100 and 200, so there is nothing to
    buy yet; rerun eval/retrieval/hnsw_recall.py as the corpus grows and raise it when recall drops."""
    raw = os.getenv("VECTOR_EF_SEARCH", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


async def attach_chunk_embeddings(pg: Any, user_id: str, chunks: list[dict[str, Any]]) -> None:
    """Set chunk["embedding"] (list[float]) on each chunk that has one, in one owner-filtered query."""
    ids = [str(c["id"]) for c in chunks if c.get("id") and c.get("embedding") is None]
    if not ids:
        return
    try:
        rows = await pg.execute_query(
            "SELECT id, embedding::text AS embedding FROM chunks "
            "WHERE user_id = CAST(:user_id AS uuid) AND id = ANY(CAST(:ids AS uuid[])) AND embedding IS NOT NULL",
            {"user_id": user_id, "ids": ids},
        )
    except Exception as e:  # diversity falls back to word overlap; retrieval itself is unaffected
        logger.warning("attach_chunk_embeddings: failed", error=str(e))
        return
    by_id = {}
    for r in rows or []:
        raw = r.get("embedding")
        try:
            by_id[str(r["id"])] = [float(x) for x in raw.strip("[]").split(",")] if isinstance(raw, str) else list(raw)
        except (TypeError, ValueError, AttributeError):
            continue
    for c in chunks:
        if c.get("embedding") is None and str(c.get("id")) in by_id:
            c["embedding"] = by_id[str(c["id"])]


def reciprocal_rank_fusion(
    ranked_lists: list[tuple[str, float, list[dict[str, Any]]]],
    *,
    k: int = RRF_K,
) -> list[dict[str, Any]]:
    """Fuse multiple chunk-ID ranked lists with weighted Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}
    items: dict[str, dict[str, Any]] = {}
    sources_by_key: dict[str, list[str]] = {}

    for source_name, weight, result_list in ranked_lists:
        if not result_list or weight <= 0:
            continue
        seen_in_list: set[str] = set()
        for item in result_list:
            chunk_id = item.get("id")
            if not chunk_id:
                continue
            key = str(chunk_id)
            if key in seen_in_list:
                continue
            rank = len(seen_in_list)
            seen_in_list.add(key)

            scores[key] = scores.get(key, 0.0) + float(weight) / float(k + rank + 1)
            matched = sources_by_key.setdefault(key, [])
            if source_name not in matched:
                matched.append(source_name)

            copied = dict(item)
            existing = items.get(key)
            if existing is None:
                items[key] = copied
            else:
                # Preserve highest vector similarity / parent content / page spans when merging legs.
                if float(copied.get("similarity") or 0.0) > float(existing.get("similarity") or 0.0):
                    existing["similarity"] = copied["similarity"]
                for field in ("parent_content", "child_content", "content", "title", "note_id", "parent_chunk_id"):
                    if not existing.get(field) and copied.get(field):
                        existing[field] = copied[field]
                if not existing.get("images") and copied.get("images"):
                    existing["images"] = copied["images"]

    ranked_keys = sorted(
        scores.keys(),
        key=lambda key: (scores[key], float(items[key].get("similarity") or 0.0)),
        reverse=True,
    )

    fused: list[dict[str, Any]] = []
    for key in ranked_keys:
        row = items[key]
        row["_rrf_score"] = round(scores[key], 6)
        row["_matched_by"] = list(sources_by_key.get(key, []))
        row["_source"] = "+".join(row["_matched_by"])
        if not row.get("content"):
            row["content"] = row.get("parent_content") or row.get("child_content") or ""
        fused.append(row)
    return fused


def dedupe_by_parent(
    candidates: list[dict[str, Any]],
    *,
    limit: int,
    max_per_parent: int = 1,
) -> list[dict[str, Any]]:
    """Keep up to `max_per_parent` highest-ranked child chunks per `parent_chunk_id` (`<=0` = unlimited)."""
    if limit <= 0:
        return []
    if max_per_parent <= 0:
        return [dict(item) for item in candidates[:limit]]

    kept_lists: dict[str, list[dict[str, Any]]] = {}
    out: list[dict[str, Any]] = []

    for item in candidates:
        parent_key = str(item.get("parent_chunk_id") or item.get("id") or "")
        if not parent_key:
            continue
        siblings = kept_lists.get(parent_key)
        if siblings is None:
            copied = dict(item)
            copied["_matched_by"] = list(item.get("_matched_by") or ([item["_source"]] if item.get("_source") else []))
            kept_lists[parent_key] = [copied]
            out.append(copied)
        elif len(siblings) < max_per_parent:
            copied = dict(item)
            copied["_matched_by"] = list(item.get("_matched_by") or ([item["_source"]] if item.get("_source") else []))
            siblings.append(copied)
            out.append(copied)
        else:
            existing = siblings[0]
            existing_sources = existing.setdefault("_matched_by", [])
            for src in item.get("_matched_by") or []:
                if src not in existing_sources:
                    existing_sources.append(src)
            existing["_source"] = "+".join(existing_sources)
            if not existing.get("images") and item.get("images"):
                existing["images"] = item["images"]
        if len(out) >= limit:
            break

    return out[:limit]


def _trim_to_word_boundary(text: str, *, trim_left: bool, trim_right: bool) -> str:
    out = text
    if trim_left:
        first_space = out.find(" ")
        if 0 < first_space < 40:
            out = out[first_space + 1 :]
        out = "…" + out.lstrip()
    if trim_right:
        last_space = out.rfind(" ")
        if last_space > len(out) - 40 and last_space > 0:
            out = out[:last_space]
        out = out.rstrip() + "…"
    return out


def extract_child_centered_window(
    parent_text: str,
    child_text: str,
    *,
    window_chars: int = 1200,
    radius_chars: int = 450,
) -> str:
    """Return a window from `parent_text` guaranteed to keep the matched `child_text` intact."""
    parent = (parent_text or "").strip()
    child = (child_text or "").strip()

    if not parent:
        return child[:window_chars] if len(child) > window_chars else child
    if len(parent) <= window_chars:
        return parent
    if not child:
        return _trim_to_word_boundary(parent[:window_chars], trim_left=False, trim_right=True)

    pos = parent.find(child)
    match_len = len(child)
    if pos < 0:
        anchor = child[: min(80, len(child))]
        pos = parent.find(anchor)
        match_len = len(child) if pos >= 0 else 0

    if pos < 0:
        # Child wasn't verbatim inside parent (e.g. legacy prefix/normalization): guarantee child is shown.
        if len(child) + 20 >= window_chars:
            return child[:window_chars]
        prefix_budget = max(0, window_chars - len(child) - 5)
        prefix = parent[:prefix_budget].rstrip()
        return f"{child}\n… {prefix}…" if prefix else child

    end = min(len(parent), pos + match_len)
    if (end - pos) >= window_chars:
        # Matched child alone exceeds window: start right at the matched child.
        return _trim_to_word_boundary(
            parent[pos : pos + window_chars],
            trim_left=pos > 0,
            trim_right=(pos + window_chars) < len(parent),
        )

    win_start = max(0, pos - radius_chars)
    win_end = min(len(parent), end + radius_chars)

    if (win_end - win_start) > window_chars:
        # Center surplus budget symmetrically around the matched child while keeping [pos, end] intact.
        slack = max(0, window_chars - (end - pos))
        win_start = max(0, pos - slack // 2)
        win_end = min(len(parent), win_start + window_chars)
        if (win_end - win_start) < window_chars and win_start > 0:
            win_start = max(0, win_end - window_chars)
    elif (win_end - win_start) < window_chars:
        missing = window_chars - (win_end - win_start)
        add_left = min(win_start, missing // 2)
        win_start -= add_left
        add_right = min(len(parent) - win_end, missing - add_left)
        win_end += add_right
        if (win_end - win_start) < window_chars and win_start > 0:
            win_start = max(0, win_end - window_chars)

    snippet = parent[win_start:win_end]
    return _trim_to_word_boundary(
        snippet,
        trim_left=win_start > 0,
        trim_right=win_end < len(parent),
    )


def pack_context_chunks(
    chunks: list[dict[str, Any]],
    *,
    max_chars: int = 6000,
    per_chunk_window: int = 1200,
) -> list[dict[str, Any]]:
    """Attach `window_content` via `extract_child_centered_window` and enforce total char budget."""
    if not chunks or max_chars <= 0:
        return []

    packed: list[dict[str, Any]] = []
    used_chars = 0
    for item in chunks:
        parent_text = item.get("parent_content") or item.get("content") or ""
        child_text = item.get("child_content") or ""
        window = extract_child_centered_window(parent_text, child_text, window_chars=per_chunk_window)
        if not window:
            continue

        remaining = max_chars - used_chars
        if packed and len(window) > remaining:
            if remaining < 240:
                break
            window = extract_child_centered_window(parent_text, child_text, window_chars=remaining)
        elif not packed and len(window) > max_chars:
            window = extract_child_centered_window(parent_text, child_text, window_chars=max_chars)

        enriched = dict(item)
        enriched["window_content"] = window
        packed.append(enriched)
        used_chars += len(window)
        if used_chars >= max_chars:
            break

    return packed


class RetrievalService:
    """Hybrid chunk-level retrieval combining Vector + Postgres FTS + Graph RRF."""

    def __init__(self, embedding_service: Optional[EmbeddingService] = None) -> None:
        self._embedding_service = embedding_service

    @property
    def embedding_service(self) -> EmbeddingService:
        if self._embedding_service is None:
            self._embedding_service = EmbeddingService()
        return self._embedding_service

    async def hybrid_search(
        self,
        query: str,
        user_id: str,
        *,
        query_embedding: Any = _UNSET,
        seed_concept_ids: Optional[list[str]] = None,
        focused_source_ids: Optional[list[str]] = None,
        limit: int = 5,
        candidate_k: int = 20,
        max_per_parent: int = 1,
        graph_mode: Optional[str] = None,
        attach_embeddings: bool = True,
        pg_client: Any = None,
        neo4j_client: Any = None,
    ) -> dict[str, Any]:
        """Run Vector + Postgres FTS + Graph chunk legs concurrently and fuse with RRF."""
        clean_query = (query or "").strip()
        if not clean_query:
            return {"chunks": [], "stats": {"vector": 0, "keyword": 0, "graph": 0, "fused": 0, "deduped": 0}}

        pg = pg_client or await get_postgres_client()

        resolved_embedding: Optional[list[float]]
        if query_embedding is _UNSET:
            resolved_embedding = await self.embedding_service.embed_query(clean_query) or None
        else:
            resolved_embedding = query_embedding

        tasks: list[tuple[str, float, Any]] = []
        if resolved_embedding:
            tasks.append((
                "vector",
                1.0,
                self._vector_search(
                    clean_query,
                    user_id,
                    limit=candidate_k,
                    query_embedding=resolved_embedding,
                    focused_source_ids=focused_source_ids,
                    pg_client=pg,
                ),
            ))
        tasks.append((
            "keyword",
            0.85,
            self._keyword_search(
                clean_query,
                user_id,
                limit=candidate_k,
                focused_source_ids=focused_source_ids,
                pg_client=pg,
            ),
        ))
        resolved_graph_mode = (graph_mode or os.getenv("GRAPH_CHUNK_MODE", "hub_pruned_2hop") or "hub_pruned_2hop").strip()
        if seed_concept_ids:
            tasks.append((
                "graph",
                0.65,
                self._graph_chunk_search(
                    user_id=user_id,
                    seed_concept_ids=seed_concept_ids,
                    query_embedding=resolved_embedding,
                    focused_source_ids=focused_source_ids,
                    limit=min(candidate_k, 15),
                    graph_mode=resolved_graph_mode,
                    pg_client=pg,
                    neo4j_client=neo4j_client,
                ),
            ))

        raw_results = await asyncio.gather(*(coro for _, _, coro in tasks), return_exceptions=True)

        ranked_lists: list[tuple[str, float, list[dict[str, Any]]]] = []
        counts = {"vector": 0, "keyword": 0, "graph": 0}
        for (name, weight, _), outcome in zip(tasks, raw_results):
            if isinstance(outcome, Exception):
                logger.warning("hybrid_search: leg failed", leg=name, error=str(outcome))
                continue
            rows = list(outcome or [])
            counts[name] = len(rows)
            if rows:
                ranked_lists.append((name, weight, rows))

        fused = reciprocal_rank_fusion(ranked_lists, k=RRF_K)
        deduped = dedupe_by_parent(fused, limit=limit, max_per_parent=max_per_parent)
        # MMR measures redundancy between chunks by cosine, so it needs their vectors. The legs
        # don't select them (768 floats per row x 3 legs x candidate_k); fetch them once here
        # for the survivors unless caller delays attachment until after second-stage reranking.
        if attach_embeddings:
            await attach_chunk_embeddings(pg, user_id, deduped)
        stats = {
            **counts,
            "fused": len(fused),
            "deduped": len(deduped),
        }
        logger.info("hybrid_search: Complete", **stats, scoped=bool(focused_source_ids))
        return {"chunks": deduped, "stats": stats}

    async def search(
        self,
        query: str,
        user_id: str,
        limit: int = 5,
        include_graph: bool = True,
    ) -> List[Dict[str, Any]]:
        """Backwards-compatible hybrid search wrapper returning fused, deduped chunks."""
        seed_ids: Optional[list[str]] = None
        if include_graph and (query or "").strip():
            try:
                neo4j = await get_neo4j_client()
                terms = [w for w in query.split() if len(w) >= 2][:6]
                seeds = await neo4j.find_seed_concepts(user_id=user_id, terms=terms)
                seed_ids = [s["id"] for s in seeds if s.get("id")]
            except Exception as e:
                logger.warning("hybrid_search: graph seed lookup failed", error=str(e))

        out = await self.hybrid_search(
            query=query,
            user_id=user_id,
            seed_concept_ids=seed_ids,
            limit=limit,
        )
        return out["chunks"]

    async def _vector_search(
        self,
        query: str,
        user_id: str,
        limit: int = 20,
        *,
        query_embedding: Optional[list[float]] = None,
        focused_source_ids: Optional[list[str]] = None,
        pg_client: Any = None,
    ) -> List[Dict[str, Any]]:
        """Semantic vector search on child chunks using chunks.user_id + HNSW iterative scan."""
        emb = query_embedding if query_embedding is not None else await self.embedding_service.embed_query(query)
        if not emb:
            return []

        pg = pg_client or await get_postgres_client()
        embedding_literal = "[" + ",".join(str(x) for x in emb) + "]"
        scoped_clause = "AND n.id = ANY(:source_ids)" if focused_source_ids else ""
        params: dict[str, Any] = {"embedding": embedding_literal, "user_id": user_id, "limit": limit}
        if focused_source_ids:
            params["source_ids"] = focused_source_ids

        sql = f"""
            SELECT
                c.id,
                c.parent_chunk_id,
                c.content AS child_content,
                c.chunk_index,
                p.content AS parent_content,
                p.images,
                c.source_location,
                c.page_start,
                c.page_end,
                c.note_id,
                n.title,
                1 - (c.embedding <=> cast(:embedding as vector)) AS similarity
            FROM chunks c
            LEFT JOIN chunks p ON c.parent_chunk_id = p.id
            JOIN notes n ON c.note_id = n.id
            WHERE c.user_id = CAST(:user_id AS uuid)
              AND n.user_id = CAST(:user_id AS uuid)
              AND c.chunk_level = 'child'
              AND c.embedding IS NOT NULL
              {scoped_clause}
            ORDER BY c.embedding <=> cast(:embedding as vector)
            LIMIT :limit
        """
        rows = await run_vector_sql(pg, sql, params, ef_search=_ef_search())

        results: list[dict[str, Any]] = []
        for row in rows or []:
            r = dict(row)
            r["_source"] = "vector"
            r["_score"] = float(r.get("similarity") or 0.0)
            r["content"] = r.get("parent_content") or r.get("child_content", "")
            r["images"] = _parse_images(r.get("images"))
            results.append(r)
        return results

    async def _keyword_search(
        self,
        query: str,
        user_id: str,
        limit: int = 20,
        *,
        focused_source_ids: Optional[list[str]] = None,
        pg_client: Any = None,
    ) -> List[Dict[str, Any]]:
        """Postgres full-text lexical search over child chunks (`content_tsv` + GIN index)."""
        clean_query = (query or "").strip()
        if not clean_query:
            return []

        pg = pg_client or await get_postgres_client()
        # KEYWORD_TSQUERY=and restores the old all-words match (kept for A/B in eval/retrieval).
        tsq = "websearch_to_tsquery('english', :query)" if os.getenv("KEYWORD_TSQUERY", "or") == "and" else _OR_TSQUERY
        scoped_clause = "AND n.id = ANY(:source_ids)" if focused_source_ids else ""
        base_params: dict[str, Any] = {"user_id": user_id, "query": clean_query, "limit": limit}
        if focused_source_ids:
            base_params["source_ids"] = focused_source_ids

        sql_indexed = f"""
            SELECT
                c.id,
                c.parent_chunk_id,
                c.content AS child_content,
                c.chunk_index,
                p.content AS parent_content,
                p.images,
                c.page_start,
                c.page_end,
                c.note_id,
                n.title,
                ts_rank_cd(c.content_tsv, {tsq}, 32) AS bm25_score
            FROM chunks c
            LEFT JOIN chunks p ON c.parent_chunk_id = p.id
            JOIN notes n ON c.note_id = n.id
            WHERE c.user_id = CAST(:user_id AS uuid)
              AND n.user_id = CAST(:user_id AS uuid)
              AND c.chunk_level = 'child'
              {scoped_clause}
              AND c.content_tsv @@ {tsq}
            ORDER BY bm25_score DESC, n.updated_at DESC
            LIMIT :limit
        """
        sql_fallback = f"""
            SELECT
                c.id,
                c.parent_chunk_id,
                c.content AS child_content,
                c.chunk_index,
                p.content AS parent_content,
                p.images,
                c.page_start,
                c.page_end,
                c.note_id,
                n.title,
                ts_rank_cd(to_tsvector('english', coalesce(c.content, '')), {tsq}, 32) AS bm25_score
            FROM chunks c
            LEFT JOIN chunks p ON c.parent_chunk_id = p.id
            JOIN notes n ON c.note_id = n.id
            WHERE c.user_id = CAST(:user_id AS uuid)
              AND n.user_id = CAST(:user_id AS uuid)
              AND c.chunk_level = 'child'
              {scoped_clause}
              AND to_tsvector('english', coalesce(c.content, '')) @@ {tsq}
            ORDER BY bm25_score DESC, n.updated_at DESC
            LIMIT :limit
        """

        try:
            rows = await pg.execute_query(sql_indexed, base_params)
        except Exception:
            rows = await pg.execute_query(sql_fallback, base_params)

        results: list[dict[str, Any]] = []
        for row in rows or []:
            r = dict(row)
            r["_source"] = "keyword"
            r["_score"] = float(r.get("bm25_score") or 0.0)
            r["content"] = r.get("parent_content") or r.get("child_content", "")
            r["images"] = _parse_images(r.get("images"))
            results.append(r)
        return results

    async def _graph_chunk_search(
        self,
        *,
        user_id: str,
        seed_concept_ids: list[str],
        query_embedding: Optional[list[float]] = None,
        focused_source_ids: Optional[list[str]] = None,
        limit: int = 15,
        graph_mode: str = "1hop",
        hub_min_degree: int = 6,
        pg_client: Any = None,
        neo4j_client: Any = None,
    ) -> List[Dict[str, Any]]:
        """Map seed concepts (and optional pruned/unpruned 1-hop neighbors) to child chunks."""
        if not seed_concept_ids:
            return []

        neo4j = neo4j_client or await get_neo4j_client()
        if graph_mode == "hub_pruned_2hop":
            # LEANN High-Degree-Preserving Pruning: retain structural typed edges unconditionally
            # and keep weak RELATED_TO edges only when they route through high-degree hub concepts.
            note_rows = await neo4j.execute_query(
                """
                OPTIONAL MATCH (n0:NoteSource {user_id: $user_id})-[:EXPLAINS]->(seed:Concept {user_id: $user_id})
                WHERE seed.id IN $concept_ids
                WITH collect(DISTINCT {nid: n0.id, w: 1.0}) AS direct_hits
                OPTIONAL MATCH (seed:Concept {user_id: $user_id})-[r:PREREQUISITE_OF|SUBTOPIC_OF|BUILDS_ON|PART_OF|USES|APPLIES_TO|RELATED_TO]-(nbr:Concept {user_id: $user_id})
                WHERE seed.id IN $concept_ids AND NOT nbr.id IN $concept_ids
                WITH direct_hits, nbr, type(r) AS rel_type, coalesce(r.strength, 0.5) AS strength,
                     CASE
                         WHEN nbr IS NULL THEN 0
                         ELSE COUNT { (nbr)-[:RELATED_TO|PREREQUISITE_OF|SUBTOPIC_OF|BUILDS_ON|PART_OF|USES|APPLIES_TO]-(:Concept {user_id: $user_id}) }
                     END AS deg
                WITH direct_hits, nbr,
                     CASE WHEN rel_type <> 'RELATED_TO' THEN 0.60 ELSE 0.35 END AS hop_w,
                     strength, deg
                WHERE nbr IS NULL OR rel_type <> 'RELATED_TO' OR deg >= $hub_min_degree
                ORDER BY hop_w * strength * log(2.0 + deg) DESC
                WITH direct_hits, collect(DISTINCT CASE WHEN nbr IS NOT NULL THEN {nid: nbr.id, w: hop_w} END)[0..12] AS nbr_items
                WITH direct_hits, [x IN nbr_items WHERE x IS NOT NULL] AS filtered_nbrs
                WITH direct_hits, CASE WHEN size(filtered_nbrs) = 0 THEN [null] ELSE filtered_nbrs END AS safe_nbrs
                UNWIND safe_nbrs AS nb
                OPTIONAL MATCH (n1:NoteSource {user_id: $user_id})-[:EXPLAINS]->(nbr_c:Concept {user_id: $user_id})
                WHERE nb IS NOT NULL AND nbr_c.id = nb.nid
                WITH direct_hits, collect(DISTINCT CASE WHEN nb IS NOT NULL AND n1 IS NOT NULL THEN {nid: n1.id, w: nb.w} END) AS hop_hits
                WITH direct_hits + hop_hits AS all_hits
                UNWIND all_hits AS h
                WITH h WHERE h IS NOT NULL AND h.nid IS NOT NULL
                RETURN h.nid AS note_id, sum(h.w) AS concept_hits
                ORDER BY concept_hits DESC
                LIMIT 12
                """,
                {
                    "user_id": user_id,
                    "concept_ids": seed_concept_ids,
                    "hub_min_degree": hub_min_degree,
                },
            )
        elif graph_mode == "naive_2hop":
            note_rows = await neo4j.execute_query(
                """
                OPTIONAL MATCH (n0:NoteSource {user_id: $user_id})-[:EXPLAINS]->(seed:Concept {user_id: $user_id})
                WHERE seed.id IN $concept_ids
                WITH collect(DISTINCT {nid: n0.id, w: 1.0}) AS direct_hits
                OPTIONAL MATCH (seed:Concept {user_id: $user_id})-[r]-(nbr:Concept {user_id: $user_id})
                WHERE seed.id IN $concept_ids AND NOT nbr.id IN $concept_ids
                WITH direct_hits, nbr, coalesce(r.strength, 0.5) AS strength
                ORDER BY strength DESC
                WITH direct_hits, collect(DISTINCT nbr.id)[0..12] AS nbr_ids
                WITH direct_hits, [x IN nbr_ids WHERE x IS NOT NULL] AS filtered_nbrs
                WITH direct_hits, CASE WHEN size(filtered_nbrs) = 0 THEN [null] ELSE filtered_nbrs END AS safe_nbrs
                UNWIND safe_nbrs AS nb_id
                OPTIONAL MATCH (n1:NoteSource {user_id: $user_id})-[:EXPLAINS]->(nbr_c:Concept {user_id: $user_id})
                WHERE nb_id IS NOT NULL AND nbr_c.id = nb_id
                WITH direct_hits, collect(DISTINCT CASE WHEN nb_id IS NOT NULL AND n1 IS NOT NULL THEN {nid: n1.id, w: 0.45} END) AS hop_hits
                WITH direct_hits + hop_hits AS all_hits
                UNWIND all_hits AS h
                WITH h WHERE h IS NOT NULL AND h.nid IS NOT NULL
                RETURN h.nid AS note_id, sum(h.w) AS concept_hits
                ORDER BY concept_hits DESC
                LIMIT 12
                """,
                {"user_id": user_id, "concept_ids": seed_concept_ids},
            )
        else:
            note_rows = await neo4j.execute_query(
                """
                MATCH (n:NoteSource {user_id: $user_id})-[:EXPLAINS]->(c:Concept {user_id: $user_id})
                WHERE c.id IN $concept_ids
                RETURN n.id AS note_id, count(DISTINCT c) AS concept_hits
                ORDER BY concept_hits DESC
                LIMIT 10
                """,
                {"user_id": user_id, "concept_ids": seed_concept_ids},
            )
        note_hits: dict[str, float] = {
            str(r["note_id"]): float(r.get("concept_hits") or 1.0)
            for r in (note_rows or [])
            if r.get("note_id")
        }
        if focused_source_ids:
            allowed_notes = {str(nid) for nid in focused_source_ids}
            note_hits = {nid: hits for nid, hits in note_hits.items() if nid in allowed_notes}
        if not note_hits:
            return []

        note_ids = list(note_hits.keys())
        pg = pg_client or await get_postgres_client()
        params: dict[str, Any] = {"user_id": user_id, "note_ids": note_ids, "limit": limit}

        if query_embedding:
            params["embedding"] = "[" + ",".join(str(x) for x in query_embedding) + "]"
            sql = """
                SELECT
                    c.id,
                    c.parent_chunk_id,
                    c.content AS child_content,
                    c.chunk_index,
                    p.content AS parent_content,
                    p.images,
                    c.page_start,
                    c.page_end,
                    c.note_id,
                    n.title,
                    1 - (c.embedding <=> cast(:embedding as vector)) AS similarity
                FROM chunks c
                LEFT JOIN chunks p ON c.parent_chunk_id = p.id
                JOIN notes n ON c.note_id = n.id
                WHERE c.user_id = CAST(:user_id AS uuid)
                  AND n.user_id = CAST(:user_id AS uuid)
                  AND n.id = ANY(:note_ids)
                  AND c.chunk_level = 'child'
                  AND c.embedding IS NOT NULL
                ORDER BY c.embedding <=> cast(:embedding as vector)
                LIMIT :limit
            """
            rows = await run_vector_sql(pg, sql, params, ef_search=_ef_search())
        else:
            sql = """
                SELECT
                    c.id,
                    c.parent_chunk_id,
                    c.content AS child_content,
                    c.chunk_index,
                    p.content AS parent_content,
                    p.images,
                    c.page_start,
                    c.page_end,
                    c.note_id,
                    n.title,
                    0.5 AS similarity
                FROM chunks c
                LEFT JOIN chunks p ON c.parent_chunk_id = p.id
                JOIN notes n ON c.note_id = n.id
                WHERE c.user_id = CAST(:user_id AS uuid)
                  AND n.user_id = CAST(:user_id AS uuid)
                  AND n.id = ANY(:note_ids)
                  AND c.chunk_level = 'child'
                ORDER BY c.chunk_index ASC
                LIMIT :limit
            """
            rows = await pg.execute_query(sql, params)
        results: list[dict[str, Any]] = []
        for row in rows or []:
            r = dict(row)
            r["_source"] = "graph"
            r["_score"] = float(r.get("similarity") or 0.0) + 0.05 * note_hits.get(str(r.get("note_id")), 0)
            r["content"] = r.get("parent_content") or r.get("child_content", "")
            r["images"] = _parse_images(r.get("images"))
            results.append(r)

        if query_embedding is None:
            results.sort(key=lambda item: item["_score"], reverse=True)
        return results
