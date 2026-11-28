"""Calibration and risk-coverage analysis for the shipped TF-IDF + LogReg intent router.

Evaluates the shipped artifact (`backend/services/intent_router/artifacts/intent_tfidf_lr.json`)
without retraining or modifying weights across `dev`, `test`, and `heldout_v2`:
  - 10-bin Expected Calibration Error (ECE-10), MCE-10, multiclass Brier score, and NLL
  - Full 10-bin reliability table
  - Risk-coverage curve across confidence thresholds + AURC / E-AURC

Frozen-set hygiene:
  - Never prints, stores, or inspects per-item texts or error lists on any split.
  - Records eval_file_sha256, artifact_sha256, and `"frozen_errors_inspected": false` on
    frozen sets (`test`, `heldout_v2`).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Sequence

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load_train_module():
    path = HERE / "train.py"
    spec = importlib.util.spec_from_file_location("router_train_helpers", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_T = _load_train_module()
CLASSES: list[str] = _T.CLASSES
FROZEN_SETS: set[str] = _T.FROZEN_SETS
ARTIFACT: Path = _T.ARTIFACT
IntentClassifier = _T.IntentClassifier
load = _T.load
route = _T.route
sha256_file = _T.sha256_file

THRESHOLDS = [0.0, 0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]


def compute_reliability_bins(
    conf: np.ndarray,
    correct: np.ndarray,
    route_correct: np.ndarray,
    n_bins: int = 10,
) -> tuple[float, float, float, list[dict]]:
    """Compute equal-width ECE, MCE, routing ECE, and the per-bin reliability table."""
    n = len(conf)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    route_ece = 0.0
    mce = 0.0
    bins: list[dict] = []
    for b in range(n_bins):
        lo, hi = float(edges[b]), float(edges[b + 1])
        if b == n_bins - 1:
            mask = (conf >= lo) & (conf <= hi)
        else:
            mask = (conf >= lo) & (conf < hi)
        cnt = int(mask.sum())
        frac = cnt / n if n else 0.0
        if cnt == 0:
            bins.append({
                "bin": b + 1,
                "low": round(lo, 2),
                "high": round(hi, 2),
                "count": 0,
                "fraction": 0.0,
                "avg_confidence": None,
                "accuracy": None,
                "routing_accuracy": None,
                "gap": None,
                "abs_gap": None,
            })
            continue
        avg_conf = float(conf[mask].mean())
        acc = float(correct[mask].mean())
        racc = float(route_correct[mask].mean())
        gap = avg_conf - acc
        abs_gap = abs(gap)
        ece += frac * abs_gap
        route_ece += frac * abs(avg_conf - racc)
        if abs_gap > mce:
            mce = abs_gap
        bins.append({
            "bin": b + 1,
            "low": round(lo, 2),
            "high": round(hi, 2),
            "count": cnt,
            "fraction": round(frac, 4),
            "avg_confidence": round(avg_conf, 4),
            "accuracy": round(acc, 4),
            "routing_accuracy": round(racc, 4),
            "gap": round(gap, 4),
            "abs_gap": round(abs_gap, 4),
        })
    return round(ece, 4), round(mce, 4), round(route_ece, 4), bins


def compute_aurc(conf: np.ndarray, correct: np.ndarray) -> dict[str, float]:
    """Compute discrete AURC, oracle AURC, and excess AURC (E-AURC)."""
    n = len(conf)
    order = np.argsort(-conf, kind="mergesort")
    sorted_corr = correct[order].astype(float)
    cum_errors = np.cumsum(1.0 - sorted_corr)
    ranks = np.arange(1, n + 1, dtype=float)
    aurc = float(np.mean(cum_errors / ranks))

    # Oracle ranks all correct items before all incorrect items.
    oracle_corr = np.sort(correct.astype(float))[::-1]
    oracle_errors = np.cumsum(1.0 - oracle_corr)
    oracle_aurc = float(np.mean(oracle_errors / ranks))
    return {
        "aurc": round(aurc, 4),
        "oracle_aurc": round(oracle_aurc, 4),
        "e_aurc": round(aurc - oracle_aurc, 4),
    }


def compute_risk_coverage(
    conf: np.ndarray,
    correct: np.ndarray,
    route_correct: np.ndarray,
    thresholds: Sequence[float] = THRESHOLDS,
) -> list[dict]:
    """Evaluate selective risk & coverage at each confidence threshold."""
    n = len(conf)
    rows: list[dict] = []
    for t in thresholds:
        keep = conf >= t
        kept_n = int(keep.sum())
        abst_n = n - kept_n
        cov = kept_n / n if n else 0.0
        acc_k = float(correct[keep].mean()) if kept_n else None
        racc_k = float(route_correct[keep].mean()) if kept_n else None
        acc_a = float(correct[~keep].mean()) if abst_n else None
        racc_a = float(route_correct[~keep].mean()) if abst_n else None
        rows.append({
            "threshold": round(float(t), 2),
            "kept_count": kept_n,
            "abstained_count": abst_n,
            "coverage": round(cov, 4),
            "accuracy_on_kept": round(acc_k, 4) if acc_k is not None else None,
            "risk_on_kept": round(1.0 - acc_k, 4) if acc_k is not None else None,
            "routing_accuracy_on_kept": round(racc_k, 4) if racc_k is not None else None,
            "routing_risk_on_kept": round(1.0 - racc_k, 4) if racc_k is not None else None,
            "accuracy_on_abstained": round(acc_a, 4) if acc_a is not None else None,
            "routing_accuracy_on_abstained": round(racc_a, 4) if racc_a is not None else None,
        })
    return rows


def evaluate_split(runtime: IntentClassifier, split: str) -> dict:
    texts, gold, _, eval_path = load(f"{split}.jsonl")
    class_idx = {c: i for i, c in enumerate(runtime.classes)}

    probs = np.asarray([runtime.predict_proba(x) for x in texts], dtype=np.float64)
    pred_idx = np.argmax(probs, axis=1)
    pred = [runtime.classes[int(i)] for i in pred_idx]
    conf = np.max(probs, axis=1)

    y_idx = np.asarray([class_idx[y] for y in gold], dtype=np.int64)
    y_onehot = np.zeros_like(probs)
    y_onehot[np.arange(len(gold)), y_idx] = 1.0

    correct = np.asarray([p == y for p, y in zip(pred, gold)], dtype=bool)
    route_correct = np.asarray([rp == ry for rp, ry in zip(route(pred), route(gold))], dtype=bool)

    brier = float(np.mean(np.sum((probs - y_onehot) ** 2, axis=1)))
    p_true = np.clip(probs[np.arange(len(gold)), y_idx], 1e-12, 1.0)
    nll = float(-np.mean(np.log(p_true)))

    ece, mce, route_ece, bins = compute_reliability_bins(conf, correct, route_correct, n_bins=10)
    aurc_8 = compute_aurc(conf, correct)
    aurc_route = compute_aurc(conf, route_correct)
    rc_curve = compute_risk_coverage(conf, correct, route_correct)

    is_frozen = split in FROZEN_SETS
    out = {
        "eval_set": split,
        "eval_size": len(texts),
        "is_frozen_eval_set": is_frozen,
        "eval_file_sha256": sha256_file(eval_path),
        "accuracy": round(float(correct.mean()), 4),
        "routing_accuracy": round(float(route_correct.mean()), 4),
        "mean_confidence": round(float(conf.mean()), 4),
        "ece_10": ece,
        "mce_10": mce,
        "routing_ece_10": route_ece,
        "brier_score": round(brier, 4),
        "nll": round(nll, 4),
        "aurc_8class": aurc_8,
        "aurc_routing": aurc_route,
        "reliability_bins": bins,
        "risk_coverage": rc_curve,
    }
    if is_frozen:
        out["frozen_errors_inspected"] = False
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--splits", nargs="+", default=["dev", "test", "heldout_v2"],
                    choices=["dev", "test", "heldout_v2", "human"])
    ap.add_argument("--out", default=str(HERE / "results" / "calibration.json"))
    args = ap.parse_args()

    runtime = IntentClassifier.load(ARTIFACT)
    payload = {
        "artifact_version": runtime.version,
        "artifact_sha256": sha256_file(ARTIFACT),
        "shipped_threshold": float(runtime.threshold),
        "bins": 10,
        "splits": {},
    }
    for split in args.splits:
        res = evaluate_split(runtime, split)
        payload["splits"][split] = res
        row_06 = next(r for r in res["risk_coverage"] if abs(r["threshold"] - 0.6) < 1e-6)
        print(
            f"{split:<10} n={res['eval_size']:<4} acc={res['accuracy']:.3f} r_acc={res['routing_accuracy']:.3f} "
            f"conf={res['mean_confidence']:.3f} ECE={res['ece_10']:.4f} Brier={res['brier_score']:.4f} "
            f"NLL={res['nll']:.4f} AURC={res['aurc_8class']['aurc']:.4f} "
            f"@0.6(cov={row_06['coverage']:.3f}, acc={row_06['accuracy_on_kept']}, r_acc={row_06['routing_accuracy_on_kept']})"
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=1) + "\n")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
