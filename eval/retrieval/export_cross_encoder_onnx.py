"""Export cached cross-encoder/ms-marco-MiniLM-L6-v2 to ONNX and verify parity.

Usage (two-step to keep torch/transformers in .venv-ml and ORT verification in backend .venv):
  1) /Users/naveenus/Projects/TubeFocus-Extension/.venv-ml/bin/python3 eval/retrieval/export_cross_encoder_onnx.py --export
  2) /Users/naveenus/Projects/GraphRecall-backend/.venv/bin/python eval/retrieval/export_cross_encoder_onnx.py --verify
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

SNAPSHOT_DIR = Path(
    "/Users/naveenus/.cache/huggingface/hub/"
    "models--cross-encoder--ms-marco-MiniLM-L6-v2/snapshots/"
    "233902d25c440f23af6f7d6e94d2946bac0bee0a"
)
OUT_DIR = ROOT / "eval" / "retrieval" / "artifacts"
ONNX_PATH = OUT_DIR / "ms-marco-MiniLM-L6-v2.onnx"
INT8_ONNX_PATH = OUT_DIR / "ms-marco-MiniLM-L6-v2.int8.onnx"
VOCAB_PATH = OUT_DIR / "vocab.txt"
PARITY_PATH = OUT_DIR / "parity_reference.json"

TEST_PAIRS = [
    ("How does HNSW graph pruning preserve connectivity?", "High-degree preserving pruning drops redundant non-hub edges while retaining hub bridges for ANN search."),
    ("What is reciprocal rank fusion in hybrid retrieval?", "Reciprocal Rank Fusion (RRF) sums 1 / (k + rank) across vector, keyword, and Neo4j graph legs."),
    ("Café naïve résumé — LoRA & QLoRA 4-bit NormalFloat?", "QLoRA quantizes a frozen 4-bit base model and tunes low-rank adapters with double quantization."),
    ("Why does two-level search improve storage overhead?", "Coarse traversal locates top candidates before dynamic batched recomputation evaluates exact scores."),
]


def export_model() -> None:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SNAPSHOT_DIR / "vocab.txt", VOCAB_PATH)

    tok = AutoTokenizer.from_pretrained(str(SNAPSHOT_DIR), local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(str(SNAPSHOT_DIR), local_files_only=True)
    model.eval()

    enc = tok(
        [q for q, _ in TEST_PAIRS],
        [d for _, d in TEST_PAIRS],
        padding=True,
        truncation="only_second",
        max_length=256,
        return_tensors="pt",
    )

    with torch.no_grad():
        torch_logits = model(**enc).logits.reshape(-1).tolist()

    hf_encoded = []
    for q, d in TEST_PAIRS:
        one = tok(q, d, padding=False, truncation="only_second", max_length=256)
        hf_encoded.append({
            "q": q,
            "d": d,
            "input_ids": one["input_ids"],
            "attention_mask": one["attention_mask"],
            "token_type_ids": one["token_type_ids"],
        })

    dummy_ids = enc["input_ids"]
    dummy_mask = enc["attention_mask"]
    dummy_types = enc["token_type_ids"]

    export_kwargs = dict(
        f=str(ONNX_PATH),
        input_names=["input_ids", "attention_mask", "token_type_ids"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "token_type_ids": {0: "batch", 1: "seq"},
            "logits": {0: "batch"},
        },
        opset_version=17,
        do_constant_folding=True,
    )
    try:
        torch.onnx.export(model, (dummy_ids, dummy_mask, dummy_types), dynamo=False, **export_kwargs)
    except TypeError:
        torch.onnx.export(model, (dummy_ids, dummy_mask, dummy_types), **export_kwargs)

    PARITY_PATH.write_text(json.dumps({"pairs": hf_encoded, "torch_logits": torch_logits}, indent=2))
    size_mb = ONNX_PATH.stat().st_size / (1024 * 1024)
    print(f"Exported ONNX model: {ONNX_PATH} ({size_mb:.2f} MB), vocab copied to {VOCAB_PATH}")


def quantize_model() -> None:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    assert ONNX_PATH.exists(), f"Missing FP32 ONNX model: {ONNX_PATH}"
    quantize_dynamic(
        model_input=str(ONNX_PATH),
        model_output=str(INT8_ONNX_PATH),
        weight_type=QuantType.QUInt8,
    )
    fp32_mb = ONNX_PATH.stat().st_size / (1024 * 1024)
    int8_mb = INT8_ONNX_PATH.stat().st_size / (1024 * 1024)
    print(f"Quantized INT8 ONNX: {INT8_ONNX_PATH} ({int8_mb:.2f} MB vs {fp32_mb:.2f} MB FP32, {fp32_mb/int8_mb:.1f}x smaller)")


def verify_parity(*, model_path: Path = ONNX_PATH) -> None:
    import numpy as np
    import onnxruntime as ort
    from backend.services.reranker import OnnxCrossEncoderReranker, _WordPieceTokenizer

    ref = json.loads(PARITY_PATH.read_text())
    wp = _WordPieceTokenizer(VOCAB_PATH)

    for idx, item in enumerate(ref["pairs"]):
        ids, mask, types = wp.encode_pair(item["q"], item["d"], max_length=256)
        assert ids == item["input_ids"], f"Pair {idx} input_ids mismatch:\n{ids}\nvs\n{item['input_ids']}"
        assert mask == item["attention_mask"], f"Pair {idx} attention_mask mismatch"
        assert types == item["token_type_ids"], f"Pair {idx} token_type_ids mismatch"
    print(f"Tokenizer parity PASSED (exact match on {len(ref['pairs'])} pairs)")

    opts = ort.SessionOptions()
    opts.inter_op_num_threads = 1
    opts.intra_op_num_threads = 4
    sess = ort.InferenceSession(str(model_path), sess_options=opts, providers=["CPUExecutionProvider"])

    pairs = [(p["q"], p["d"]) for p in ref["pairs"]]
    b_ids, b_mask, b_types = wp.encode_batch(pairs, max_length=256)
    ort_logits = np.asarray(
        sess.run(None, {"input_ids": b_ids, "attention_mask": b_mask, "token_type_ids": b_types})[0],
        dtype=np.float64,
    ).reshape(-1)
    max_diff = float(np.max(np.abs(ort_logits - np.asarray(ref["torch_logits"], dtype=np.float64))))
    if model_path == ONNX_PATH:
        assert max_diff < 1e-4, f"ONNX vs PyTorch max diff too large: {max_diff}"
    print(f"[{model_path.name}] Logit max diff vs PyTorch = {max_diff:.2e}")

    # Benchmark dynamic-batched batch=30 CPU latency on realistic child chunks.
    reranker = OnnxCrossEncoderReranker(model_path, VOCAB_PATH)
    fake_chunks = [
        {"id": f"c{i}", "title": f"Note {i}", "child_content": TEST_PAIRS[i % len(TEST_PAIRS)][1] * 2}
        for i in range(30)
    ]
    _ = reranker.rerank(TEST_PAIRS[0][0], fake_chunks, top_k=10)  # warm up session
    latencies = []
    for _ in range(5):
        t0 = time.perf_counter()
        res = reranker.rerank(TEST_PAIRS[0][0], fake_chunks, top_k=10)
        assert not res.used_fallback and res.method == "onnx_cross_encoder"
        latencies.append((time.perf_counter() - t0) * 1000.0)
    print(f"[{model_path.name}] Batch=30 CPU latency: mean={sum(latencies)/len(latencies):.1f} ms (min={min(latencies):.1f}, max={max(latencies):.1f})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--quantize", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.export:
        export_model()
    if args.quantize:
        quantize_model()
    if args.verify:
        verify_parity(model_path=ONNX_PATH)
        if INT8_ONNX_PATH.exists():
            verify_parity(model_path=INT8_ONNX_PATH)
