"""Pure-unit tests for backend.services.reranker."""

from __future__ import annotations

import builtins
import sys
import time
import types

import pytest

from backend.services.reranker import (
    CrossEncoderReranker,
    LexicalOverlapReranker,
    Reranker,
    RerankResult,
    mmr_select_chunks,
    order_lost_in_middle,
)


def test_reranker_protocol_conformance() -> None:
    assert isinstance(LexicalOverlapReranker(), Reranker)
    assert isinstance(CrossEncoderReranker(), Reranker)


def test_lexical_overlap_reranker_promotes_exact_acronym_and_phrase_without_mutation() -> None:
    chunks = [
        {
            "id": "c_decoy",
            "parent_chunk_id": "p_decoy",
            "title": "Vector Databases Overview",
            "content": "Approximate nearest neighbor indexes improve query throughput for large corpora.",
            "similarity": 0.91,
        },
        {
            "id": "c_hnsw",
            "parent_chunk_id": "p_hnsw",
            "title": "HNSW Graph Construction",
            "content": "HNSW uses ef_construction and M links per layer for fast hierarchical graph search.",
            "similarity": 0.72,
        },
        {
            "id": "c_partial",
            "parent_chunk_id": "p_partial",
            "title": "Graph Notes",
            "content": "Search speed depends on parameters and memory layout.",
            "similarity": 0.75,
        },
    ]
    snapshot = [dict(c) for c in chunks]

    reranker = LexicalOverlapReranker()
    result = reranker.rerank("HNSW ef_construction", chunks, top_k=2)

    assert isinstance(result, RerankResult)
    assert result.method == "lexical_overlap"
    assert result.used_fallback is False
    assert len(result.chunks) == 2
    assert result.chunks[0]["id"] == "c_hnsw"
    assert "rerank_score" in result.chunks[0]
    assert result.chunks[0]["rerank_score"] > result.chunks[1]["rerank_score"]
    # Caller dicts must remain untouched.
    assert chunks == snapshot
    assert all("rerank_score" not in c for c in chunks)


def test_lexical_overlap_reranker_phrase_bonus_and_edge_cases() -> None:
    chunks = [
        {
            "id": "c1",
            "title": "Note 1",
            "content": "Fusion combines reciprocal lists using rank weights.",
            "_rrf_score": 0.04,
        },
        {
            "id": "c2",
            "title": "Note 2",
            "content": "Reciprocal Rank Fusion (RRF) sums 1 / (k + rank) across retrieval legs.",
            "_rrf_score": 0.03,
        },
    ]
    reranker = LexicalOverlapReranker()
    res = reranker.rerank("reciprocal rank fusion", chunks, top_k=5)
    assert [c["id"] for c in res.chunks] == ["c2", "c1"]

    assert reranker.rerank("anything", [], top_k=5).chunks == []
    assert reranker.rerank("anything", chunks, top_k=0).chunks == []

    # Empty query preserves prior-score ordering cleanly.
    empty_q = reranker.rerank("", chunks, top_k=2)
    assert [c["id"] for c in empty_q.chunks] == ["c1", "c2"]


def test_cross_encoder_lazy_load_and_missing_dependency_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    # Instantiation must never import sentence_transformers.
    reranker = CrossEncoderReranker(timeout_ms=50.0)
    assert reranker._model is None

    # Force ImportError when sentence_transformers is imported inside rerank().
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "sentence_transformers" or name.startswith("sentence_transformers."):
            raise ImportError("sentence_transformers not installed")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)

    chunks = [
        {"id": "c1", "content": "Unrelated topic about cooking.", "similarity": 0.9},
        {"id": "c2", "content": "LoRA adds low-rank adapter matrices to attention projections.", "similarity": 0.6},
    ]
    res = reranker.rerank("LoRA adapter matrices", chunks, top_k=2)
    assert res.used_fallback is True
    assert res.method == "lexical_overlap"
    assert res.chunks[0]["id"] == "c2"


def test_cross_encoder_timeout_and_exception_fallback() -> None:
    chunks = [
        {"id": "c1", "content": "General notes", "similarity": 0.95},
        {"id": "c2", "content": "FSRS stability decay formula", "similarity": 0.50},
    ]

    class SlowModel:
        def predict(self, pairs):
            time.sleep(0.25)
            return [0.9, 0.1]

    slow_reranker = CrossEncoderReranker(timeout_ms=25.0, model=SlowModel())
    t0 = time.perf_counter()
    res_timeout = slow_reranker.rerank("FSRS stability", chunks, top_k=2)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert res_timeout.used_fallback is True
    assert res_timeout.chunks[0]["id"] == "c2"
    # Must return promptly after timeout rather than waiting 250ms for SlowModel.
    assert elapsed_ms < 180.0

    class BrokenModel:
        def predict(self, pairs):
            raise RuntimeError("CUDA OOM")

    err_reranker = CrossEncoderReranker(timeout_ms=100.0, model=BrokenModel())
    res_err = err_reranker.rerank("FSRS stability", chunks, top_k=2)
    assert res_err.used_fallback is True
    assert res_err.chunks[0]["id"] == "c2"


