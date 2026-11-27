"""Verify the exact wired production chat retrieval flow on golden.r4.jsonl (n=171).

Compares:
  - vector            pgvector HNSW cosine top-20
  - shipped_top5_old  previous prod: V+K+G(1hop) RRF (cap=1, limit=10) -> LexicalReranker(6) -> MMR(k=5, cap=1)
  - wired_fp32_top5   exact new chat_graph flow using FP32 ONNX CE -> MMR(k=5, cap=2, lam=0.88)
  - wired_int8_top5   exact new chat_graph flow using INT8 ONNX CE -> MMR(k=5, cap=2, lam=0.88)
"""
from __future__ import annotations

import asyncio
import json
import math
import random
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE.parent / "graphrag"))

import _env  # noqa: E402

KS = (1, 5, 10)
ARMS = ("vector", "shipped_top5_old", "wired_fp32_top5", "wired_int8_top5")


def metrics(ranked: list[str], relevant: set[str]) -> dict[str, float]:
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
    dcg = sum(1.0 / math.log2(i + 1) for i, c in enumerate(ranked[:10], 1) if c in relevant)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), 10) + 1))
    out["ndcg@10"] = dcg / idcg if idcg else 0.0
    return out


def bootstrap(values: list[float], n: int = 2000, seed: int = 7) -> tuple[float, float]:
    rng = random.Random(seed)
    means = sorted(sum(rng.choice(values) for _ in values) / len(values) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def percentile(values: list[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))] if s else 0.0


