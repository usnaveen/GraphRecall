"""Tests for GR-OPS-09: multi-tenant pgvector HNSW iterative scan & Neo4j pre-filter ANN."""

from __future__ import annotations

import math
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from backend.db import migrate as M
from backend.services.concept_similarity import (
    _FALLBACK_OVERFETCH_MIN,
    ensure_vector_index,
    similar_to_embedding,
)
from backend.services.retrieval_service import RetrievalService
from backend.tests.test_account_deletion import stores  # noqa: F401
from backend.tests.test_migrate import scratch_db  # noqa: F401


def _unit_cosine_vec(cos_target: float, *, plane_axis: int = 1, dims: int = 768) -> list[float]:
    """Return a normalized vector with exact cosine similarity `cos_target` to e_0."""
    vec = [0.0] * dims
    vec[0] = float(cos_target)
    rem = max(0.0, 1.0 - cos_target * cos_target)
    vec[plane_axis] = math.sqrt(rem)
    return vec


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


@pytest.mark.asyncio
async def test_postgres_50_tenant_decoy_hnsw_recall(scratch_db) -> None:  # noqa: F811
    pg, _ = scratch_db
    applied = await M.migrate(pg)
    assert "020_chunks_user_id_and_hnsw" in applied
    assert await M.migrate(pg) == []

    idx_rows = await pg.execute_query(
        "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'chunks'"
    )
    by_name = {r["indexname"]: r["indexdef"] for r in idx_rows}
    assert "idx_chunks_embedding_hnsw" in by_name
    assert "USING hnsw" in by_name["idx_chunks_embedding_hnsw"]
    assert "idx_chunks_embedding" not in by_name

    col_rows = await pg.execute_query(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = 'chunks' AND column_name = 'user_id'"
    )
    assert col_rows and col_rows[0]["is_nullable"] == "NO"

    # Seed 50 decoy users (200 decoy chunks closer to query than target) + 1 target user.
    users = []
    for i in range(51):
        row = (
            await pg.execute_query(
                "INSERT INTO users (email) VALUES (:e) RETURNING id",
                {"e": f"ann-{i}-{uuid.uuid4().hex[:6]}@example.invalid"},
            )
        )[0]
        users.append(str(row["id"]))

    target_uid = users[0]
    decoy_uids = users[1:]

    note_rows = []
    for i, uid in enumerate(users):
        nrow = (
            await pg.execute_query(
                "INSERT INTO notes (user_id, title, content_text) "
                "VALUES (CAST(:u AS uuid), :t, 'body') RETURNING id",
                {"u": uid, "t": f"Note {i}"},
            )
        )[0]
        note_rows.append(str(nrow["id"]))

    target_nid = note_rows[0]

    # Trigger check: omit user_id on parent INSERT and verify chunks_sync_user_id fills it.
    target_parent_ids: list[str] = []
    for p_idx in range(5):
        pid = str(
            (
                await pg.execute_query(
                    "INSERT INTO chunks (note_id, chunk_index, content, chunk_level) "
                    "VALUES (CAST(:n AS uuid), :idx, :content, 'parent') RETURNING id",
                    {"n": target_nid, "idx": p_idx, "content": f"Target parent body {p_idx}"},
                )
            )[0]["id"]
        )
        target_parent_ids.append(pid)
    target_parent_id = target_parent_ids[0]
    parent_row = (
        await pg.execute_query(
            "SELECT user_id::text AS uid FROM chunks WHERE id = CAST(:id AS uuid)",
            {"id": target_parent_id},
        )
    )[0]
    assert parent_row["uid"] == target_uid

    # Insert 5 relevant target child chunks (across 5 distinct parents, cos 0.85..0.89)
    # plus 5 orthogonal target child chunks (cos 0.05).
    relevant_ids: list[str] = []
    batch_rows: list[dict] = []
    for j in range(5):
        cid = str(uuid.uuid4())
        relevant_ids.append(cid)
        vec = _unit_cosine_vec(0.85 + 0.01 * j, plane_axis=1)
        batch_rows.append(
            {
                "id": cid,
                "nid": target_nid,
                "uid": target_uid,
                "pid": target_parent_ids[j],
                "idx": j + 1,
                "content": f"target relevant chunk {j}",
                "emb": _vec_literal(vec),
            }
        )
    for j in range(5):
        vec = _unit_cosine_vec(0.05, plane_axis=3 + (j % 4))
        batch_rows.append(
            {
                "id": str(uuid.uuid4()),
                "nid": target_nid,
                "uid": target_uid,
                "pid": target_parent_id,
                "idx": 10 + j,
                "content": f"target unrelated chunk {j}",
                "emb": _vec_literal(vec),
            }
        )

    # 50 decoy users * 4 child chunks = 200 decoys with cos 0.970..0.999 (all strictly closer than target 0.89).
    decoy_ids: set[str] = set()
    for d_idx, uid in enumerate(decoy_uids):
        nid = note_rows[d_idx + 1]
        for k in range(4):
            cid = str(uuid.uuid4())
            decoy_ids.add(cid)
            cos_d = 0.970 + ((d_idx * 4 + k) % 30) * 0.00095
            vec = _unit_cosine_vec(cos_d, plane_axis=2 + (k % 3))
            batch_rows.append(
                {
                    "id": cid,
                    "nid": nid,
                    "uid": uid,
                    "pid": None,
                    "idx": k,
                    "content": f"decoy tenant {d_idx} chunk {k}",
                    "emb": _vec_literal(vec),
                }
            )

    async with pg.session() as s:
        await s.execute(
            text(
                "INSERT INTO chunks (id, note_id, user_id, parent_chunk_id, chunk_index, content, chunk_level, embedding) "
                "VALUES (CAST(:id AS uuid), CAST(:nid AS uuid), CAST(:uid AS uuid), "
                "CAST(:pid AS uuid), :idx, :content, 'child', CAST(:emb AS vector))"
            ),
            batch_rows,
        )
        await s.execute(text("ANALYZE chunks"))

    query_vec = _unit_cosine_vec(1.0)
    query_lit = _vec_literal(query_vec)

    # Verify HNSW behavior directly on idx_chunks_embedding_hnsw inside a rolled-back savepoint:
    # without iterative_scan, 200 closer decoy vectors exhaust ef_search=10 (<5 hits);
    # enabling SET LOCAL hnsw.iterative_scan = relaxed_order recovers 5/5 recall.
    hnsw_sql = (
        "SELECT id::text AS id FROM chunks "
        "WHERE user_id = CAST(:uid AS uuid) AND chunk_level = 'child' AND embedding IS NOT NULL "
        "ORDER BY embedding <=> CAST(:emb AS vector) LIMIT 5"
    )
    async with pg.session() as s:
        await s.execute(text("SAVEPOINT sp_hnsw_probe"))
        await s.execute(text("DROP INDEX idx_chunks_user_level"))
        await s.execute(text("SET LOCAL enable_seqscan = off"))
        await s.execute(text("SET LOCAL hnsw.ef_search = 10"))

        await s.execute(text("SET LOCAL hnsw.iterative_scan = off"))
        plan_rows = (
            await s.execute(text("EXPLAIN " + hnsw_sql), {"uid": target_uid, "emb": query_lit})
        ).fetchall()
        assert any("idx_chunks_embedding_hnsw" in r[0] for r in plan_rows)
        naive = (await s.execute(text(hnsw_sql), {"uid": target_uid, "emb": query_lit})).fetchall()
        assert len(naive) < 5

        await s.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
        rescued = (await s.execute(text(hnsw_sql), {"uid": target_uid, "emb": query_lit})).fetchall()
        assert {r[0] for r in rescued} == set(relevant_ids)
        await s.execute(text("ROLLBACK TO SAVEPOINT sp_hnsw_probe"))

    # Positive proof 1: PostgresClient.execute_vector_query returns exact 5/5 target chunks.
    vec_rows = await pg.execute_vector_query(hnsw_sql, {"uid": target_uid, "emb": query_lit}, ef_search=10)
    assert set(relevant_ids) == {r["id"] for r in vec_rows}

    # Positive proof 2: end-to-end RetrievalService.hybrid_search hits all 5 target chunks with zero decoy leakage.
    out = await RetrievalService().hybrid_search(
        query="completely unmatched lexical probe xyzzy",
        user_id=target_uid,
        query_embedding=query_vec,
        limit=5,
        pg_client=pg,
    )
    returned_ids = {str(c["id"]) for c in out["chunks"]}
    assert returned_ids == set(relevant_ids)
    assert not (returned_ids & decoy_ids)


