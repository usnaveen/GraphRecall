"""Measure GraphRecall's latency end to end.

Run it inside the API container, so it needs nothing extra installed:

    docker compose exec api python -m backend.scripts.benchmark_latency --runs 3
    docker compose exec api python -m backend.scripts.benchmark_latency --runs 3 --ingest

Client side, it timestamps every Server-Sent Event from /api/chat/stream the way the app
experiences them: first byte, each graph step, first answer token, done.

Server side, it reads GET /api/debug/latency — rolling percentiles the API records for auth,
chat graph nodes, retrieval, ingestion nodes and every LLM call (with token counts).

Free-tier Gemini keys allow only a few requests per minute, so runs are spaced out (--pause).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import httpx

QUESTIONS = [
    "How does GraphRAG differ from plain RAG in my notes?",
    "What should I review about transformers?",
    "Explain spaced repetition using what I've saved.",
    "How are self-attention and multi-head attention related?",
]

SAMPLE_NOTE = (
    "Backpressure lets a slow consumer tell a fast producer to slow down. Message queues "
    "buffer work between services so spikes don't overload them. Idempotent handlers can "
    "safely process the same message twice, which makes retries safe."
)


def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


async def time_chat(client: httpx.AsyncClient, base: str, headers: dict, question: str) -> dict:
    marks: dict[str, float] = {}
    start = time.perf_counter()
    body = {"message": question, "user_id": "benchmark"}
    async with client.stream("POST", f"{base}/api/chat/stream", headers=headers, json=body, timeout=240) as response:
        marks["headers received"] = _ms(start)
        if response.status_code != 200:
            detail = (await response.aread()).decode(errors="replace")[:200]
            raise RuntimeError(f"chat stream returned {response.status_code}: {detail}")
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            elapsed = _ms(start)
            marks.setdefault("first event", elapsed)
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            content = event.get("content") or ""
            if kind == "status" and content.startswith("Step: "):
                marks.setdefault(f"step started: {content[6:].rstrip('.')}", elapsed)
            elif kind == "chunk":
                marks.setdefault("first answer token", elapsed)
            elif kind == "error":
                raise RuntimeError(f"chat stream error event: {content[:200]}")
            elif kind == "done":
                marks["done"] = elapsed
                break
    marks.setdefault("done", _ms(start))
    return marks


async def time_ingest(client: httpx.AsyncClient, base: str, headers: dict) -> dict:
    start = time.perf_counter()
    response = await client.post(
        f"{base}/api/review/ingest",
        headers=headers,
        json={"content": SAMPLE_NOTE, "skip_review": False},
        timeout=300,
    )
    total = _ms(start)
    response.raise_for_status()
    data = response.json()
    session_id = data.get("session_id")
    if session_id:
        # Keep the benchmark from leaving review sessions behind.
        await client.post(f"{base}/api/review/sessions/{session_id}/cancel", headers=headers, timeout=30)
    return {"total": total, "concepts": data.get("concepts_count", 0)}


def _print_table(title: str, header: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(str(cell)) for cell in column) for column in zip(header, *rows)] if rows else [len(h) for h in header]
    print(f"\n{title}")
    print("  " + "  ".join(str(cell).ljust(width) for cell, width in zip(header, widths)))
    print("  " + "  ".join("-" * width for width in widths))
    for row in rows:
        print("  " + "  ".join(str(cell).ljust(width) for cell, width in zip(row, widths)))


def _fmt(ms: float) -> str:
    return f"{ms:,.0f} ms"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--token", default="test-token", help="Bearer token (DEBUG backends accept test-token)")
    parser.add_argument("--runs", type=int, default=3, help="chat questions to time")
    parser.add_argument("--pause", type=float, default=8.0, help="seconds between runs (free-tier rate limits)")
    parser.add_argument("--ingest", action="store_true", help="also time one review-mode import")
    parser.add_argument("--keep-stats", action="store_true", help="don't reset server stats before running")
    args = parser.parse_args()

    headers = {"Authorization": f"Bearer {args.token}"}
    async with httpx.AsyncClient() as client:
        if not args.keep_stats:
            await client.delete(f"{args.base}/api/debug/latency", timeout=10)

        runs: list[dict] = []
        for index in range(args.runs):
            question = QUESTIONS[index % len(QUESTIONS)]
            try:
                marks = await time_chat(client, args.base, headers, question)
                runs.append(marks)
                print(f"run {index + 1}: first token {_fmt(marks.get('first answer token', 0))}, done {_fmt(marks['done'])}  ({question})")
            except Exception as error:  # keep going so one 429 doesn't lose the whole benchmark
                print(f"run {index + 1}: failed — {error}")
            if index < args.runs - 1:
                await asyncio.sleep(args.pause)

        if runs:
            order = list(dict.fromkeys(name for marks in runs for name in marks))
            rows = []
            for name in order:
                values = [marks[name] for marks in runs if name in marks]
                rows.append([name, _fmt(statistics.median(values)), _fmt(max(values)), str(len(values))])
            _print_table("Chat, as the app sees it (time since request sent)", ["event", "median", "max", "runs"], rows)

        if args.ingest:
            await asyncio.sleep(args.pause)
            try:
                result = await time_ingest(client, args.base, headers)
                print(f"\nReview-mode import: {_fmt(result['total'])} for {result['concepts']} concepts")
            except Exception as error:
                print(f"\nReview-mode import failed — {error}")

        stats = (await client.get(f"{args.base}/api/debug/latency", timeout=10)).json()
        rows = [
            [name, str(values["count"]), _fmt(values["p50_ms"]), _fmt(values["p95_ms"]), _fmt(values["max_ms"])]
            for name, values in stats["stages"].items()
        ]
        _print_table("Server stages (rolling window)", ["stage", "count", "p50", "p95", "max"], rows)
        llm_rows = [
            [model, str(t["calls"]), str(t["errors"]), f"{t['input_tokens']:,}", f"{t['output_tokens']:,}"]
            for model, t in stats["llm"].items()
        ]
        if llm_rows:
            _print_table("LLM usage", ["model", "calls", "errors", "input tokens", "output tokens"], llm_rows)


if __name__ == "__main__":
    asyncio.run(main())
