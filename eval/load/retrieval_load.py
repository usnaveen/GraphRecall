"""Load test of the chat's retrieval step under concurrency (no LLM, no embedding API in the loop).

Runs the real chat_graph.get_context_node (seeds, three retrieval legs, fusion, cross-encoder rerank,
MMR, learner state) for an eval corpus at increasing concurrency, with query embeddings pre-warmed so
the numbers measure this server, not the embedding provider. Also measures **event-loop lag**: a
ticker that should wake every 10 ms; any CPU work done on the loop (instead of in a thread) shows up
as lag, and in production that lag stalls every other user's token stream.

    EVAL_RUN=h1 PYTHONPATH=. python eval/load/retrieval_load.py [--levels 1 4 8 16] [--per-level 48]

Writes eval/load/results/retrieval_load.<tag>.md.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import statistics
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "graphrag"))
import _env  # noqa: E402


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))] if xs else 0.0


async def lag_ticker(stop: asyncio.Event, samples: list[float]) -> None:
    while not stop.is_set():
        t = time.perf_counter()
        await asyncio.sleep(0.01)
        samples.append((time.perf_counter() - t) * 1000 - 10)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", type=int, nargs="+", default=[1, 4, 8, 16])
    ap.add_argument("--per-level", type=int, default=48)
    args = ap.parse_args()
    _env.setup()
    from langchain_core.messages import HumanMessage

    cg = importlib.import_module("backend.graphs.chat_graph")
    tag = _env.run_key("grb").split("-", 1)[-1]
    uid = await _env.eval_user_id("grb")
    qs = [json.loads(l)["question"] for l in (HERE.parent / "retrieval" / f"golden.{tag}.jsonl").open()]
    print(f"warming {len(qs)} query embeddings...", flush=True)
    for q in qs:
        await cg._embed_query_cached(q)

    async def one(q: str) -> float:
        t = time.perf_counter()
        await cg.get_context_node({"user_id": uid, "intent": "explain", "entities": [], "router_source": "model",
                                   "messages": [HumanMessage(content=q)]})
        return (time.perf_counter() - t) * 1000

    await one(qs[0])  # load the reranker model once
    lines = [f"# Retrieval load test ({tag}, {args.per_level} requests per level)", "",
             "| concurrency | throughput (req/s) | p50 ms | p95 ms | max ms | event-loop lag p95 / max ms |",
             "|---|---|---|---|---|---|"]
    for level in args.levels:
        sem, lat, lag, stop = asyncio.Semaphore(level), [], [], asyncio.Event()

        async def bounded(q: str) -> None:
            async with sem:
                lat.append(await one(q))

        ticker = asyncio.create_task(lag_ticker(stop, lag))
        t0 = time.perf_counter()
        await asyncio.gather(*(bounded(qs[i % len(qs)]) for i in range(args.per_level)))
        wall = time.perf_counter() - t0
        stop.set()
        await ticker
        row = (f"| {level} | {args.per_level / wall:.1f} | {statistics.median(lat):.0f} | {pct(lat, 95):.0f} | "
               f"{max(lat):.0f} | {pct(lag, 95):.0f} / {max(lag):.0f} |")
        lines.append(row)
        print(row, flush=True)
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    (out / f"retrieval_load.{tag}.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