@pytest.mark.asyncio
async def test_neo4j_50_tenant_decoy_vector_prefilter(stores, monkeypatch) -> None:  # noqa: F811
    _, neo = stores
    run_prefix = f"ann50-{uuid.uuid4().hex[:8]}-"
    target_uid = f"{run_prefix}target"
    monkeypatch.setattr("backend.services.concept_similarity.get_neo4j_client", AsyncMock(return_value=neo))

    ready = await ensure_vector_index()
    assert ready is True
    idx = await neo.execute_query(
        "SHOW VECTOR INDEXES YIELD name, properties, state WHERE name = 'concept_embedding' RETURN properties, state"
    )
    assert idx and "user_id" in (idx[0].get("properties") or [])
    assert idx[0].get("state") == "ONLINE"

    try:
        # 50 decoy tenants * 2 concepts = 100 closer nodes (cos 0.980..0.999) > default pool_size=25.
        decoy_nodes = []
        for d in range(50):
            uid = f"{run_prefix}decoy-{d}"
            for k in range(2):
                decoy_nodes.append(
                    {
                        "id": f"{run_prefix}d-{d}-{k}",
                        "uid": uid,
                        "name": f"Decoy {d} {k}",
                        "emb": _unit_cosine_vec(0.980 + ((d * 2 + k) % 20) * 0.0009, plane_axis=2),
                    }
                )

        # Target user: 5 relevant concepts (0.88..0.92) + 10 lower baseline concepts (0.73) so median is 0.73 -> threshold 0.75.
        relevant_ids = []
        target_nodes = []
        for j in range(5):
            cid = f"{run_prefix}rel-{j}"
            relevant_ids.append(cid)
            target_nodes.append(
                {
                    "id": cid,
                    "uid": target_uid,
                    "name": f"Target Relevant {j}",
                    "emb": _unit_cosine_vec(0.88 + 0.01 * j, plane_axis=1),
                }
            )
        for j in range(10):
            target_nodes.append(
                {
                    "id": f"{run_prefix}base-{j}",
                    "uid": target_uid,
                    "name": f"Target Baseline {j}",
                    "emb": _unit_cosine_vec(0.73, plane_axis=3 + (j % 4)),
                }
            )

        await neo.execute_query(
            """
            UNWIND $rows AS r
            CREATE (c:Concept {id: r.id, user_id: r.uid, name: r.name, domain: 'ML', definition: 'test', embedding: r.emb})
            """,
            {"rows": decoy_nodes + target_nodes},
        )

        # wait briefly for vector index catch-up via awaitIndex / count visibility
        await neo.execute_query("CALL db.awaitIndex('concept_embedding', 30)", {})

        hits = await similar_to_embedding(
            target_uid,
            _unit_cosine_vec(1.0),
            limit=5,
        )
        hit_ids = {h["id"] for h in hits}
        assert hit_ids == set(relevant_ids)
    finally:
        await neo.execute_query(
            "MATCH (c:Concept) WHERE c.id STARTS WITH $prefix DETACH DELETE c",
            {"prefix": run_prefix},
        )


@pytest.mark.asyncio
async def test_neo4j_similarity_falls_back_to_heavy_overfetch_on_legacy() -> None:
    calls: list[tuple[str, dict]] = []

    class LegacyNeo4j:
        async def execute_query(self, query: str, params: dict):
            calls.append((query, params))
            if "CYPHER 25" in query:
                raise RuntimeError("Invalid input 'SEARCH'")
            return [
                {"id": "c1", "name": "HNSW", "definition": "ANN graph", "domain": "IR", "score": 0.91},
            ]

    with patch("backend.services.concept_similarity.get_neo4j_client", AsyncMock(return_value=LegacyNeo4j())):
        hits = await similar_to_embedding("u1", [0.1] * 8, limit=5, min_margin=0.0)

    assert [h["id"] for h in hits] == ["c1"]
    assert len(calls) == 2
    assert "db.index.vector.queryNodes" in calls[1][0]
    assert calls[1][1]["k"] >= _FALLBACK_OVERFETCH_MIN
