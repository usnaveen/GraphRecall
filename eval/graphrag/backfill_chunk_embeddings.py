"""Embed eval chunks that were saved without a vector (e.g. after an embedding quota ran out mid-ingest).

embed_node saves chunks even when every embedding call failed ("Chunks will be saved without
embeddings"), so a note can look ingested and still be invisible to vector search. This finds the
eval user's child chunks with a NULL embedding and fills them with the same call embed_node makes
(EmbeddingService.embed_batch, 768 dims).

    python eval/graphrag/backfill_chunk_embeddings.py [--dataset grb]
"""

from __future__ import annotations

import argparse
import asyncio

import _env

_env.setup()


async def main(dataset: str, batch: int) -> None:
    from backend.db.postgres_client import get_postgres_client
    from backend.services.ingestion.embedding_service import EmbeddingService

    _env.throttle_llm()
    pg = await get_postgres_client()
    user_id = await _env.eval_user_id(dataset)
    rows = await pg.execute_query(
        """SELECT c.id::text AS id, c.content FROM chunks c JOIN notes n ON c.note_id = n.id
           WHERE n.user_id = CAST(:u AS uuid) AND c.chunk_level = 'child' AND c.embedding IS NULL ORDER BY c.id""",
        {"u": user_id},
    )
    print(f"{len(rows)} child chunks without an embedding", flush=True)
    svc, done = EmbeddingService(), 0
    for i in range(0, len(rows), batch):
        part = rows[i:i + batch]
        vectors = await svc.embed_batch([r["content"] for r in part])
        for r, v in zip(part, vectors or []):
            if v:
                await pg.execute_update("UPDATE chunks SET embedding = CAST(:e AS vector) WHERE id = CAST(:id AS uuid)",
                                        {"e": "[" + ",".join(map(str, v)) + "]", "id": r["id"]})
                done += 1
        print(f"  {done}/{len(rows)} embedded", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="grb")
    ap.add_argument("--batch", type=int, default=20)
    a = ap.parse_args()
    asyncio.run(main(a.dataset, a.batch))
