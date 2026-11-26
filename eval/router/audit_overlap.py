"""Audit train-vs-dev/test overlap and compute decontaminated router metrics.

Quantifies template-iteration leakage between `data/train.jsonl` and `data/{dev,test}.jsonl`
using two surface/lexical similarity measures:
  1. Max TF-IDF cosine similarity using the exact fitted TF-IDF FeatureUnion blocks
     (word 1-2 grams + char_wb 2-5 grams, sublinear TF, L2-normalized) of the shipped
     classifier (`artifacts/intent_tfidf_lr.json`).
  2. Max character 5-gram Jaccard similarity (`|G5(q) ∩ G5(t)| / |G5(q) ∪ G5(t)|`).

Then evaluates the CURRENT shipped artifact (`backend/services/intent_router/artifacts/intent_tfidf_lr.json`)
and the keyword-rules baseline WITHOUT retraining on:
  - Full `test.jsonl` (n=160)
  - Decontaminated `test.jsonl` below the primary 0.80 overlap ceiling (`max_tfidf_cosine <= 0.80`
    AND `max_char5_jaccard <= 0.80`), plus sensitivity slices at 0.70 and 0.60.

Runs in pure `numpy` (no `scikit-learn` required at audit time) so CI and local `.venv`
can reproduce it directly. Writes `eval/router/results/contamination_audit.json`.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
ARTIFACT = ROOT / "backend" / "services" / "intent_router" / "artifacts" / "intent_tfidf_lr.json"
CLASSES = ["explain", "compare", "find", "summarize", "quiz", "path", "show_images", "general"]


def _load_module(path: Path, mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


IntentClassifier = _load_module(ROOT / "backend" / "services" / "intent_router" / "model.py", "ir_model").IntentClassifier
ROUTE_GROUP = _load_module(ROOT / "backend" / "services" / "intent_router" / "routing.py", "ir_routing").ROUTE_GROUP
train_mod = _load_module(HERE / "train.py", "ir_train")
rules_predict = train_mod.rules_predict
bootstrap_ci = train_mod.bootstrap_ci
accuracy_np = train_mod.accuracy_np
macro_f1_np = train_mod.macro_f1_np


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def norm_text(text: str) -> str:
    return " ".join(text.lower().strip().split())


def char_5grams(text: str) -> frozenset[str]:
    s = f" {norm_text(text)} "
    if len(s) <= 5:
        return frozenset({s})
    return frozenset(s[i : i + 5] for i in range(len(s) - 4))


def embed_tfidf_unit(clf: IntentClassifier, texts: list[str]) -> np.ndarray:
    """Transform texts through the exact fitted TF-IDF FeatureUnion and L2-normalize each row."""
    mat = np.vstack([clf.features(t) for t in texts]).astype(np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms = np.where(norms > 1e-12, norms, 1.0)
    return mat / norms


def compute_overlap_records(
    clf: IntentClassifier,
    train_texts: list[str],
    tr_mat: np.ndarray,
    train_5grams: list[frozenset[str]],
    split_rows: list[dict],
) -> list[dict]:
    query_texts = [r["text"] for r in split_rows]
    qu_mat = embed_tfidf_unit(clf, query_texts)
    cos_mat = qu_mat @ tr_mat.T  # (n_query, n_train)

    records: list[dict] = []
    for idx, row in enumerate(split_rows):
        cos_row = cos_mat[idx]
        best_cos_i = int(np.argmax(cos_row))
        max_cos = float(cos_row[best_cos_i])

        q_grams = char_5grams(row["text"])
        best_jac = -1.0
        best_jac_i = 0
        for t_idx, t_grams in enumerate(train_5grams):
            inter = len(q_grams & t_grams)
            jac = 0.0 if inter == 0 else inter / len(q_grams | t_grams)
            if jac > best_jac:
                best_jac = jac
                best_jac_i = t_idx

        records.append({
            "index": idx,
            "text": row["text"],
            "intent": row["intent"],
            "max_tfidf_cosine": round(max_cos, 4),
            "nearest_train_tfidf": train_texts[best_cos_i],
            "max_char5_jaccard": round(float(best_jac), 4),
            "nearest_train_jaccard": train_texts[best_jac_i],
            "max_either": round(max(max_cos, float(best_jac)), 4),
        })
    return records


def summarize_distribution(values: list[float]) -> dict:
    arr = np.asarray(values, dtype=np.float64)
    return {
        "n": int(len(arr)),
        "min": round(float(arr.min()), 4),
        "p25": round(float(np.percentile(arr, 25)), 4),
        "median": round(float(np.percentile(arr, 50)), 4),
        "p75": round(float(np.percentile(arr, 75)), 4),
        "p90": round(float(np.percentile(arr, 90)), 4),
        "p95": round(float(np.percentile(arr, 95)), 4),
        "max": round(float(arr.max()), 4),
        "count_gt_0.80": int((arr > 0.80).sum()),
        "count_gt_0.70": int((arr > 0.70).sum()),
        "count_gt_0.60": int((arr > 0.60).sum()),
    }


def score_subset(clf: IntentClassifier, rows: list[dict]) -> dict:
    texts = [r["text"] for r in rows]
    gold = [r["intent"] for r in rows]
    preds = []
    confs = []
    for t in texts:
        p = clf.predict(t)
        preds.append(p.intent)
        confs.append(p.confidence)
    rule_preds = [rules_predict(t) for t in texts]

    def _metrics(y_true: list[str], y_pred: list[str]) -> dict:
        acc = accuracy_np(y_true, y_pred)
        acc_ci = bootstrap_ci(y_true, y_pred, accuracy_np)
        present_labels = [c for c in CLASSES if c in set(y_true) | set(y_pred)]
        mf1 = macro_f1_np(y_true, y_pred, present_labels)
        mf1_ci = bootstrap_ci(
            y_true,
            y_pred,
            lambda a, b: macro_f1_np(list(a), list(b), [c for c in CLASSES if c in set(a) | set(b)]),
        )
        r_true = [ROUTE_GROUP[x] for x in y_true]
        r_pred = [ROUTE_GROUP[x] for x in y_pred]
        r_acc = accuracy_np(r_true, r_pred)
        r_ci = bootstrap_ci(r_true, r_pred, accuracy_np)
        return {
            "n": len(y_true),
            "accuracy": round(acc, 4),
            "accuracy_ci95": [round(acc_ci[0], 4), round(acc_ci[1], 4)],
            "macro_f1": round(mf1, 4),
            "macro_f1_ci95": [round(mf1_ci[0], 4), round(mf1_ci[1], 4)],
            "routing_accuracy": round(r_acc, 4),
            "routing_accuracy_ci95": [round(r_ci[0], 4), round(r_ci[1], 4)],
        }

    keep_06 = np.asarray(confs) >= 0.6
    selective_06 = {
        "threshold": 0.6,
        "coverage": round(float(keep_06.mean()), 4),
        "accuracy_on_kept": round(
            float((np.asarray(gold)[keep_06] == np.asarray(preds)[keep_06]).mean()), 4
        )
        if keep_06.any()
        else None,
    }

    return {
        "n": len(rows),
        "tfidf_lr_shipped": {**_metrics(gold, preds), "selective_at_0.6": selective_06},
        "keyword_rules": _metrics(gold, rule_preds),
    }


def main() -> None:
    train_path = HERE / "data" / "train.jsonl"
    dev_path = HERE / "data" / "dev.jsonl"
    test_path = HERE / "data" / "test.jsonl"

    train_rows = load_jsonl(train_path)
    dev_rows = load_jsonl(dev_path)
    test_rows = load_jsonl(test_path)
    train_texts = [r["text"] for r in train_rows]

    clf = IntentClassifier.load(ARTIFACT)
    tr_mat = embed_tfidf_unit(clf, train_texts)
    train_5grams = [char_5grams(t) for t in train_texts]

    dev_overlap = compute_overlap_records(clf, train_texts, tr_mat, train_5grams, dev_rows)
    test_overlap = compute_overlap_records(clf, train_texts, tr_mat, train_5grams, test_rows)

    slices: dict[str, dict] = {
        "full_test": score_subset(clf, test_rows),
    }
    for ceiling in (0.80, 0.70, 0.60):
        clean_indices = [
            r["index"]
            for r in test_overlap
            if r["max_tfidf_cosine"] <= ceiling and r["max_char5_jaccard"] <= ceiling
        ]
        clean_rows = [test_rows[i] for i in clean_indices]
        slices[f"decontaminated_le_{ceiling:.2f}"] = {
            "ceiling": ceiling,
            "removed_count": len(test_rows) - len(clean_rows),
            **score_subset(clf, clean_rows),
        }

    audit = {
        "hashes_sha256": {
            "train.jsonl": sha256_file(train_path),
            "dev.jsonl": sha256_file(dev_path),
            "test.jsonl": sha256_file(test_path),
            "intent_tfidf_lr.json": sha256_file(ARTIFACT),
        },
        "sizes": {
            "train": len(train_rows),
            "dev": len(dev_rows),
            "test": len(test_rows),
        },
        "dev_overlap": {
            "tfidf_cosine": summarize_distribution([r["max_tfidf_cosine"] for r in dev_overlap]),
            "char5_jaccard": summarize_distribution([r["max_char5_jaccard"] for r in dev_overlap]),
            "either_gt_0.80": sum(1 for r in dev_overlap if r["max_either"] > 0.80),
            "either_gt_0.70": sum(1 for r in dev_overlap if r["max_either"] > 0.70),
            "top_10_nearest_in_dev": sorted(dev_overlap, key=lambda r: -r["max_either"])[:10],
        },
        "test_overlap": {
            "tfidf_cosine": summarize_distribution([r["max_tfidf_cosine"] for r in test_overlap]),
            "char5_jaccard": summarize_distribution([r["max_char5_jaccard"] for r in test_overlap]),
            "either_gt_0.80": sum(1 for r in test_overlap if r["max_either"] > 0.80),
            "either_gt_0.70": sum(1 for r in test_overlap if r["max_either"] > 0.70),
            # Only items exceeding 0.80 are surfaced to document template leakage without
            # exposing uncontaminated test items.
            "contaminated_gt_0.80": [r for r in test_overlap if r["max_either"] > 0.80],
        },
        "test_evaluation_slices": slices,
    }

    out_path = HERE / "results" / "contamination_audit.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(audit, indent=2) + "\n")

    print("=== OVERLAP SUMMARY ===")
    for split_name, sec in [("dev (n=120)", audit["dev_overlap"]), ("test (n=160)", audit["test_overlap"])]:
        tc = sec["tfidf_cosine"]
        cj = sec["char5_jaccard"]
        print(
            f"{split_name:<14} TF-IDF cos: med={tc['median']:.3f} p90={tc['p90']:.3f} max={tc['max']:.3f} (>0.8: {tc['count_gt_0.80']}) | "
            f"char5 Jaccard: med={cj['median']:.3f} p90={cj['p90']:.3f} max={cj['max']:.3f} (>0.8: {cj['count_gt_0.80']}) | "
            f"either>0.8: {sec['either_gt_0.80']}"
        )
    print("\n=== CURRENT ARTIFACT ON TEST SLICES (NO RETRAIN) ===")
    for k, v in slices.items():
        m = v["tfidf_lr_shipped"]
        kr = v["keyword_rules"]
        print(
            f"{k:<26} n={v['n']:<3d} | TF-IDF+LR acc={m['accuracy']:.4f} {m['accuracy_ci95']} "
            f"macroF1={m['macro_f1']:.4f} routeAcc={m['routing_accuracy']:.4f} | "
            f"Rules acc={kr['accuracy']:.4f} routeAcc={kr['routing_accuracy']:.4f}"
        )
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
