"""Local ONNX Runtime NLI cross-encoder scorer (no PyTorch, no transformers, no LLM calls).

Model: `cross-encoder/nli-deberta-v3-xsmall` (Apache-2.0, pinned in fetch_nli.py).
Label mapping from `config.json`: `{0: "contradiction", 1: "entailment", 2: "neutral"}`.
Uses `tokenizers` `only_first` truncation at 512 tokens so the premise is trimmed if long and
the claim (hypothesis) is preserved intact.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL_DIR = Path(__file__).resolve().parent / "models" / "nli-deberta-v3-xsmall"


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.sum(exp, axis=-1, keepdims=True)


class LocalNLIModel:
    def __init__(self, model_dir: Path = MODEL_DIR, fp32: bool = False, max_length: int = 512):
        cfg_path = model_dir / "config.json"
        tok_path = model_dir / "tokenizer.json"
        onnx_path = model_dir / ("model.fp32.onnx" if fp32 else "model.int8.onnx")
        if not onnx_path.exists():
            alt = model_dir / "model.fp32.onnx"
            if not fp32 and alt.exists():
                onnx_path = alt
            else:
                raise FileNotFoundError(
                    f"Missing NLI ONNX weights at {onnx_path}. Run `python eval/faithfulness/fetch_nli.py` first."
                )

        cfg = json.loads(cfg_path.read_text())
        self.id2label: dict[int, str] = {int(k): str(v).lower() for k, v in cfg["id2label"].items()}
        pad_id = int(cfg.get("pad_token_id", 0))

        self.tokenizer = Tokenizer.from_file(str(tok_path))
        self.tokenizer.enable_truncation(max_length=max_length, strategy="only_first")
        self.tokenizer.enable_padding(pad_id=pad_id, pad_token="[PAD]")

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(onnx_path), opts, providers=["CPUExecutionProvider"])
        self.input_names = {inp.name for inp in self.session.get_inputs()}
        self.onnx_path = onnx_path

    def score_pairs(self, pairs: list[tuple[str, str]], batch_size: int = 16) -> list[dict]:
        """Score `(premise, hypothesis/claim)` pairs returning class probabilities and argmax label."""
        if not pairs:
            return []
        results: list[dict] = []
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start : start + batch_size]
            encs = self.tokenizer.encode_batch(batch)
            feeds: dict[str, np.ndarray] = {
                "input_ids": np.asarray([e.ids for e in encs], dtype=np.int64),
                "attention_mask": np.asarray([e.attention_mask for e in encs], dtype=np.int64),
            }
            if "token_type_ids" in self.input_names:
                feeds["token_type_ids"] = np.asarray([e.type_ids for e in encs], dtype=np.int64)

            logits = self.session.run(None, feeds)[0]
            probs = _softmax(np.asarray(logits, dtype=np.float64))
            for row in probs:
                by_label = {self.id2label[i]: float(row[i]) for i in range(len(row))}
                top_label = self.id2label[int(np.argmax(row))]
                results.append({
                    "label": top_label,
                    "entailment": by_label["entailment"],
                    "neutral": by_label["neutral"],
                    "contradiction": by_label["contradiction"],
                })
        return results


def self_test(fp32: bool = False) -> None:
    model = LocalNLIModel(fp32=fp32)
    cases = [
        (
            "Smoking tobacco is the single biggest risk factor for lung cancer and contains over 50 carcinogens.",
            "Tobacco smoking is the leading risk factor for lung cancer.",
            "entailment",
        ),
        (
            "An aldosteronoma causes excess aldosterone without Cushing syndrome symptoms.",
            "An aldosteronoma always causes severe Cushing syndrome symptoms.",
            "contradiction",
        ),
        (
            "Basal cell carcinoma commonly develops on sun-exposed skin such as the head and neck.",
            "Basal cell carcinoma is treated with cisplatin chemotherapy in all patients.",
            "neutral",
        ),
    ]
    preds = model.score_pairs([(p, h) for p, h, _ in cases])
    for (p, h, expected), pred in zip(cases, preds):
        print(
            f"expected={expected:<13} got={pred['label']:<13} "
            f"E={pred['entailment']:.3f} N={pred['neutral']:.3f} C={pred['contradiction']:.3f} | {h[:55]}"
        )
        assert pred["label"] == expected, f"Self-test failed: expected {expected}, got {pred}"
    print(f"NLI self-test passed ({model.onnx_path.name})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--fp32", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        self_test(fp32=args.fp32)
