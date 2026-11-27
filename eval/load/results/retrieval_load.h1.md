# Retrieval load test (h1 held-out corpus, 48 requests per level)

Real `chat_graph.get_context_node` (seeds, vector/keyword/graph legs, fusion, cross-encoder, MMR, learner
state) on an 8-core M-series Mac, query embeddings pre-warmed. "Lag" = how late a 10 ms event-loop ticker
woke up: CPU work on the loop stalls every other request, including token streams.

## Before: cross-encoder called synchronously on the event loop

| concurrency | throughput (req/s) | p50 ms | p95 ms | max ms | event-loop lag p95 / max ms |
|---|---|---|---|---|---|
| 1 | 5.1 | 186 | 239 | 388 | 124 / 200 |
| 4 | 6.2 | 636 | 1024 | 1045 | 167 / 361 |
| 8 | 6.7 | 1152 | 1502 | 1578 | 203 / 330 |
| 16 | 6.6 | 2416 | 2901 | 3080 | 247 / 1029 |

## After: asyncio.to_thread + a semaphore of cores / RERANKER_THREADS (default 4 threads -> 2 runs)

| concurrency | throughput (req/s) | p50 ms | p95 ms | max ms | event-loop lag p95 / max ms |
|---|---|---|---|---|---|
| 1 | 5.2 | 183 | 270 | 315 | 3 / 8 |
| 4 | 8.6 | 441 | 663 | 713 | 10 / 34 |
| 8 | 8.5 | 891 | 1167 | 1259 | 15 / 38 |
| 16 | 8.8 | 1683 | 1919 | 2159 | 13 / 100 |

## Threads per cross-encoder run (RERANKER_THREADS)

| threads | runs at once | 1 user p50 ms | 16 users req/s | 16 users p95 ms |
|---|---|---|---|---|
| 4 (default) | 2 | 183 | 8.8 | 1919 |
| 2 | 4 | 247 | 9.3 | 2170 |
| 1 | 8 | 398 | 8.1 | 2634 |

Default stays 4: single-user latency is what a personal app feels. Use 2 for a busier server.
The ceiling after the fix is cross-encoder CPU (~165 ms per query); beyond ~9 req/s per 8 cores,
scale out workers or move reranking to a GPU/accelerator.
