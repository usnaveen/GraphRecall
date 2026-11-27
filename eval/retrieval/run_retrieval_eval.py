"""Score GraphRecall's retrieval stages on the golden set: recall@k, hit@k, MRR@10, nDCG@10.

No LLM is called: questions are embedded once (cached), then every arm ranks child chunks and is scored
against the mechanically labelled relevant chunks (build_golden.py). Arms, cheapest first:

  vector          pgvector cosine over child chunks (top 20)
  keyword         Postgres full-text search (websearch_to_tsquery + ts_rank_cd) (top 20)
  graph           seed concepts by meaning -> (:NoteSource)-[:EXPLAINS]->(:Concept) -> chunks (top 15)
  rrf_vk          RRF of vector + keyword, one child per parent (what hybrid_search returns, no graph)
  rrf_vkg         RRF of vector + keyword + graph, one child per parent (the shipped retrieval, limit 10)
  shipped_top5    the chat's pipeline: uncapped pool of 25 -> cross-encoder -> MMR (k=5, <=2 per parent)

Ablations (eval only, same leg results and weights as hybrid_search):
  ablate_vkg_no_parent_cap   RRF of all three legs without the one-child-per-parent cap
  ablate_vg                  RRF of vector + graph (no keyword leg), one child per parent
  ablate_vg_no_parent_cap    RRF of vector + graph without the cap

    EVAL_RUN=r3 PYTHONPATH=. python eval/retrieval/run_retrieval_eval.py     # -> eval/retrieval/results/retrieval.r3.{json,md}

Relevance is binary; nDCG uses the ideal ranking of all labelled chunks. 95% CIs are percentile bootstrap
over questions (2,000 resamples, seed 7); differences vs `vector` are paired.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "graphrag"))

import _env  # noqa: E402

KS = (1, 5, 10)
ARMS = ("vector", "keyword", "graph", "rrf_vk", "rrf_vkg", "shipped_top5",
        "ablate_vkg_no_parent_cap", "ablate_vg", "ablate_vg_no_parent_cap")


def metrics(ranked: list[str], relevant: set[str], grades: dict[str, int] | None = None) -> dict[str, float]:
    out: dict[str, float] = {}
    for k in KS:
        top = ranked[:k]
        hits = sum(1 for c in top if c in relevant)
        out[f"recall@{k}"] = hits / len(relevant)
        out[f"hit@{k}"] = 1.0 if hits else 0.0
    rr = 0.0
    for i, c in enumerate(ranked[:10], 1):
        if c in relevant:
            rr = 1.0 / i
            break
    out["mrr@10"] = rr
    # Graded gains (2 = answers it, 1 = helps) when a human labelled them, else binary.
    gain = {c: float((grades or {}).get(c, 1)) for c in relevant}
    dcg = sum((2 ** gain[c] - 1) / math.log2(i + 1) for i, c in enumerate(ranked[:10], 1) if c in gain)
    ideal = sorted(gain.values(), reverse=True)[:10]
    idcg = sum((2 ** g - 1) / math.log2(i + 1) for i, g in enumerate(ideal, 1))
    out["ndcg@10"] = dcg / idcg if idcg else 0.0
    return out


def bootstrap(values: list[float], n: int = 2000, seed: int = 7) -> tuple[float, float]:
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


async def rank_all(q: dict, user_id: str, svc, pg, emb) -> dict[str, list[str]]:
    from backend.services.concept_similarity import similar_to_embedding
    from backend.services.reranker import mmr_select_chunks

    ids = lambda rows: [str(r.get("id")) for r in rows or []]  # noqa: E731
    question = q["question"]
    vec, kw = await asyncio.gather(
        svc._vector_search(question, user_id, limit=20, query_embedding=emb, pg_client=pg),
        svc._keyword_search(question, user_id, limit=20, pg_client=pg),
    )
    seeds = [s["id"] for s in await similar_to_embedding(user_id, emb, limit=5)]
    graph = await svc._graph_chunk_search(user_id=user_id, seed_concept_ids=seeds, query_embedding=emb,
                                          limit=15, pg_client=pg) if seeds else []
    vk = await svc.hybrid_search(question, user_id, query_embedding=emb, limit=10, candidate_k=20, pg_client=pg)
    vkg = await svc.hybrid_search(question, user_id, query_embedding=emb, seed_concept_ids=seeds or None,
                                  limit=10, candidate_k=20, pg_client=pg)
    from backend.services.retrieval_service import RRF_K, dedupe_by_parent, reciprocal_rank_fusion

    def fuse(legs, cap):
        fused = reciprocal_rank_fusion([(n, w, rows) for n, w, rows in legs if rows], k=RRF_K)
        return ids(dedupe_by_parent(fused, limit=10) if cap else fused[:10])
    tag = lambda rows, name: [{**r, "_source": name} for r in rows or []]  # noqa: E731
    v_, k_, g_ = tag(vec, "vector"), tag(kw, "keyword"), tag(graph, "graph")
    abl = {"ablate_vkg_no_parent_cap": fuse([("vector", 1.0, v_), ("keyword", 0.85, k_), ("graph", 0.65, g_)], False),
           "ablate_vg": fuse([("vector", 1.0, v_), ("graph", 0.65, g_)], True),
           "ablate_vg_no_parent_cap": fuse([("vector", 1.0, v_), ("graph", 0.65, g_)], False)}
    # What chat_graph.get_context_node runs: wide uncapped pool -> cross-encoder (lexical if the model
    # is missing) -> embeddings for the survivors -> MMR, at most 2 children per parent.
    from backend.services.reranker import get_reranker
    from backend.services.retrieval_service import attach_chunk_embeddings

    coarse = await svc.hybrid_search(question, user_id, query_embedding=emb, seed_concept_ids=seeds or None,
                                     limit=25, candidate_k=25, max_per_parent=0, attach_embeddings=False, pg_client=pg)
    rr = get_reranker().rerank(question, coarse["chunks"], top_k=8)
    await attach_chunk_embeddings(pg, user_id, rr.chunks)
    is_ce = rr.method == "onnx_cross_encoder"
    top5 = mmr_select_chunks(emb, rr.chunks, k=5, lambda_mult=0.88 if is_ce else 0.72, max_per_parent=2,
                             prefer_rerank_score=is_ce)
    return {"vector": ids(vec), "keyword": ids(kw), "graph": ids(graph), "rrf_vk": ids(vk["chunks"]),
            "rrf_vkg": ids(vkg["chunks"]), "shipped_top5": ids(top5), **abl, "_seeds": len(seeds)}


async def main() -> None:
    _env.setup()
    from backend.db.postgres_client import get_postgres_client
    from backend.services.ingestion.embedding_service import EmbeddingService
    from backend.services.retrieval_service import RetrievalService

    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--golden", help="golden file (default eval/retrieval/golden.<EVAL_RUN>.jsonl)")
    ap.add_argument("--user-id", help="whose corpus to search (default: the eval user for EVAL_RUN)")
    args = ap.parse_args()
    tag = _env.run_key("grb").split("-", 1)[-1]
    golden_path = Path(args.golden) if args.golden else HERE / f"golden.{tag}.jsonl"
    if args.golden:
        tag = golden_path.stem.replace("golden.", "")
    golden = [json.loads(l) for l in golden_path.open() if json.loads(l).get("relevant_child_ids")]
    user_id = args.user_id or await _env.eval_user_id("grb")
    pg = await get_postgres_client()
    svc, embedder = RetrievalService(), EmbeddingService()

    rows, t0 = [], time.time()
    for i, q in enumerate(golden, 1):
        emb = await embedder.embed_query(q["question"])
        ranked = await rank_all(q, user_id, svc, pg, emb)
        rel = set(q["relevant_child_ids"])
        grades = q.get("grades")
        rows.append({"id": q["id"], "type": q["type"], "seeds": ranked.pop("_seeds"),
                     "scores": {arm: metrics(ranked[arm], rel, grades) for arm in ARMS}})
        if i % 20 == 0:
            print(f"[{i}/{len(golden)}] {time.time() - t0:.0f}s", flush=True)

    names = list(rows[0]["scores"]["vector"].keys())
    summary: dict = {"n": len(rows), "by_type": {}, "overall": {}, "diff_vs_vector": {}}
    for arm in ARMS:
        summary["overall"][arm] = {m: (sum(r["scores"][arm][m] for r in rows) / len(rows),
                                       *bootstrap([r["scores"][arm][m] for r in rows])) for m in names}
    for t in sorted({r["type"] for r in rows}):
        sub = [r for r in rows if r["type"] == t]
        summary["by_type"][t] = {"n": len(sub), **{arm: {m: sum(r["scores"][arm][m] for r in sub) / len(sub)
                                                         for m in ("recall@5", "mrr@10", "ndcg@10")} for arm in ARMS}}
    for arm in ARMS[1:]:
        summary["diff_vs_vector"][arm] = {m: (sum(r["scores"][arm][m] - r["scores"]["vector"][m] for r in rows) / len(rows),
                                              *bootstrap([r["scores"][arm][m] - r["scores"]["vector"][m] for r in rows]))
                                          for m in ("recall@5", "ndcg@10")}

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"retrieval.{tag}.json").write_text(json.dumps({"golden": golden_path.name, "summary": summary,
                                                               "rows": rows}, indent=1))
    lines = [f"# Retrieval eval ({golden_path.name}, n={len(rows)})", "",
             "| arm | recall@1 | recall@5 | recall@10 | hit@5 | MRR@10 | nDCG@10 |", "|---|---|---|---|---|---|---|"]
    for arm in ARMS:
        o = summary["overall"][arm]
        f = lambda m: f"{o[m][0]:.3f} [{o[m][1]:.2f}, {o[m][2]:.2f}]"  # noqa: E731
        lines.append(f"| {arm} | {o['recall@1'][0]:.3f} | {f('recall@5')} | {o['recall@10'][0]:.3f} | "
                     f"{o['hit@5'][0]:.3f} | {o['mrr@10'][0]:.3f} | {f('ndcg@10')} |")
    lines += ["", "Difference vs vector (paired, 95% CI):", ""]
    for arm, d in summary["diff_vs_vector"].items():
        lines.append(f"- {arm}: recall@5 {d['recall@5'][0]:+.3f} [{d['recall@5'][1]:+.3f}, {d['recall@5'][2]:+.3f}], "
                     f"nDCG@10 {d['ndcg@10'][0]:+.3f} [{d['ndcg@10'][1]:+.3f}, {d['ndcg@10'][2]:+.3f}]")
    lines += ["", "By question type (recall@5 / nDCG@10):", ""]
    for t, d in summary["by_type"].items():
        lines.append(f"- {t} (n={d['n']}): " + ", ".join(f"{a} {d[a]['recall@5']:.2f}/{d[a]['ndcg@10']:.2f}" for a in ARMS))
    lines.append(f"\nQuestions with any graph seed: {sum(1 for r in rows if r['seeds'])}/{len(rows)}")
    (out_dir / f"retrieval.{tag}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main())
