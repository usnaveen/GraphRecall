"""Does the pgvector index return the same top-5 chunks as an exact search?

init.sql creates `idx_chunks_embedding` (ivfflat, lists=100) when the chunks table is empty, and
pgvector warns that this gives low recall: ivfflat centroids are fixed at build time. The chat query
also filters by user and chunk level after the approximate scan. This runs the product's own vector
query for each eval question twice, with the index and with index scans disabled (exact), and
reports overlap@5 and how many rows came back.

    python eval/graphrag/check_vector_index.py --questions questions_slice.json
"""

from __future__ import annotations

import argparse
import asyncio
import json

import _env

_env.setup()

QUERY = """
SELECT c.id
FROM chunks c JOIN notes n ON c.note_id = n.id
WHERE n.user_id = :user_id AND c.chunk_level = 'child' AND c.embedding IS NOT NULL
ORDER BY c.embedding <=> cast(:embedding as vector)
LIMIT 5
"""


async def main(questions_file: str) -> None:
    from sqlalchemy import text

    from backend.config.llm import get_embedding_dims, get_embeddings
    from backend.db.postgres_client import get_postgres_client

    pg = await get_postgres_client()
    user_id = await _env.eval_user_id("grb")
    qs = json.loads((_env.HERE / questions_file).read_text())["questions"]
    # Same call the chat path makes (get_context_node._embed_question): a query-type embedding.
    vecs = [await get_embeddings().aembed_query(q["question"], output_dimensionality=get_embedding_dims()) for q in qs]
    rows = []
    async with pg._engine.connect() as conn:
        plan = (await conn.execute(text("EXPLAIN " + QUERY), {"user_id": user_id, "embedding": "[" + ",".join(map(str, vecs[0])) + "]"})).fetchall()
        uses_index = any("idx_chunks_embedding" in str(r[0]) for r in plan)
        for q, v in zip(qs, vecs):
            lit = "[" + ",".join(map(str, v)) + "]"
            approx = [r[0] for r in (await conn.execute(text(QUERY), {"user_id": user_id, "embedding": lit})).fetchall()]
            await conn.execute(text("SET LOCAL enable_indexscan = off"))
            await conn.execute(text("SET LOCAL enable_bitmapscan = off"))
            exact = [r[0] for r in (await conn.execute(text(QUERY), {"user_id": user_id, "embedding": lit})).fetchall()]
            await conn.execute(text("RESET enable_indexscan"))
            await conn.execute(text("RESET enable_bitmapscan"))
            rows.append({"id": q["id"], "approx_rows": len(approx), "overlap_at_5": len(set(approx) & set(exact))})
        n_chunks = (await conn.execute(text("SELECT count(*) FROM chunks c JOIN notes n ON c.note_id = n.id WHERE n.user_id = :u AND c.chunk_level='child'"), {"u": user_id})).scalar()
    out = {"plan_uses_ivfflat": uses_index, "child_chunks": n_chunks, "questions": len(rows),
           "mean_overlap_at_5": sum(r["overlap_at_5"] for r in rows) / len(rows),
           "mean_rows_returned": sum(r["approx_rows"] for r in rows) / len(rows), "rows": rows,
           "plan": [str(r[0]) for r in plan]}
    (_env.HERE / "results").mkdir(exist_ok=True)
    (_env.HERE / "results" / "vector_index_check.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k not in ("rows",)}, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default="questions_slice.json")
    asyncio.run(main(ap.parse_args().questions))
