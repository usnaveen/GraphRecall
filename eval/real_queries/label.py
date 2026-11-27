"""Label your own real questions for the retrieval golden set (the gap benchmark data cannot close).

For each question you actually asked the assistant (chat history), the tool retrieves candidate
passages from your notes (vector top 10 plus what the shipped pipeline would send) and asks you to
grade each one:

  2  answers the question        1  helps / partially relevant        0  not relevant
  s  skip this question          q  save and quit (resumable)

Output: eval/real_queries/data/golden.real.jsonl (git-ignored: it holds your questions and note ids).
Then score retrieval on it with graded nDCG:

    DATABASE_URL=postgresql://$USER@localhost:5432/graphrecall PYTHONPATH=. \\
      python eval/real_queries/label.py --user-id <your uuid>
    DATABASE_URL=postgresql://$USER@localhost:5432/graphrecall PYTHONPATH=. \\
      python eval/retrieval/run_retrieval_eval.py --golden eval/real_queries/data/golden.real.jsonl --user-id <your uuid>

Find your id with:  psql -d graphrecall -c "select id, name from users"
Aim for 50+ questions: enough to see a 0.1 change in recall@5 outside the noise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "golden.real.jsonl"
_SMALL_TALK = re.compile(r"^\s*(hi|hello|hey|thanks?|thank you|ok(ay)?|cool|great)\b[\s!.?]*$", re.I)


async def questions(pg, user_id: str) -> list[str]:
    rows = await pg.execute_query(
        """
        SELECT cm.content, MIN(cm.created_at) AS first_at
        FROM chat_messages cm JOIN chat_conversations cc ON cc.id = cm.conversation_id
        WHERE cc.user_id = :user_id AND cm.role = 'user' AND length(cm.content) >= 12
        GROUP BY cm.content ORDER BY first_at
        """,
        {"user_id": user_id},
    )
    return [r["content"].strip() for r in rows or [] if not _SMALL_TALK.match(r["content"])]


async def candidates(question: str, user_id: str, pg) -> list[dict]:
    from backend.services.reranker import get_reranker, mmr_select_chunks
    from backend.services.retrieval_service import RetrievalService

    svc = RetrievalService()
    emb = await svc.embedding_service.embed_query(question)
    vec = await svc._vector_search(question, user_id, limit=10, query_embedding=emb, pg_client=pg)
    coarse = await svc.hybrid_search(question, user_id, query_embedding=emb, limit=25, candidate_k=25,
                                     max_per_parent=0, attach_embeddings=False, pg_client=pg)
    rr = get_reranker().rerank(question, coarse["chunks"], top_k=8)
    shipped = mmr_select_chunks(emb, rr.chunks, k=5, max_per_parent=2)
    seen, out = set(), []
    for c in list(shipped) + list(vec):
        cid = str(c.get("id"))
        if cid not in seen:
            seen.add(cid)
            out.append(c)
    return out[:12]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", required=True)
    args = ap.parse_args()
    from backend.db.postgres_client import get_postgres_client

    pg = await get_postgres_client()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(l)["question"] for l in OUT.open()} if OUT.exists() else set()
    todo = [q for q in await questions(pg, args.user_id) if q not in done]
    print(f"{len(done)} labelled, {len(todo)} to go. Grades: 2 answers it, 1 helps, 0 no. s skip, q quit.\n")
    for qi, q in enumerate(todo, 1):
        print("=" * 80 + f"\n[{qi}/{len(todo)}] {q}\n")
        grades: dict[str, int] = {}
        for ci, c in enumerate(await candidates(q, args.user_id, pg), 1):
            snippet = re.sub(r"\s+", " ", c.get("child_content") or c.get("content") or "")[:320]
            print(f"  ({ci}) {c.get('title') or 'Note'}\n" + textwrap.indent(textwrap.fill(snippet, 76), "      "))
            ans = input("      grade [2/1/0, s, q]: ").strip().lower()
            if ans == "q":
                print(f"saved to {OUT}")
                return
            if ans == "s":
                grades = {}
                break
            if ans in ("1", "2"):
                grades[str(c["id"])] = int(ans)
        if grades:
            with OUT.open("a") as fh:
                fh.write(json.dumps({"id": f"real-{len(done) + qi}", "type": "real", "question": q,
                                     "relevant_child_ids": sorted(grades), "grades": grades}) + "\n")
        elif ans != "s":
            with OUT.open("a") as fh:  # nothing relevant: a retrieval miss worth keeping (unanswerable set)
                fh.write(json.dumps({"id": f"real-{len(done) + qi}", "type": "real-unanswerable",
                                     "question": q, "relevant_child_ids": [], "grades": {}}) + "\n")
    print(f"all done: {OUT}")


if __name__ == "__main__":
    if not sys.stdin.isatty():
        sys.exit("label.py is interactive: run it in a terminal")
    asyncio.run(main())
