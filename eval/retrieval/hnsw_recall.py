"""HNSW recall vs exact search, per ef_search, on an eval corpus (no LLM; embeddings are cached).

    EVAL_RUN=h1 PYTHONPATH=. python eval/retrieval/hnsw_recall.py [ef ...]     # default 40 100 200

27 Nov 2026, 2,353 vectors: recall@20 = 1.000 at every ef_search, p50 ~9 ms. Approximate search
only loses recall at much larger scales; rerun this when a user's corpus reaches ~100k chunks and set
VECTOR_EF_SEARCH to the smallest value that keeps recall@20 >= 0.98.
"""

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "graphrag"))
import _env  # noqa: E402

SQL = ("SELECT c.id FROM chunks c WHERE c.user_id = CAST(:u AS uuid) AND c.chunk_level = 'child' "
       "AND c.embedding IS NOT NULL ORDER BY c.embedding <=> cast(:e as vector) LIMIT 20")


async def main(efs: list[int]) -> None:
    _env.setup()
    from sqlalchemy import text
    from backend.db.postgres_client import get_postgres_client
    from backend.services.ingestion.embedding_service import EmbeddingService

    pg, emb = await get_postgres_client(), EmbeddingService()
    uid = await _env.eval_user_id("grb")
    tag = _env.run_key("grb").split("-", 1)[-1]
    qs = [json.loads(l)["question"] for l in (HERE / f"golden.{tag}.jsonl").open()][:60]
    res: dict[int, dict] = {}
    for q in qs:
        lit = "[" + ",".join(map(str, await emb.embed_query(q))) + "]"
        async with pg.session() as s:  # exact: no index scans
            await s.execute(text("SET LOCAL enable_indexscan = off"))
            await s.execute(text("SET LOCAL enable_bitmapscan = off"))
            exact = {str(r[0]) for r in (await s.execute(text(SQL), {"u": uid, "e": lit})).fetchall()}
        for ef in efs:
            t = time.perf_counter()
            got = {str(r["id"]) for r in await pg.execute_vector_query(SQL, {"u": uid, "e": lit}, ef_search=ef)}
            r = res.setdefault(ef, {"recall": [], "ms": []})
            r["recall"].append(len(got & exact) / max(1, len(exact)))
            r["ms"].append((time.perf_counter() - t) * 1000)
    for ef, r in res.items():
        print(f"ef_search={ef:4d}  recall@20 {statistics.mean(r['recall']):.3f} (min {min(r['recall']):.2f})  "
              f"p50 {statistics.median(r['ms']):.1f} ms")


if __name__ == "__main__":
    asyncio.run(main([int(a) for a in sys.argv[1:]] or [40, 100, 200]))