def test_cross_encoder_success_via_lazy_import(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded_names: list[str] = []

    class FakeCrossEncoder:
        def __init__(self, model_name: str) -> None:
            loaded_names.append(model_name)

        def predict(self, pairs):
            # Score second chunk higher regardless of lexical overlap.
            return [0.15, 0.92]

    fake_mod = types.ModuleType("sentence_transformers")
    fake_mod.CrossEncoder = FakeCrossEncoder  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_mod)

    chunks = [
        {"id": "c1", "content": "alpha beta", "similarity": 0.9},
        {"id": "c2", "content": "gamma delta", "similarity": 0.4},
    ]
    reranker = CrossEncoderReranker(model_name="fake/mini-ce", timeout_ms=200.0)
    res = reranker.rerank("alpha", chunks, top_k=2)

    assert loaded_names == ["fake/mini-ce"]
    assert res.used_fallback is False
    assert res.method == "cross_encoder"
    assert [c["id"] for c in res.chunks] == ["c2", "c1"]
    assert res.chunks[0]["rerank_score"] == 0.92


def test_mmr_select_chunks_dedupes_parents_and_enforces_embedding_diversity() -> None:
    q_emb = [0.707107, 0.707107, 0.0]
    chunks = [
        {"id": "c1a", "parent_chunk_id": "p1", "content": "chunk 1a", "embedding": [0.78, 0.6258, 0.0], "rerank_score": 0.95},
        {"id": "c1b", "parent_chunk_id": "p1", "content": "chunk 1b", "embedding": [0.79, 0.6131, 0.0], "rerank_score": 0.80},
        {"id": "c2", "parent_chunk_id": "p2", "content": "chunk 2 near dup", "embedding": [0.80, 0.60, 0.0], "rerank_score": 0.90},
        {"id": "c3", "parent_chunk_id": "p3", "content": "chunk 3 diverse", "embedding": [0.45, 0.8930, 0.0], "rerank_score": 0.70},
    ]

    selected = mmr_select_chunks(q_emb, chunks, k=2, lambda_mult=0.5)
    assert len(selected) == 2
    # c1b shares parent p1 with c1a so it is deduped out; c3 beats near-duplicate c2 under lambda=0.5.
    assert selected[0]["id"] == "c1a"
    assert selected[1]["id"] == "c3"


def test_mmr_select_chunks_jaccard_fallback_when_embeddings_none() -> None:
    chunks = [
        {
            "id": "c1",
            "note_id": "n1",
            "content": "HNSW hierarchical navigable small world graph search algorithm",
            "rerank_score": 0.95,
        },
        {
            "id": "c2",
            "note_id": "n2",
            "content": "HNSW hierarchical navigable small world graph search tuning",
            "rerank_score": 0.90,
        },
        {
            "id": "c3",
            "note_id": "n3",
            "content": "PGVector HNSW ef_search runtime recall versus latency tradeoff",
            "rerank_score": 0.84,
        },
    ]
    selected = mmr_select_chunks(None, chunks, k=2, lambda_mult=0.5)
    assert [c["id"] for c in selected] == ["c1", "c3"]
    assert mmr_select_chunks(None, [], k=3) == []
    assert mmr_select_chunks(None, chunks, k=0) == []


def test_order_lost_in_middle() -> None:
    ranked = [{"id": f"c{i}"} for i in range(6)]
    reordered = order_lost_in_middle(ranked)
    assert [c["id"] for c in reordered] == ["c0", "c2", "c4", "c5", "c3", "c1"]

    odd_ranked = [{"id": f"c{i}"} for i in range(5)]
    assert [c["id"] for c in order_lost_in_middle(odd_ranked)] == ["c0", "c2", "c4", "c3", "c1"]

    assert order_lost_in_middle([]) == []
    assert [c["id"] for c in order_lost_in_middle([{"id": "c0"}])] == ["c0"]
    assert [c["id"] for c in order_lost_in_middle([{"id": "c0"}, {"id": "c1"}])] == ["c0", "c1"]
    assert [c["id"] for c in order_lost_in_middle([{"id": "c0"}, {"id": "c1"}, {"id": "c2"}])] == [
        "c0",
        "c2",
        "c1",
    ]


