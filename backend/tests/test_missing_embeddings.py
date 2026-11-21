"""A failed embedding call must not look like a clean ingest.

embed_node keeps the chunks (no text is lost) but records how many have no vector; the final
status then says so (status_reason "completed_missing_embeddings", next_action "reembed",
a warning), and reembed_missing_chunks fills them in once the provider works again.
"""

import pytest

pytestmark = pytest.mark.asyncio


def _chunks(n_children: int):
    return [{"parent_content": "p", "parent_index": 0, "child_contents": [f"c{i}" for i in range(n_children)]}]


class FailingEmbedder:
    async def embed_batch(self, texts):
        return []  # what EmbeddingService returns when every call failed


class PartialEmbedder:
    async def embed_batch(self, texts):
        return [[0.1] * 3 if i % 2 == 0 else [] for i in range(len(texts))]


async def _run_embed(monkeypatch, embedder, n=4):
    import importlib

    ig = importlib.import_module("backend.graphs.ingestion_graph")
    monkeypatch.setattr(ig, "embedding_service", embedder)
    # call the undecorated node: the instrumented wrapper also needs live-progress plumbing
    node = ig.embed_node.__wrapped__ if hasattr(ig.embed_node, "__wrapped__") else ig.embed_node
    return ig, await node({"chunks": _chunks(n), "processing_metadata": {"keep": 1}})


async def test_all_embeddings_failing_is_reported(monkeypatch):
    ig, out = await _run_embed(monkeypatch, FailingEmbedder())
    meta = out["processing_metadata"]
    assert meta["embeddings"] == {"total": 4, "embedded": 0, "missing": 4}
    assert meta["keep"] == 1  # earlier metadata survives
    assert out["chunks"][0]["child_embeddings"] == [None] * 4  # text still saved, just without vectors
    outcome = ig.embedding_outcome(meta)
    assert outcome["status_reason"] == "completed_missing_embeddings"
    assert outcome["next_action"] == "reembed"
    assert outcome["embeddings_missing"] == 4 and "4 of 4 chunks" in outcome["warnings"][0]


async def test_partial_failure_counts_only_missing(monkeypatch):
    ig, out = await _run_embed(monkeypatch, PartialEmbedder())
    assert out["processing_metadata"]["embeddings"] == {"total": 4, "embedded": 2, "missing": 2}
    assert ig.embedding_outcome(out["processing_metadata"])["embeddings_missing"] == 2


async def test_clean_ingest_unchanged():
    import importlib

    ig = importlib.import_module("backend.graphs.ingestion_graph")
    assert ig.embedding_outcome({"embeddings": {"total": 3, "embedded": 3, "missing": 0}}) == {
        "status_reason": "completed", "next_action": "none", "warnings": [], "embeddings_missing": 0}
    assert ig.embedding_outcome({})["status_reason"] == "completed"  # older metadata without counts


class FakePg:
    def __init__(self, rows):
        self.rows, self.updates = rows, []

    async def execute_query(self, sql, params):
        return list(self.rows)

    async def execute_update(self, sql, params):
        self.updates.append(params["id"])


async def test_reembed_fills_missing_and_stops_on_dead_provider():
    from backend.services.ingestion.reembed import reembed_missing_chunks

    class Ok:
        async def embed_batch(self, texts):
            return [[0.5, 0.5] for _ in texts]

    pg = FakePg([{"id": f"id{i}", "content": f"t{i}"} for i in range(5)])
    assert await reembed_missing_chunks("u", "n", pg=pg, embedder=Ok(), batch_size=2) == {
        "missing_before": 5, "embedded": 5, "still_missing": 0}
    assert pg.updates == [f"id{i}" for i in range(5)]

    calls = []

    class Dead:
        async def embed_batch(self, texts):
            calls.append(len(texts))
            return []

    pg = FakePg([{"id": f"id{i}", "content": "t"} for i in range(6)])
    assert await reembed_missing_chunks("u", None, pg=pg, embedder=Dead(), batch_size=2) == {
        "missing_before": 6, "embedded": 0, "still_missing": 6}
    assert calls == [2]  # one failed batch, not three
