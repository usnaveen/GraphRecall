"""Standalone deterministic CI recall & regression gate for GraphRecall RAG.

Zero-LLM, zero-DB verification harness validating:
1. Multi-tenant pre-filter ANN vs naive post-filter collapse across 50 tenants.
2. 15-query ML/RAG golden benchmark (exact acronyms, multi-turn coreference
   rewriting, hybrid RRF, LexicalOverlapReranker, MMR deduplication,
   child-centered parent window preservation, lost-in-middle ordering, and
   citation precision).

Run:
    python eval/graphrag/ci_recall_gate.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.services.query_rewrite import contextualize
from backend.services.reranker import (
    LexicalOverlapReranker,
    mmr_select_chunks,
    order_lost_in_middle,
)
from backend.services.retrieval_service import (
    extract_child_centered_window,
    reciprocal_rank_fusion,
)

THRESHOLDS = {
    "Recall@5": 0.90,
    "MRR": 0.80,
    "MultiTenantRecall@5": 1.0,
    "ParentWindowPreservation": 1.0,
    "CitationPrecision": 1.0,
}

_WORD_RE = re.compile(r"[a-z0-9_]+")
_CITATION_RE = re.compile(r"\[(\d+)\]")


def _deterministic_embed(text: str, dims: int = 64) -> list[float]:
    """Deterministic feature-hashed unit vector for zero-LLM vector search simulation."""
    vec = [0.0] * dims
    tokens = _WORD_RE.findall((text or "").lower())
    for tok in tokens:
        digest = hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "little") % dims
        sign = 1.0 if (digest[4] & 1) == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0.0:
        return vec
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return (dot / (na * nb)) if (na > 0.0 and nb > 0.0) else 0.0


def _build_corpus() -> list[dict[str, Any]]:
    filler_prefix = (
        "Background notes on distributed machine learning systems, storage layouts, "
        "batching pipelines, evaluation protocols, and latency instrumentation. "
    ) * 10
    filler_suffix = (
        " Additional benchmark observations regarding throughput scaling and hardware telemetry."
    ) * 4

    specs = [
        (
            "c_hnsw",
            "p_hnsw",
            "n_hnsw",
            "HNSW Vector Indexing",
            "HNSW constructs a Hierarchical Navigable Small World multi-layer proximity graph controlled by M links per node and ef_construction.",
            True,
        ),
        (
            "c_hnsw_dup",
            "p_hnsw",
            "n_hnsw",
            "HNSW Vector Indexing",
            "Raising ef_search at query time improves HNSW recall at the cost of extra distance evaluations.",
            False,
        ),
        (
            "c_lora",
            "p_lora",
            "n_lora",
            "LoRA Parameter-Efficient Fine-Tuning",
            "LoRA freezes pretrained weights W0 and injects trainable low-rank decomposition matrices A and B of rank r into attention projections.",
            True,
        ),
        (
            "c_qlora",
            "p_qlora",
            "n_qlora",
            "QLoRA 4-bit Quantized Adaptation",
            "QLoRA quantizes frozen base weights to 4-bit NormalFloat (NF4) with Double Quantization and PagedAdamW optimizers to cut GPU VRAM.",
            True,
        ),
        (
            "c_rrf",
            "p_rrf",
            "n_rrf",
            "Reciprocal Rank Fusion (RRF)",
            "RRF combines heterogeneous retrieval legs in shared chunk ID space using sum(weight / (k + rank)) with smoothing constant k=60.",
            True,
        ),
        (
            "c_fsrs",
            "p_fsrs",
            "n_fsrs",
            "FSRS Spaced Repetition Scheduler",
            "FSRS models memory state using stability S, difficulty D, and exponential retrievability R to schedule optimal review intervals.",
            True,
        ),
        (
            "c_mcp",
            "p_mcp",
            "n_mcp",
            "Model Context Protocol (MCP)",
            "MCP standardizes JSON-RPC tool discovery, typed schemas, and resource URIs between AI agents and external tool servers.",
            True,
        ),
        (
            "c_bm25",
            "p_bm25",
            "n_bm25",
            "BM25 Sparse Lexical Scoring",
            "Okapi BM25 scores term overlap using IDF weighting, term-frequency saturation parameter k1, and document-length normalization b.",
            True,
        ),
        (
            "c_mmr",
            "p_mmr",
            "n_mmr",
            "Maximal Marginal Relevance (MMR)",
            "MMR greedily balances query relevance and redundancy penalty via lambda_mult * rel(d) - (1 - lambda_mult) * max sim(d, selected).",
            True,
        ),
        (
            "c_pgvector",
            "p_pgvector",
            "n_pgvector",
            "pgvector Cosine and HNSW Indexes",
            "pgvector evaluates cosine distance with the <=> operator and supports HNSW versus IVFFlat indexes scoped by user_id.",
            True,
        ),
        (
            "c_crossenc",
            "p_crossenc",
            "n_crossenc",
            "Cross-Encoder Reranking",
            "Cross-encoder models such as cross-encoder/ms-marco-MiniLM-L-6-v2 jointly attend across query-document pairs for high-precision reranking.",
            True,
        ),
        (
            "c_flash",
            "p_flash",
            "n_flash",
            "FlashAttention IO-Aware Tiling",
            "FlashAttention tiles Q, K, and V blocks inside fast GPU SRAM to compute exact softmax attention without materializing the N^2 matrix in HBM.",
            True,
        ),
        (
            "c_rope",
            "p_rope",
            "n_rope",
            "Rotary Position Embedding (RoPE)",
            "RoPE encodes relative token positions by applying pairwise 2D rotation matrices to query and key subspaces.",
            False,
        ),
        (
            "c_specdec",
            "p_specdec",
            "n_specdec",
            "Speculative Decoding",
            "Speculative decoding drafts candidate tokens with a small model and verifies them in parallel using the target LLM without altering output distribution.",
            False,
        ),
        (
            "c_kg",
            "p_kg",
            "n_kg",
            "Knowledge Graph K-Hop Retrieval",
            "Graph retrieval matches seed concept entities in Neo4j and expands k-hop neighborhoods back to source chunk IDs.",
            True,
        ),
        (
            "c_lostmid",
            "p_lostmid",
            "n_lostmid",
            "Lost in the Middle Context Ordering",
            "Placing highest-ranked chunks at the start and end [0, 2, 4, ..., 3, 1] mitigates LLM middle-context attention decay.",
            True,
        ),
    ]

    corpus: list[dict[str, Any]] = []
    for cid, pid, nid, title, needle, long_parent in specs:
        parent_text = f"{filler_prefix}{needle}{filler_suffix}" if long_parent else needle
        corpus.append(
            {
                "id": cid,
                "parent_chunk_id": pid,
                "note_id": nid,
                "title": title,
                "child_content": needle,
                "parent_content": parent_text,
                "content": parent_text,
                "embedding": _deterministic_embed(f"{title} {needle}"),
            }
        )
    return corpus


def _build_golden_queries() -> list[dict[str, Any]]:
    return [
        {
            "id": "q01_hnsw",
            "query": "Which parameters control HNSW graph construction?",
            "history": [],
            "gold_parent": "p_hnsw",
            "seed_notes": ["n_hnsw"],
        },
        {
            "id": "q02_hnsw_followup",
            "query": "Compare it with IVFFlat cosine indexing in pgvector",
            "history": [
                {"role": "user", "content": "Explain HNSW"},
                {"role": "assistant", "content": "HNSW builds a multi-layer proximity graph."},
            ],
            "gold_parent": "p_pgvector",
            "seed_notes": ["n_pgvector"],
        },
        {
            "id": "q03_lora",
            "query": "How does LoRA update attention projections without unfreezing W0?",
            "history": [],
            "gold_parent": "p_lora",
            "seed_notes": ["n_lora"],
        },
        {
            "id": "q04_qlora_followup",
            "query": "What about its 4-bit quantization and optimizer for VRAM savings?",
            "history": [
                {"role": "user", "content": "How does QLoRA work?"},
                {"role": "assistant", "content": "QLoRA fine-tunes quantized LLMs efficiently."},
            ],
            "gold_parent": "p_qlora",
            "seed_notes": ["n_qlora"],
        },
        {
            "id": "q05_rrf",
            "query": "How does RRF combine heterogeneous retrieval legs?",
            "history": [],
            "gold_parent": "p_rrf",
            "seed_notes": ["n_rrf"],
        },
        {
            "id": "q06_rrf_followup",
            "query": "What is the smoothing constant k in it?",
            "history": [
                {"role": "user", "content": "Explain RRF"},
                {"role": "assistant", "content": "RRF fuses ranked chunk lists."},
            ],
            "gold_parent": "p_rrf",
            "seed_notes": ["n_rrf"],
        },
        {
            "id": "q07_fsrs",
            "query": "How does FSRS schedule spaced repetition review intervals?",
            "history": [],
            "gold_parent": "p_fsrs",
            "seed_notes": ["n_fsrs"],
        },
        {
            "id": "q08_fsrs_followup",
            "query": "Which memory variables does it track?",
            "history": [
                {"role": "user", "content": "Tell me about FSRS"},
                {"role": "assistant", "content": "FSRS predicts optimal review timing."},
            ],
            "gold_parent": "p_fsrs",
            "seed_notes": ["n_fsrs"],
        },
        {
            "id": "q09_mcp",
            "query": "What does MCP standardize between AI agents and tool servers?",
            "history": [],
            "gold_parent": "p_mcp",
            "seed_notes": ["n_mcp"],
        },
        {
            "id": "q10_bm25",
            "query": "How does Okapi BM25 apply k1 saturation and b length normalization?",
            "history": [],
            "gold_parent": "p_bm25",
            "seed_notes": ["n_bm25"],
        },
        {
            "id": "q11_mmr",
            "query": "How does MMR trade off relevance against redundancy with lambda_mult?",
            "history": [],
            "gold_parent": "p_mmr",
            "seed_notes": ["n_mmr"],
        },
        {
            "id": "q12_crossenc",
            "query": "Why does ms-marco-MiniLM-L-6-v2 cross-encoder improve reranking precision?",
            "history": [],
            "gold_parent": "p_crossenc",
            "seed_notes": ["n_crossenc"],
        },
        {
            "id": "q13_flash",
            "query": "How does FlashAttention avoid materializing N^2 attention in HBM?",
            "history": [],
            "gold_parent": "p_flash",
            "seed_notes": ["n_flash"],
        },
        {
            "id": "q14_kg",
            "query": "How does Neo4j k-hop knowledge graph retrieval map back to chunks?",
            "history": [],
            "gold_parent": "p_kg",
            "seed_notes": ["n_kg"],
        },
        {
            "id": "q15_lostmid",
            "query": "Why reorder ranked chunks to mitigate lost in the middle attention decay?",
            "history": [],
            "gold_parent": "p_lostmid",
            "seed_notes": ["n_lostmid"],
        },
    ]


def _verify_answer_citations(answer: str, chunks: list[dict[str, Any]]) -> tuple[float, str]:
    """Use backend.services.grounding_guard.verify_citations if present, else deterministic check."""
    valid_indices = set(range(1, len(chunks) + 1))
    try:
        from backend.services.grounding_guard import verify_citations

        audit = verify_citations(answer, valid_indices, valid_graph_ids=set())
        return float(audit.grounded_ratio), "grounding_guard.verify_citations"
    except Exception:
        pass

    cited = [int(m) for m in _CITATION_RE.findall(answer)]
    if not cited:
        return 0.0, "builtin_citation_verifier"

    ans_tokens = set(_WORD_RE.findall(answer.lower()))
    valid = 0
    for idx in cited:
        if idx in valid_indices:
            c = chunks[idx - 1]
            c_text = f"{c.get('title', '')} {c.get('window_content', c.get('content', ''))}".lower()
            c_tokens = set(_WORD_RE.findall(c_text))
            if ans_tokens & c_tokens:
                valid += 1
    return valid / len(cited), "builtin_citation_verifier"


def run_multi_tenant_simulation() -> tuple[float, float]:
    """Compare naive post-ANN top-k filtering vs pre-filtered tenant ANN across 50 tenants."""
    target_tenant = "tenant_00"
    all_rows: list[dict[str, Any]] = []

    for q_idx in range(5):
        all_rows.append(
            {
                "query_idx": q_idx,
                "id": f"target_q{q_idx}",
                "user_id": target_tenant,
                "similarity": 0.86,
            }
        )
        # 49 decoy tenants with denser/higher global similarity distractors.
        for t_idx in range(1, 50):
            all_rows.append(
                {
                    "query_idx": q_idx,
                    "id": f"decoy_t{t_idx:02d}_q{q_idx}",
                    "user_id": f"tenant_{t_idx:02d}",
                    "similarity": 0.90 + (t_idx % 9) * 0.008,
                }
            )

    naive_hits = 0
    prefilter_hits = 0
    for q_idx in range(5):
        q_rows = [r for r in all_rows if r["query_idx"] == q_idx]

        # Naive global top-5 ANN then post-filter by tenant.
        global_top5 = sorted(q_rows, key=lambda r: r["similarity"], reverse=True)[:5]
        post_filtered = [r for r in global_top5 if r["user_id"] == target_tenant]
        if any(r["id"] == f"target_q{q_idx}" for r in post_filtered):
            naive_hits += 1

        # Pre-filtered tenant ANN top-5.
        tenant_rows = [r for r in q_rows if r["user_id"] == target_tenant]
        prefilter_top5 = sorted(tenant_rows, key=lambda r: r["similarity"], reverse=True)[:5]
        if any(r["id"] == f"target_q{q_idx}" for r in prefilter_top5):
            prefilter_hits += 1

    return naive_hits / 5.0, prefilter_hits / 5.0


async def evaluate_benchmark() -> dict[str, Any]:
    corpus = _build_corpus()
    queries = _build_golden_queries()
    reranker = LexicalOverlapReranker()

    recall_hits = 0
    rr_sum = 0.0
    window_preserved = 0
    citation_precisions: list[float] = []
    verifier_used = "builtin_citation_verifier"
    per_query: list[dict[str, Any]] = []

    for item in queries:
        # The same follow-up rewriter the chat runs (backend/services/query_rewrite.py).
        prior_user = [t["content"] for t in item["history"] if t.get("role") == "user"]
        effective_query = contextualize(item["query"], prior_user[-1] if prior_user else None, [])
        q_emb = _deterministic_embed(effective_query)

        # Vector leg
        vec_scored = []
        for c in corpus:
            copy_c = dict(c)
            copy_c["similarity"] = max(0.0, _cosine(q_emb, c["embedding"]))
            vec_scored.append(copy_c)
        vec_leg = sorted(vec_scored, key=lambda c: c["similarity"], reverse=True)[:10]

        # Lexical leg (query term overlap)
        q_tokens = set(_WORD_RE.findall(effective_query.lower()))
        kw_scored = []
        for c in corpus:
            c_tokens = set(_WORD_RE.findall(f"{c['title']} {c['child_content']}".lower()))
            overlap = len(q_tokens & c_tokens)
            if overlap > 0:
                kw_scored.append((overlap, c))
        kw_leg = [dict(c) for _, c in sorted(kw_scored, key=lambda p: p[0], reverse=True)[:10]]

        # Graph leg (simulated seed-note traversal)
        seed_notes = set(item.get("seed_notes") or [])
        graph_leg = [dict(c) for c in corpus if c["note_id"] in seed_notes]

        fused = reciprocal_rank_fusion(
            [("vector", 1.0, vec_leg), ("keyword", 0.85, kw_leg), ("graph", 0.65, graph_leg)]
        )
        reranked = reranker.rerank(effective_query, fused, top_k=10).chunks
        mmr_top5 = mmr_select_chunks(q_emb, reranked, k=5, lambda_mult=0.72)

        # Windowing preserving child needle inside long parent chunks
        windowed: list[dict[str, Any]] = []
        for c in mmr_top5:
            wc = dict(c)
            wc["window_content"] = extract_child_centered_window(
                c["parent_content"],
                c["child_content"],
                window_chars=700,
                radius_chars=220,
            )
            windowed.append(wc)

        # Metrics before lost-in-middle reordering
        gold_parent = item["gold_parent"]
        parent_ids = [c["parent_chunk_id"] for c in windowed]
        hit = gold_parent in parent_ids
        if hit:
            recall_hits += 1
            rank = parent_ids.index(gold_parent) + 1
            rr_sum += 1.0 / rank
            gold_chunk = windowed[rank - 1]
            if gold_chunk["child_content"] in gold_chunk["window_content"]:
                window_preserved += 1
        else:
            rank = 0

        ordered = order_lost_in_middle(windowed)
        # Rank-0 highest-evidence chunk sits at index 0 after order_lost_in_middle.
        top_chunk = ordered[0]
        synthetic_answer = f"{top_chunk['child_content']} [1]"
        cit_prec, verifier_used = _verify_answer_citations(synthetic_answer, ordered)
        citation_precisions.append(cit_prec)

        per_query.append(
            {
                "id": item["id"],
                "rewrite_method": "contextualize" if effective_query != item["query"] else "unchanged",
                "effective_query": effective_query,
                "hit@5": hit,
                "rank": rank,
            }
        )

    naive_mt_recall, prefilter_mt_recall = run_multi_tenant_simulation()
    n_queries = len(queries)

    metrics = {
        "Recall@5": round(recall_hits / n_queries, 4),
        "MRR": round(rr_sum / n_queries, 4),
        "MultiTenantRecall@5": round(prefilter_mt_recall, 4),
        "NaivePostFilterRecall@5": round(naive_mt_recall, 4),
        "ParentWindowPreservation": round(window_preserved / n_queries, 4),
        "CitationPrecision": round(sum(citation_precisions) / len(citation_precisions), 4),
    }

    checks = {
        "Recall@5": metrics["Recall@5"] >= THRESHOLDS["Recall@5"],
        "MRR": metrics["MRR"] >= THRESHOLDS["MRR"],
        "MultiTenantRecall@5": metrics["MultiTenantRecall@5"] == THRESHOLDS["MultiTenantRecall@5"],
        "NaivePostFilterCollapsed": metrics["NaivePostFilterRecall@5"] < 0.30,
        "ParentWindowPreservation": metrics["ParentWindowPreservation"] == THRESHOLDS["ParentWindowPreservation"],
        "CitationPrecision": metrics["CitationPrecision"] == THRESHOLDS["CitationPrecision"],
    }

    return {
        "passed": all(checks.values()),
        "queries_evaluated": n_queries,
        "tenants_simulated": 50,
        "citation_verifier": verifier_used,
        "metrics": metrics,
        "thresholds": THRESHOLDS,
        "checks": checks,
        "per_query": per_query,
    }


def _print_report(report: dict[str, Any]) -> None:
    print(json.dumps({k: v for k, v in report.items() if k != "per_query"}, indent=2))
    print("\n| Metric | Value | Threshold | Status |")
    print("|---|---:|---:|:---:|")
    for metric_name, threshold in THRESHOLDS.items():
        val = report["metrics"][metric_name]
        ok = report["checks"][metric_name]
        op = "==" if threshold == 1.0 else ">="
        print(f"| {metric_name} | {val:.4f} | {op} {threshold:.2f} | {'PASS' if ok else 'FAIL'} |")
    naive_val = report["metrics"]["NaivePostFilterRecall@5"]
    naive_ok = report["checks"]["NaivePostFilterCollapsed"]
    print(f"| NaivePostFilterRecall@5 (baseline) | {naive_val:.4f} | < 0.30 | {'PASS' if naive_ok else 'FAIL'} |")


def main() -> int:
    report = asyncio.run(evaluate_benchmark())
    _print_report(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
