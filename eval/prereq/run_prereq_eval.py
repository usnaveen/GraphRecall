"""Does the graph help on prerequisite-chain questions? (The case vector search should be bad at.)

Setup (not circular):
- Links: PREREQUISITE_OF edges A -> B that ingestion extracted into the eval graphs (r4, h1), filtered to
  ones a human labelled as real prerequisites (labels.*.jsonl) and to *specific* prerequisites (A named in
  at most 15 chunks, so a generic term cannot be found by accident).
- Question: "Explain B from the ground up, including the concepts it builds on." It names B, never A.
- Ground truth for "the context covers A": A's name appears in the text the model receives. That is
  measured on text, independent of any graph link.

Arms, per question:
  vector_top5        the 5 nearest child chunks (what a plain RAG app would send)
  shipped_chunks     the 5 chunks the chat actually packs (fusion with the graph leg -> cross-encoder -> MMR)
  shipped_context    those chunks *plus* the knowledge-graph concepts get_context_node puts in the prompt

Metric: share of questions whose context mentions the prerequisite A (and, as a sanity check, B).

    PYTHONPATH=. python eval/prereq/run_prereq_eval.py      # -> eval/prereq/results.md
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import random
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "graphrag"))
import _env  # noqa: E402

MAX_A_CHUNKS = 15


def mentions(name: str, text: str) -> bool:
    return re.search(r"\b" + re.escape(name.lower()) + r"\b", (text or "").lower()) is not None


def bootstrap_diff(a: list[int], b: list[int], n: int = 2000, seed: int = 7) -> tuple[float, float, float]:
    rng, idx = random.Random(seed), range(len(a))
    diffs = sorted(sum(b[i] - a[i] for i in (rng.choice(idx) for _ in idx)) / len(a) for _ in range(n))
    return sum(y - x for x, y in zip(a, b)) / len(a), diffs[int(0.025 * n)], diffs[int(0.975 * n) - 1]


async def main() -> None:
    _env.setup()
    from langchain_core.messages import HumanMessage

    cg = importlib.import_module("backend.graphs.chat_graph")
    from backend.db.postgres_client import get_postgres_client
    from backend.services.retrieval_service import RetrievalService

    cands = {r["n"]: r for r in map(json.loads, (HERE / "candidates.jsonl").open())}
    keep = {}
    for f in sorted(HERE.glob("labels.*.jsonl")):  # a link counts only if every labeller kept it
        for r in map(json.loads, f.open()):
            keep[r["n"]] = keep.get(r["n"], True) and bool(r["keep"])
    items = [cands[n] for n, k in keep.items() if k and len(cands[n]["a_chunks"]) <= MAX_A_CHUNKS]
    pg, svc, rows = await get_postgres_client(), RetrievalService(), []
    for it in items:
        os.environ["EVAL_RUN"] = it["run"]
        uid = await _env.eval_user_id("grb")
        a, b = it["prerequisite"], it["of"]
        q = f"Explain {b} from the ground up, including the concepts it builds on."
        emb = await cg._embed_query_cached(q)
        vec = await svc._vector_search(q, uid, limit=5, query_embedding=emb, pg_client=pg)
        out = await cg.get_context_node({"user_id": uid, "intent": "explain", "entities": [], "router_source": "model",
                                         "messages": [HumanMessage(content=q)]})
        vec_text = " ".join(c.get("child_content") or "" for c in vec)
        shipped_text = " ".join((c.get("child_content") or c.get("content") or "") for c in out["rag_context"])
        concepts = " | ".join(str(c.get("name")) for c in out["graph_context"].get("concepts") or [])
        rows.append({"n": it["n"], "run": it["run"], "prerequisite": a, "of": b,
                     "vector_top5": int(mentions(a, vec_text)), "shipped_chunks": int(mentions(a, shipped_text)),
                     "shipped_context": int(mentions(a, shipped_text) or mentions(a, concepts)),
                     "b_in_vector": int(mentions(b, vec_text)), "b_in_shipped": int(mentions(b, shipped_text))})
        print(f"{it['n']:3d} {a} -> {b}: vec {rows[-1]['vector_top5']} chunks {rows[-1]['shipped_chunks']} "
              f"context {rows[-1]['shipped_context']}", flush=True)

    n = len(rows)
    share = lambda k: sum(r[k] for r in rows) / n  # noqa: E731
    lines = [f"# Prerequisite-chain benchmark (n={n} human-checked links, specific prerequisites)", "",
             "Question: \"Explain B from the ground up, including the concepts it builds on.\" Does the context "
             "the model receives mention B's prerequisite A?", "",
             "| arm | mentions prerequisite A | mentions B (sanity) |", "|---|---|---|",
             f"| vector_top5 (plain RAG) | {share('vector_top5'):.2f} | {share('b_in_vector'):.2f} |",
             f"| shipped_chunks | {share('shipped_chunks'):.2f} | {share('b_in_shipped'):.2f} |",
             f"| shipped_context (chunks + graph concepts) | {share('shipped_context'):.2f} | — |", "",
             "Paired difference vs vector_top5 (95% bootstrap CI):", ""]
    for arm in ("shipped_chunks", "shipped_context"):
        d, lo, hi = bootstrap_diff([r["vector_top5"] for r in rows], [r[arm] for r in rows])
        lines.append(f"- {arm}: {d:+.2f} [{lo:+.2f}, {hi:+.2f}]")
    (HERE / "results.md").write_text("\n".join(lines) + "\n")
    (HERE / "results.json").write_text(json.dumps(rows, indent=1))
    print("\n".join(lines))


if __name__ == "__main__":
    asyncio.run(main())
