"""Paired A/B benchmark of LEANN-inspired (arXiv:2506.08276) upgrades vs current GraphRecall retrieval.

Tests on golden.r4.jsonl (n=171, 596 child / 119 parent chunks, eval DB read-only):
  1. vector                 Current pgvector HNSW float32 cosine (top 20)
  2. shipped_top5           Exact current prod pipeline: V+K+G RRF (cap=1) -> LexicalReranker(6) -> MMR(k=5)
  3. ablate_vkg_no_cap      V+K+G RRF without premature per-parent cap
  4. graph_1hop             Current Neo4j 1-hop seed -> NoteSource -> chunks
  5. graph_naive_2hop       Unpruned 1-hop Neo4j concept expansion
  6. graph_hub_pruned_2hop  LEANN high-degree-preserving pruning (structural edges + hub bridges only)
  7. leann_two_level_ce     Coarse V+K+G (no cap, top 30) -> single dynamic-batched ONNX Cross-Encoder
  8. leann_two_level_ce_rrf Coarse V+K+G (no cap, top 30) -> ONNX Cross-Encoder + RRF blend (0.75 CE + 0.25 RRF)
  9. leann_two_level_full   Coarse V+K+hub_pruned_2hop (top 30) -> ONNX CE+RRF -> MMR (max_per_parent=2, CE-guided)
 10. binary_only            Offline iOS 1-bit packed binary coarse search (96 B/chunk vs 3,072 B float32)
 11. leann_binary_to_cosine Two-level: 1-bit binary top-40 -> float32 cosine rescore
 12. leann_binary_to_ce     Two-level: 1-bit binary top-40 -> dynamic-batched ONNX Cross-Encoder (0 stored float32)

Usage:
  set -a && source ~/.config/graphrecall/eval.env && set +a && unset DATABASE_URL
  EVAL_RUN=r4 /Users/naveenus/Projects/GraphRecall-backend/.venv/bin/python eval/retrieval/run_leann_ab.py
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

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE.parent / "graphrag"))

import _env  # noqa: E402

KS = (1, 5, 10)
ARMS = (
    "vector",
    "shipped_top5",
    "ablate_vkg_no_cap",
    "graph_1hop",
    "graph_naive_2hop",
    "graph_hub_pruned_2hop",
    "leann_two_level_ce",
    "leann_two_level_ce_rrf",
    "leann_two_level_full",
    "binary_only",
    "leann_binary_to_cosine",
    "leann_binary_to_ce",
)
POPCOUNT_LUT = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


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
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, max(0, int(round((p / 100.0) * (len(s) - 1)))))
    return s[idx]


def _parse_pg_vec(raw: Any) -> np.ndarray:
    if isinstance(raw, str):
        return np.fromstring(raw.strip("[]"), sep=",", dtype=np.float32)
    return np.asarray(raw, dtype=np.float32)


async def load_binary_corpus(pg: Any, user_id: str) -> tuple[list[dict[str, Any]], np.ndarray, np.ndarray]:
    """Load all child chunks for eval_user_id once for in-memory 1-bit binary quantization eval."""
    rows = await pg.execute_query(
        """
        SELECT c.id, c.parent_chunk_id, c.content AS child_content, c.chunk_index,
               p.content AS parent_content, c.note_id, n.title, c.embedding::text AS embedding
        FROM chunks c
        LEFT JOIN chunks p ON c.parent_chunk_id = p.id
        JOIN notes n ON c.note_id = n.id
        WHERE c.user_id = CAST(:user_id AS uuid)
          AND n.user_id = CAST(:user_id AS uuid)
          AND c.chunk_level = 'child'
          AND c.embedding IS NOT NULL
        """,
        {"user_id": user_id},
    )
    chunks: list[dict[str, Any]] = []
    vecs: list[np.ndarray] = []
    for r in rows or []:
        v = _parse_pg_vec(r["embedding"])
        norms = float(np.linalg.norm(v))
        if norms > 0:
            v = v / norms
        vecs.append(v)
        chunks.append({
            "id": str(r["id"]),
            "parent_chunk_id": str(r["parent_chunk_id"]) if r.get("parent_chunk_id") else None,
            "child_content": r.get("child_content") or "",
            "parent_content": r.get("parent_content") or "",
            "content": r.get("parent_content") or r.get("child_content") or "",
            "note_id": str(r["note_id"]),
            "title": r.get("title") or "",
        })
    f32 = np.vstack(vecs).astype(np.float32)
    packed_bin = np.packbits((f32 > 0).astype(np.uint8), axis=1)
    return chunks, f32, packed_bin


async def eval_question(
    q: dict[str, Any],
    user_id: str,
    svc: Any,
    pg: Any,
    neo4j: Any,
    emb: list[float],
    ce_pure: Any,
    ce_blend: Any,
    bin_chunks: list[dict[str, Any]],
    bin_f32: np.ndarray,
    bin_packed: np.ndarray,
) -> tuple[dict[str, list[str]], dict[str, float]]:
    from backend.services.concept_similarity import similar_to_embedding
    from backend.services.reranker import LexicalOverlapReranker, mmr_select_chunks
    from backend.services.retrieval_service import (
        RRF_K,
        attach_chunk_embeddings,
        dedupe_by_parent,
        reciprocal_rank_fusion,
    )

    ids = lambda rows: [str(r.get("id")) for r in (rows or [])]  # noqa: E731
    question = q["question"]
    timings: dict[str, float] = {}

    t0 = time.perf_counter()
    vec, kw = await asyncio.gather(
        svc._vector_search(question, user_id, limit=25, query_embedding=emb, pg_client=pg),
        svc._keyword_search(question, user_id, limit=25, pg_client=pg),
    )
    timings["vec_kw_ms"] = (time.perf_counter() - t0) * 1000.0

    seeds = [s["id"] for s in await similar_to_embedding(user_id, emb, limit=5)]

    async def timed_graph(mode: str) -> list[dict[str, Any]]:
        if not seeds:
            return []
        tg = time.perf_counter()
        rows = await svc._graph_chunk_search(
            user_id=user_id,
            seed_concept_ids=seeds,
            query_embedding=emb,
            limit=15,
            graph_mode=mode,
            pg_client=pg,
            neo4j_client=neo4j,
        )
        timings[f"graph_{mode}_ms"] = (time.perf_counter() - tg) * 1000.0
        return rows

    g_1hop = await timed_graph("1hop")
    g_naive2 = await timed_graph("naive_2hop")
    g_hub2 = await timed_graph("hub_pruned_2hop")

    # 1. vector (top 20) & 2. shipped_top5 (exact current production pipeline)
    t_ship = time.perf_counter()
    vkg_shipped = await svc.hybrid_search(
        question,
        user_id,
        query_embedding=emb,
        seed_concept_ids=seeds or None,
        limit=10,
        candidate_k=20,
        pg_client=pg,
        neo4j_client=neo4j,
    )
    rr_lex = LexicalOverlapReranker().rerank(question, vkg_shipped["chunks"], top_k=6)
    shipped_top5 = mmr_select_chunks(emb, rr_lex.chunks, k=5)
    timings["shipped_end_to_end_ms"] = (time.perf_counter() - t_ship) * 1000.0

    # 3. ablate_vkg_no_cap (coarse pool = 20 per leg, same as run_retrieval_eval)
    tag = lambda rows, name: [{**r, "_source": name} for r in (rows or [])]  # noqa: E731
    fused_1hop_20 = reciprocal_rank_fusion(
        [
            ("vector", 1.0, tag(vec[:20], "vector")),
            ("keyword", 0.85, tag(kw[:20], "keyword")),
            ("graph", 0.65, tag(g_1hop, "graph")),
        ],
        k=RRF_K,
    )
    ablate_vkg_no_cap = ids(fused_1hop_20[:10])

    # 7 & 8. LEANN Two-Level Search: Coarse V+K+G (top 30 uncapped) -> dynamic-batched ONNX CE
    fused_coarse_30 = reciprocal_rank_fusion(
        [
            ("vector", 1.0, tag(vec[:25], "vector")),
            ("keyword", 0.85, tag(kw[:25], "keyword")),
            ("graph", 0.65, tag(g_1hop, "graph")),
        ],
        k=RRF_K,
    )[:30]
    res_ce_pure = ce_pure.rerank(question, fused_coarse_30, top_k=10)
    res_ce_blend = ce_blend.rerank(question, fused_coarse_30, top_k=10)
    timings["ce_batch30_ms"] = res_ce_pure.latency_ms

    # 9. LEANN Full: Coarse V+K+hub_pruned_2hop (top 30) -> ONNX CE+RRF (top 14) -> MMR(k=10, cap=2, CE-guided)
    fused_hub_30 = reciprocal_rank_fusion(
        [
            ("vector", 1.0, tag(vec[:25], "vector")),
            ("keyword", 0.85, tag(kw[:25], "keyword")),
            ("graph", 0.65, tag(g_hub2, "graph")),
        ],
        k=RRF_K,
    )[:30]
    res_hub_ce = ce_blend.rerank(question, fused_hub_30, top_k=14)
    await attach_chunk_embeddings(pg, user_id, res_hub_ce.chunks)
    leann_full_chunks = mmr_select_chunks(
        emb,
        res_hub_ce.chunks,
        k=10,
        lambda_mult=0.78,
        max_per_parent=2,
        prefer_rerank_score=True,
    )
    timings["leann_full_rerank_ms"] = res_hub_ce.latency_ms

    # 10-12. Offline iOS / LEANN Storage Compression Benchmark (1-bit binary -> cosine / ONNX CE)
    tb = time.perf_counter()
    q_arr = np.asarray(emb, dtype=np.float32)
    q_norm = float(np.linalg.norm(q_arr))
    if q_norm > 0:
        q_arr = q_arr / q_norm
    q_bin = np.packbits((q_arr > 0).astype(np.uint8))
    hamming = POPCOUNT_LUT[np.bitwise_xor(bin_packed, q_bin)].sum(axis=1)
    top40_idx = np.argpartition(hamming, min(40, len(hamming) - 1))[:40]
    top40_idx = top40_idx[np.argsort(hamming[top40_idx])]
    timings["binary_hamming_596_ms"] = (time.perf_counter() - tb) * 1000.0

    coarse_bin_chunks = [bin_chunks[int(i)] for i in top40_idx]
    cos_scores = bin_f32[top40_idx] @ q_arr
    cos_order = top40_idx[np.argsort(-cos_scores)[:10]]

    tbc = time.perf_counter()
    bin_ce = ce_pure.rerank(question, coarse_bin_chunks, top_k=10)
    timings["binary_ce_batch40_ms"] = (time.perf_counter() - tbc) * 1000.0

    ranked = {
        "vector": ids(vec[:20]),
        "shipped_top5": ids(shipped_top5),
        "ablate_vkg_no_cap": ablate_vkg_no_cap,
        "graph_1hop": ids(g_1hop),
        "graph_naive_2hop": ids(g_naive2),
        "graph_hub_pruned_2hop": ids(g_hub2),
        "leann_two_level_ce": ids(res_ce_pure.chunks),
        "leann_two_level_ce_rrf": ids(res_ce_blend.chunks),
        "leann_two_level_full": ids(leann_full_chunks),
        "binary_only": [bin_chunks[int(i)]["id"] for i in top40_idx[:10]],
        "leann_binary_to_cosine": [bin_chunks[int(i)]["id"] for i in cos_order],
        "leann_binary_to_ce": ids(bin_ce.chunks),
    }
    return ranked, timings


async def main() -> None:
    _env.setup()
    from backend.db.neo4j_client import get_neo4j_client
    from backend.db.postgres_client import get_postgres_client
    from backend.services.ingestion.embedding_service import EmbeddingService
    from backend.services.reranker import OnnxCrossEncoderReranker
    from backend.services.retrieval_service import RetrievalService

    tag = _env.run_key("grb").split("-", 1)[-1]
    golden_path = HERE / f"golden.{tag}.jsonl"
    golden = [json.loads(line) for line in golden_path.open()]
    user_id = await _env.eval_user_id("grb")
    pg = await get_postgres_client()
    neo4j = await get_neo4j_client()
    svc, embedder = RetrievalService(), EmbeddingService()

    ce_pure = OnnxCrossEncoderReranker(use_child_text=True, rrf_blend_weight=0.0)
    ce_blend = OnnxCrossEncoderReranker(use_child_text=True, rrf_blend_weight=0.25)
    # Warm up ONNX session before timing questions.
    warm = ce_pure.rerank("warm up query", [{"id": "w", "title": "W", "child_content": "warm up text"}], top_k=1)
    assert not warm.used_fallback and warm.method == "onnx_cross_encoder", f"ONNX failed: {warm}"

    bin_chunks, bin_f32, bin_packed = await load_binary_corpus(pg, user_id)
    f32_bytes = int(bin_f32.nbytes)
    bin_bytes = int(bin_packed.nbytes)
    print(
        f"Loaded binary corpus: n={len(bin_chunks)} chunks | float32={f32_bytes/1024:.1f} KB "
        f"| 1-bit packed={bin_bytes/1024:.1f} KB ({f32_bytes / max(1, bin_bytes):.1f}x smaller)",
        flush=True,
    )

    rows: list[dict[str, Any]] = []
    all_timings: list[dict[str, float]] = []
    t0 = time.time()
    for i, q in enumerate(golden, 1):
        emb = await embedder.embed_query(q["question"])
        ranked, timings = await eval_question(
            q, user_id, svc, pg, neo4j, emb, ce_pure, ce_blend, bin_chunks, bin_f32, bin_packed
        )
        rel = set(q["relevant_child_ids"])
        rows.append({
            "id": q["id"],
            "type": q["type"],
            "scores": {arm: metrics(ranked[arm], rel) for arm in ARMS},
        })
        all_timings.append(timings)
        if i % 25 == 0:
            print(f"[{i}/{len(golden)}] {time.time() - t0:.1f}s", flush=True)

    metric_names = list(rows[0]["scores"]["vector"].keys())
    summary: dict[str, Any] = {
        "n": len(rows),
        "corpus": {
            "chunks": len(bin_chunks),
            "float32_bytes": f32_bytes,
            "binary_1bit_bytes": bin_bytes,
            "compression_ratio": round(f32_bytes / max(1, bin_bytes), 2),
        },
        "overall": {},
        "by_type": {},
        "diff_vs_shipped": {},
        "diff_vs_vector": {},
        "latency_ms": {},
    }

    for arm in ARMS:
        summary["overall"][arm] = {
            m: (
                sum(r["scores"][arm][m] for r in rows) / len(rows),
                *bootstrap([r["scores"][arm][m] for r in rows]),
            )
            for m in metric_names
        }
    for t in sorted({r["type"] for r in rows}):
        sub = [r for r in rows if r["type"] == t]
        summary["by_type"][t] = {
            "n": len(sub),
            **{
                arm: {m: sum(r["scores"][arm][m] for r in sub) / len(sub) for m in ("recall@5", "mrr@10", "ndcg@10")}
                for arm in ARMS
            },
        }
    for base_name, target_dict in (("shipped_top5", summary["diff_vs_shipped"]), ("vector", summary["diff_vs_vector"])):
        for arm in ARMS:
            if arm == base_name:
                continue
            target_dict[arm] = {
                m: (
                    sum(r["scores"][arm][m] - r["scores"][base_name][m] for r in rows) / len(rows),
                    *bootstrap([r["scores"][arm][m] - r["scores"][base_name][m] for r in rows]),
                )
                for m in ("recall@1", "recall@5", "mrr@10", "ndcg@10")
            }

    timing_keys = sorted({k for tm in all_timings for k in tm})
    for k in timing_keys:
        vals = [tm[k] for tm in all_timings if k in tm]
        summary["latency_ms"][k] = {
            "mean": round(sum(vals) / len(vals), 2),
            "p50": round(percentile(vals, 50), 2),
            "p95": round(percentile(vals, 95), 2),
        }

    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"leann_ab.{tag}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))

    lines = [
        f"# LEANN vs Current Retrieval A/B Eval ({golden_path.name}, n={len(rows)})",
        "",
        "| arm | recall@1 | recall@5 | recall@10 | hit@5 | MRR@10 | nDCG@10 |",
        "|---|---|---|---|---|---|---|",
    ]
    for arm in ARMS:
        o = summary["overall"][arm]
        fmt = lambda m: f"{o[m][0]:.3f} [{o[m][1]:.2f}, {o[m][2]:.2f}]"  # noqa: E731
        lines.append(
            f"| {arm} | {o['recall@1'][0]:.3f} | {fmt('recall@5')} | {o['recall@10'][0]:.3f} | "
            f"{o['hit@5'][0]:.3f} | {o['mrr@10'][0]:.3f} | {fmt('ndcg@10')} |"
        )
    lines += ["", "Paired diff vs shipped_top5 (95% CI):", ""]
    for arm, d in summary["diff_vs_shipped"].items():
        lines.append(
            f"- {arm}: recall@1 {d['recall@1'][0]:+.3f} [{d['recall@1'][1]:+.3f}, {d['recall@1'][2]:+.3f}], "
            f"recall@5 {d['recall@5'][0]:+.3f} [{d['recall@5'][1]:+.3f}, {d['recall@5'][2]:+.3f}], "
            f"MRR@10 {d['mrr@10'][0]:+.3f}, nDCG@10 {d['ndcg@10'][0]:+.3f} [{d['ndcg@10'][1]:+.3f}, {d['ndcg@10'][2]:+.3f}]"
        )
    lines += ["", "Paired diff vs vector (95% CI):", ""]
    for arm, d in summary["diff_vs_vector"].items():
        lines.append(
            f"- {arm}: recall@1 {d['recall@1'][0]:+.3f}, "
            f"recall@5 {d['recall@5'][0]:+.3f} [{d['recall@5'][1]:+.3f}, {d['recall@5'][2]:+.3f}], "
            f"nDCG@10 {d['ndcg@10'][0]:+.3f} [{d['ndcg@10'][1]:+.3f}, {d['ndcg@10'][2]:+.3f}]"
        )
    lines += ["", "By question type (recall@5 / nDCG@10):", ""]
    for t, d in summary["by_type"].items():
        lines.append(f"- {t} (n={d['n']}): " + ", ".join(f"{a} {d[a]['recall@5']:.2f}/{d[a]['ndcg@10']:.2f}" for a in ARMS))
    lines += ["", "Latency (ms/query):", ""]
    for k, v in summary["latency_ms"].items():
        lines.append(f"- {k}: mean={v['mean']} ms, p50={v['p50']} ms, p95={v['p95']} ms")
    lines += [
        "",
        f"Binary quantization storage (n={len(bin_chunks)} child chunks, 768 dims): "
        f"float32={f32_bytes/1024:.1f} KB vs 1-bit packed={bin_bytes/1024:.1f} KB "
        f"({f32_bytes / max(1, bin_bytes):.1f}x smaller).",
    ]
    md = "\n".join(lines) + "\n"
    (out_dir / f"leann_ab.{tag}.md").write_text(md)
    print("\n" + md)


if __name__ == "__main__":
    asyncio.run(main())