def test_wordpiece_tokenizer_dynamic_batching_and_truncation(tmp_path) -> None:
    from backend.services.reranker import _WordPieceTokenizer

    vocab_tokens = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "hello", "world", "cafe", "note", "##s", ",", "?"]
    vocab_file = tmp_path / "vocab.txt"
    vocab_file.write_text("\n".join(vocab_tokens) + "\n", encoding="utf-8")

    tok = _WordPieceTokenizer(vocab_file)
    ids, mask, types = tok.encode_pair("Café?", "Hello, notes " + "world " * 20, max_length=12)
    assert len(ids) == 12
    assert ids[0] == tok.cls_id
    assert ids.count(tok.sep_id) == 2
    assert types[0] == 0 and types[-1] == 1
    assert mask == [1] * 12

    b_ids, b_mask, b_types = tok.encode_batch(
        [("hello", "world"), ("hello world", "notes world")],
        max_length=16,
    )
    # Longest sequence in this batch ([CLS] hello world [SEP] note ##s world [SEP] -> 8) sets width.
    assert b_ids.shape == (2, 8)
    assert b_mask[0, -1] == 0 and b_ids[0, -1] == tok.pad_id
    assert b_types.shape == (2, 8)


def test_onnx_cross_encoder_reranker_fallback_and_blend(tmp_path) -> None:
    import numpy as np
    from backend.services.reranker import OnnxCrossEncoderReranker

    chunks = [
        {"id": "c1", "parent_chunk_id": "p1", "title": "Intro", "child_content": "General text", "_rrf_score": 0.05},
        {"id": "c2", "parent_chunk_id": "p1", "title": "Target", "child_content": "HNSW pruning bridges", "_rrf_score": 0.02},
    ]
    snapshot = [dict(c) for c in chunks]

    # Missing model falls back deterministically to LexicalOverlapReranker.
    missing = OnnxCrossEncoderReranker(model_path=tmp_path / "none.onnx", vocab_path=tmp_path / "none.txt")
    fb = missing.rerank("HNSW pruning", chunks, top_k=2)
    assert fb.used_fallback is True
    assert fb.method == "lexical_overlap"
    assert fb.chunks[0]["id"] == "c2"

    class FakeInput:
        def __init__(self, name: str) -> None:
            self.name = name

    class FakeTokenizer:
        def encode_batch(self, pairs, *, max_length: int = 256):
            n = len(pairs)
            return (
                np.ones((n, 4), dtype=np.int64),
                np.ones((n, 4), dtype=np.int64),
                np.zeros((n, 4), dtype=np.int64),
            )

    class FakeSession:
        def get_inputs(self):
            return [FakeInput("input_ids"), FakeInput("attention_mask"), FakeInput("token_type_ids")]

        def run(self, _outputs, inputs):
            assert inputs["input_ids"].shape[0] == 2
            return [np.array([[-1.5], [2.2]], dtype=np.float32)]

    ce = OnnxCrossEncoderReranker(
        rrf_blend_weight=0.2,
        session=FakeSession(),
        tokenizer=FakeTokenizer(),  # type: ignore[arg-type]
    )
    res = ce.rerank("HNSW pruning", chunks, top_k=2)
    assert res.used_fallback is False
    assert res.method == "onnx_cross_encoder"
    assert [c["id"] for c in res.chunks] == ["c2", "c1"]
    assert "ce_logit" in res.chunks[0] and "ce_prob" in res.chunks[0]
    assert chunks == snapshot


def test_mmr_max_per_parent_and_prefer_rerank_score() -> None:
    q_emb = [1.0, 0.0]
    chunks = [
        {"id": "c1a", "parent_chunk_id": "p1", "content": "alpha one", "embedding": [0.4, 0.9165], "rerank_score": 4.2},
        {"id": "c1b", "parent_chunk_id": "p1", "content": "alpha two", "embedding": [0.99, 0.141], "rerank_score": 2.5},
        {"id": "c2", "parent_chunk_id": "p2", "content": "beta decoy", "embedding": [1.0, 0.0], "rerank_score": -3.0},
    ]
    # max_per_parent=2 retains both p1 chunks; prefer_rerank_score=True trusts negative/positive CE logits over decoy cosine.
    selected = mmr_select_chunks(q_emb, chunks, k=3, lambda_mult=0.78, max_per_parent=2, prefer_rerank_score=True)
    assert [c["id"] for c in selected[:2]] == ["c1a", "c1b"]