async def main() -> None:
    _env.setup()
    from backend.db.neo4j_client import get_neo4j_client
    from backend.db.postgres_client import get_postgres_client
    from backend.services.concept_similarity import similar_to_embedding
    from backend.services.ingestion.embedding_service import EmbeddingService
    from backend.services.reranker import (
        DEFAULT_INT8_ONNX_MODEL,
        DEFAULT_ONNX_MODEL,
        LexicalOverlapReranker,
        OnnxCrossEncoderReranker,
        mmr_select_chunks,
    )
    from backend.services.retrieval_service import RetrievalService, attach_chunk_embeddings

    tag = _env.run_key("grb").split("-", 1)[-1]
    golden_path = HERE / f"golden.{tag}.jsonl"
    golden = [json.loads(line) for line in golden_path.open()]
    user_id = await _env.eval_user_id("grb")
    pg = await get_postgres_client()
    neo4j = await get_neo4j_client()
    svc, embedder = RetrievalService(), EmbeddingService()

    ce_fp32 = OnnxCrossEncoderReranker(model_path=DEFAULT_ONNX_MODEL, use_child_text=True, rrf_blend_weight=0.0)
    ce_int8 = OnnxCrossEncoderReranker(model_path=DEFAULT_INT8_ONNX_MODEL, use_child_text=True, rrf_blend_weight=0.0)
    for r in (ce_fp32, ce_int8):
        w = r.rerank("warm up", [{"id": "w", "title": "W", "child_content": "warm up text"}], top_k=1)
        assert not w.used_fallback and w.method == "onnx_cross_encoder"

    rows: list[dict[str, Any]] = []
    timings: dict[str, list[float]] = {"old_e2e_ms": [], "wired_fp32_e2e_ms": [], "wired_int8_e2e_ms": [], "ce_fp32_ms": [], "ce_int8_ms": []}
    ids = lambda xs: [str(x.get("id")) for x in (xs or [])]  # noqa: E731

    t0 = time.time()
    for i, q in enumerate(golden, 1):
        question = q["question"]
        emb = await embedder.embed_query(question)
        seeds = [s["id"] for s in await similar_to_embedding(user_id, emb, limit=5)]

        vec = await svc._vector_search(question, user_id, limit=20, query_embedding=emb, pg_client=pg)

        t_old = time.perf_counter()
        old_h = await svc.hybrid_search(
            question, user_id, query_embedding=emb, seed_concept_ids=seeds or None,
            limit=10, candidate_k=20, max_per_parent=1, graph_mode="1hop", attach_embeddings=True,
            pg_client=pg, neo4j_client=neo4j,
        )
        old_rr = LexicalOverlapReranker().rerank(question, old_h["chunks"], top_k=6)
        old_top5 = mmr_select_chunks(emb, old_rr.chunks, k=5)
        timings["old_e2e_ms"].append((time.perf_counter() - t_old) * 1000.0)

        t_new = time.perf_counter()
        new_h = await svc.hybrid_search(
            question, user_id, query_embedding=emb, seed_concept_ids=seeds or None,
            limit=25, candidate_k=25, max_per_parent=0, graph_mode="hub_pruned_2hop", attach_embeddings=False,
            pg_client=pg, neo4j_client=neo4j,
        )
        coarse_elapsed_ms = (time.perf_counter() - t_new) * 1000.0

        t_f = time.perf_counter()
        rr_fp32 = ce_fp32.rerank(question, new_h["chunks"], top_k=8)
        await attach_chunk_embeddings(pg, user_id, rr_fp32.chunks)
        fp32_top5 = mmr_select_chunks(emb, rr_fp32.chunks, k=5, lambda_mult=0.88, max_per_parent=2, prefer_rerank_score=True)
        timings["wired_fp32_e2e_ms"].append(coarse_elapsed_ms + (time.perf_counter() - t_f) * 1000.0)
        timings["ce_fp32_ms"].append(rr_fp32.latency_ms)

        t_i = time.perf_counter()
        rr_int8 = ce_int8.rerank(question, new_h["chunks"], top_k=8)
        await attach_chunk_embeddings(pg, user_id, rr_int8.chunks)
        int8_top5 = mmr_select_chunks(emb, rr_int8.chunks, k=5, lambda_mult=0.88, max_per_parent=2, prefer_rerank_score=True)
        timings["wired_int8_e2e_ms"].append(coarse_elapsed_ms + (time.perf_counter() - t_i) * 1000.0)
        timings["ce_int8_ms"].append(rr_int8.latency_ms)

        ranked = {
            "vector": ids(vec),
            "shipped_top5_old": ids(old_top5),
            "wired_fp32_top5": ids(fp32_top5),
            "wired_int8_top5": ids(int8_top5),
        }
        rel = set(q["relevant_child_ids"])
        rows.append({"id": q["id"], "type": q["type"], "scores": {a: metrics(ranked[a], rel) for a in ARMS}})
        if i % 30 == 0:
            print(f"[{i}/{len(golden)}] {time.time() - t0:.1f}s", flush=True)

    metric_names = list(rows[0]["scores"]["vector"].keys())
    summary: dict[str, Any] = {"n": len(rows), "overall": {}, "diff_vs_old": {}, "diff_vs_vector": {}, "latency_ms": {}}
    for arm in ARMS:
        summary["overall"][arm] = {
            m: (sum(r["scores"][arm][m] for r in rows) / len(rows), *bootstrap([r["scores"][arm][m] for r in rows]))
            for m in metric_names
        }
    for base, target in (("shipped_top5_old", summary["diff_vs_old"]), ("vector", summary["diff_vs_vector"])):
        for arm in ARMS:
            if arm == base:
                continue
            target[arm] = {
                m: (
                    sum(r["scores"][arm][m] - r["scores"][base][m] for r in rows) / len(rows),
                    *bootstrap([r["scores"][arm][m] - r["scores"][base][m] for r in rows]),
                )
                for m in ("recall@1", "recall@5", "mrr@10", "ndcg@10")
            }
    for k, vals in timings.items():
        summary["latency_ms"][k] = {"mean": round(sum(vals) / len(vals), 2), "p50": round(percentile(vals, 50), 2), "p95": round(percentile(vals, 95), 2)}

    lines = [
        f"# Wired Pipeline Verification ({golden_path.name}, n={len(rows)})",
        "",
        "| arm | recall@1 | recall@5 | hit@5 | MRR@10 | nDCG@10 |",
        "|---|---|---|---|---|---|",
    ]
    for arm in ARMS:
        o = summary["overall"][arm]
        lines.append(
            f"| {arm} | {o['recall@1'][0]:.3f} | {o['recall@5'][0]:.3f} [{o['recall@5'][1]:.2f}, {o['recall@5'][2]:.2f}] | "
            f"{o['hit@5'][0]:.3f} | {o['mrr@10'][0]:.3f} | {o['ndcg@10'][0]:.3f} [{o['ndcg@10'][1]:.2f}, {o['ndcg@10'][2]:.2f}] |"
        )
    lines += ["", "Paired diff vs shipped_top5_old (95% CI):", ""]
    for arm, d in summary["diff_vs_old"].items():
        lines.append(
            f"- {arm}: recall@1 {d['recall@1'][0]:+.3f}, recall@5 {d['recall@5'][0]:+.3f} [{d['recall@5'][1]:+.3f}, {d['recall@5'][2]:+.3f}], "
            f"MRR@10 {d['mrr@10'][0]:+.3f}, nDCG@10 {d['ndcg@10'][0]:+.3f} [{d['ndcg@10'][1]:+.3f}, {d['ndcg@10'][2]:+.3f}]"
        )
    lines += ["", "Paired diff vs vector (95% CI):", ""]
    for arm, d in summary["diff_vs_vector"].items():
        lines.append(
            f"- {arm}: recall@1 {d['recall@1'][0]:+.3f}, recall@5 {d['recall@5'][0]:+.3f} [{d['recall@5'][1]:+.3f}, {d['recall@5'][2]:+.3f}], "
            f"nDCG@10 {d['ndcg@10'][0]:+.3f} [{d['ndcg@10'][1]:+.3f}, {d['ndcg@10'][2]:+.3f}]"
        )
    lines += ["", "Latency (ms/query):", ""]
    for k, v in summary["latency_ms"].items():
        lines.append(f"- {k}: mean={v['mean']} ms, p50={v['p50']} ms, p95={v['p95']} ms")

    out_dir = HERE / "results"
    (out_dir / f"wired_ab.{tag}.md").write_text("\n".join(lines) + "\n")
    (out_dir / f"wired_ab.{tag}.json").write_text(json.dumps(summary, indent=1))
    print("\n" + "\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main())
