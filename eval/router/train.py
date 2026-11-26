"""Train and evaluate the chat intent router with frozen-set anti-leakage hygiene.

Compares three models on an evaluation set (`dev`, `test`, `heldout_v2`, or `human`):
  1. keyword rules        - a hand-written regex baseline, the "do we even need ML" check
  2. TF-IDF + LogReg      - word 1-2 grams + char 2-5 grams; servable with numpy only (ships)
  3. MiniLM + LogReg      - all-MiniLM-L6-v2 sentence embeddings; needs torch at serve time
Reports accuracy, macro-F1 (over all 8 classes and over present gold classes), routing-equivalent
accuracy (only intents that change retrieval behaviour are kept apart), per-class F1, confusion
matrix, bootstrap 95% CIs, selective accuracy/coverage at confidence thresholds, and per-query
latency.

Anti-contamination rules enforced by code:
  - SHA-256 digests of the eval file, train file, and shipped artifact are recorded in every
    `results/<eval_set>.json`.
  - Per-item error examples (`*_errors`) are ONLY written/printed on `dev`. On frozen sets
    (`test`, `heldout_v2`, `human`), per-item errors are suppressed so nobody can tune templates
    against held-out items. Passing `--inspect-frozen-errors` logs an explicit audit marker
    (`"frozen_errors_inspected": true` + UTC timestamp) in the output JSON.
  - `--score-only` evaluates the existing `intent_tfidf_lr.json` artifact + keyword baseline
    using pure `numpy` (no `scikit-learn` required) without retraining or overwriting the model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def _load_module(name: str):
    """Import a runtime module by path, skipping backend/services/__init__ (it pulls in the whole app)."""
    import importlib.util

    path = ROOT / "backend" / "services" / "intent_router" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"intent_router_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


IntentClassifier = _load_module("model").IntentClassifier
ROUTE_GROUP = _load_module("routing").ROUTE_GROUP

HERE = Path(__file__).parent
ARTIFACT = ROOT / "backend" / "services" / "intent_router" / "artifacts" / "intent_tfidf_lr.json"
CLASSES = ["explain", "compare", "find", "summarize", "quiz", "path", "show_images", "general"]
FROZEN_SETS = {"test", "heldout_v2", "human"}
VERSION = "tfidf-lr-v1"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def load(name: str) -> tuple[list[str], list[str], list[str], Path]:
    path = HERE / "data" / name
    rows = [json.loads(line) for line in path.open() if line.strip()]
    return (
        [r["text"] for r in rows],
        [r["intent"] for r in rows],
        [r.get("label_source", "synthetic") for r in rows],
        path,
    )


# --------------------------------------------------------------------------- 1. keyword baseline
RULES = [
    ("show_images", r"\b(diagram|image|images|picture|pictures|photo|figure|figures|visual|visuali[sz]e|screenshot|chart|illustrat|look like|flowchart|slide)\b"),
    ("quiz", r"\b(quiz|test me|test my|flashcard|practice|drill|grill|questions? (on|about|at me)|mcq|exam)\b"),
    ("path", r"\b(prereq|prerequisite|before|roadmap|learning path|study plan|where (do|should) i (start|begin)|next|order|path|curriculum|foundation)\b"),
    ("compare", r"\b(vs\.?|versus|differ|difference|compare|contrast|better|or)\b"),
    ("summarize", r"\b(summar|overview|recap|tl;?dr|big picture|key (points|themes)|main (themes|takeaways)|gist|nutshell)\b"),
    ("find", r"\b(my notes|i (wrote|saved|noted|took)|find|search|where('s| is| did)|which (note|article|source)|pull up)\b"),
    ("explain", r"\b(what is|what's|explain|how does|how do|why|define|understand|intuition|meaning)\b"),
]


def rules_predict(text: str) -> str:
    t = text.lower()
    for intent, pat in RULES:
        if re.search(pat, t):
            return intent
    return "general"


# --------------------------------------------------------------------------- 2. TF-IDF + LR (training)
def make_tfidf(C: float = 10.0):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, make_pipeline

    feats = FeatureUnion([
        ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True, min_df=1)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, min_df=2)),
    ])
    return make_pipeline(feats, LogisticRegression(C=C, max_iter=5000))


def export_tfidf(pipe, threshold: float) -> dict:
    union, lr = pipe.steps[0][1], pipe.steps[1][1]
    blocks = []
    for _, vec in union.transformer_list:
        blocks.append({
            "analyzer": vec.analyzer,
            "ngram_range": list(vec.ngram_range),
            "sublinear_tf": vec.sublinear_tf,
            "vocab": {k: int(v) for k, v in vec.vocabulary_.items()},
            "idf": vec.idf_.round(8).tolist(),
        })
    order = [list(lr.classes_).index(c) for c in CLASSES]
    return {
        "version": VERSION,
        "classes": CLASSES,
        "blocks": blocks,
        "coef": lr.coef_[order].round(8).tolist(),
        "intercept": lr.intercept_[order].round(8).tolist(),
        "threshold": threshold,
    }


# --------------------------------------------------------------------------- pure-numpy metrics
def route(labels: Sequence[str]) -> list[str]:
    return [ROUTE_GROUP[x] for x in labels]


def accuracy_np(y: Sequence[str], p: Sequence[str]) -> float:
    ya, pa = np.asarray(y), np.asarray(p)
    return float((ya == pa).mean()) if len(ya) else 0.0


def per_class_f1_np(y: Sequence[str], p: Sequence[str], labels: Sequence[str]) -> list[float]:
    ya, pa = np.asarray(y), np.asarray(p)
    scores: list[float] = []
    for c in labels:
        tp = int(((ya == c) & (pa == c)).sum())
        fp = int(((ya != c) & (pa == c)).sum())
        fn = int(((ya == c) & (pa != c)).sum())
        denom = 2 * tp + fp + fn
        scores.append((2.0 * tp / denom) if denom > 0 else 0.0)
    return scores


def macro_f1_np(y: Sequence[str], p: Sequence[str], labels: Sequence[str]) -> float:
    vals = per_class_f1_np(y, p, labels)
    return float(np.mean(vals)) if vals else 0.0


def confusion_np(y: Sequence[str], p: Sequence[str], labels: Sequence[str]) -> list[list[int]]:
    idx_map = {c: i for i, c in enumerate(labels)}
    k = len(labels)
    mat = [[0] * k for _ in range(k)]
    for yt, yp in zip(y, p):
        if yt in idx_map and yp in idx_map:
            mat[idx_map[yt]][idx_map[yp]] += 1
    return mat


def bootstrap_ci(y, p, fn, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    y, p = np.asarray(y), np.asarray(p)
    vals = []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        vals.append(fn(y[idx], p[idx]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def report(name, y, pred, conf=None, latency_ms=None) -> dict:
    acc = accuracy_np(y, pred)
    mf1 = macro_f1_np(y, pred, CLASSES)
    gold_classes = [c for c in CLASSES if c in set(y)]
    mf1_present = macro_f1_np(y, pred, gold_classes)
    ry, rp = route(y), route(pred)
    racc = accuracy_np(ry, rp)
    per_cls = per_class_f1_np(y, pred, CLASSES)
    out = {
        "model": name,
        "accuracy": round(acc, 4),
        "accuracy_ci95": [round(v, 4) for v in bootstrap_ci(y, pred, accuracy_np)],
        "macro_f1": round(mf1, 4),
        "macro_f1_ci95": [round(v, 4) for v in bootstrap_ci(
            y, pred, lambda a, b: macro_f1_np(a, b, CLASSES))],
        "macro_f1_present_gold": round(mf1_present, 4),
        "macro_f1_present_gold_ci95": [round(v, 4) for v in bootstrap_ci(
            y, pred, lambda a, b: macro_f1_np(a, b, [c for c in CLASSES if c in set(a)]))],
        "routing_accuracy": round(racc, 4),
        "routing_accuracy_ci95": [round(v, 4) for v in bootstrap_ci(ry, rp, accuracy_np)],
        "per_class_f1": {c: round(v, 3) for c, v in zip(CLASSES, per_cls)},
        "confusion": {"labels": CLASSES, "matrix": confusion_np(y, pred, CLASSES)},
    }
    if conf is not None:
        sel = []
        for t in (0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
            keep = np.asarray(conf) >= t
            cov = float(keep.mean())
            a = float((np.asarray(y)[keep] == np.asarray(pred)[keep]).mean()) if keep.any() else float("nan")
            ra = float((np.asarray(ry)[keep] == np.asarray(rp)[keep]).mean()) if keep.any() else float("nan")
            sel.append({
                "threshold": t,
                "coverage": round(cov, 3),
                "accuracy_on_kept": round(a, 4),
                "routing_accuracy_on_kept": round(ra, 4),
            })
        out["selective"] = sel
    if latency_ms is not None:
        out["latency_ms_p50"] = round(float(np.percentile(latency_ms, 50)), 3)
        out["latency_ms_p95"] = round(float(np.percentile(latency_ms, 95)), 3)
    return out


def errors(texts, y, pred, k=25):
    return [{"text": t, "gold": a, "pred": b} for t, a, b in zip(texts, y, pred) if a != b][:k]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-minilm", action="store_true")
    ap.add_argument("--score-only", action="store_true",
                    help="Evaluate existing artifacts/intent_tfidf_lr.json without retraining or overwriting it")
    ap.add_argument("--threshold", type=float, default=0.6,
                    help="chosen on dev: 84%% coverage at 93%% accuracy")
    ap.add_argument("--eval-set", default="dev", choices=["dev", "test", "heldout_v2", "human"],
                    help="iterate on dev; score frozen sets (test, heldout_v2, human) once per model version")
    ap.add_argument("--inspect-frozen-errors", action="store_true",
                    help="Override frozen-set error suppression (logs audit trail in output JSON)")
    args = ap.parse_args()

    is_frozen = args.eval_set in FROZEN_SETS
    emit_errors = (not is_frozen) or args.inspect_frozen_errors

    Xte, yte, src, eval_path = load(f"{args.eval_set}.jsonl")
    train_path = HERE / "data" / "train.jsonl"

    results: dict = {
        "eval_set": args.eval_set,
        "score_only": bool(args.score_only),
        "is_frozen_eval_set": is_frozen,
        "eval_size": len(Xte),
        "eval_file_sha256": sha256_file(eval_path),
        "test_label_sources": {s: src.count(s) for s in sorted(set(src))},
    }
    if is_frozen and args.inspect_frozen_errors:
        print(
            f"WARNING: --inspect-frozen-errors used on frozen set '{args.eval_set}'. "
            "Logging audit marker in results JSON.",
            file=sys.stderr,
        )
        results["frozen_errors_inspected"] = True
        results["frozen_errors_inspected_at"] = datetime.now(timezone.utc).isoformat()
    elif is_frozen:
        results["frozen_errors_inspected"] = False

    # 1. rules
    t0 = time.perf_counter()
    rp = [rules_predict(x) for x in Xte]
    lat = (time.perf_counter() - t0) * 1000 / len(Xte)
    results["rules"] = report("keyword rules", yte, rp, latency_ms=[lat])

    # 2. TF-IDF + LR
    if args.score_only:
        runtime = IntentClassifier.load(ARTIFACT)
        results["artifact_sha256"] = sha256_file(ARTIFACT)
        results["artifact_version"] = runtime.version
        np_proba, lat = [], []
        for x in Xte:
            t0 = time.perf_counter()
            np_proba.append(runtime.predict_proba(x))
            lat.append((time.perf_counter() - t0) * 1000)
        tp = [runtime.classes[int(np.argmax(p))] for p in np_proba]
        tc = [float(np.max(p)) for p in np_proba]
        results["tfidf_lr"] = report("TF-IDF + LogReg (ships)", yte, tp, tc, lat)
        results["tfidf_lr"]["features"] = int(runtime.coef.shape[1])
        if emit_errors:
            results["tfidf_lr_errors"] = errors(Xte, yte, tp)
    else:
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import StratifiedKFold, cross_val_score

        Xtr, ytr, _, _ = load("train.jsonl")
        results["train_size"] = len(Xtr)
        results["train_file_sha256"] = sha256_file(train_path)
        cv = StratifiedKFold(5, shuffle=True, random_state=0)
        cv_scores = {C: float(cross_val_score(make_tfidf(C), Xtr, ytr, cv=cv, scoring="f1_macro").mean())
                     for C in (1.0, 3.0, 10.0, 30.0)}
        best_C = max(cv_scores, key=cv_scores.get)
        pipe = make_tfidf(best_C).fit(Xtr, ytr)
        spec = export_tfidf(pipe, args.threshold)
        runtime = IntentClassifier(spec)

        sk_proba = pipe.predict_proba(Xte)
        sk_order = [list(pipe.classes_).index(c) for c in CLASSES]
        np_proba, lat = [], []
        for x in Xte:
            t0 = time.perf_counter()
            np_proba.append(runtime.predict_proba(x))
            lat.append((time.perf_counter() - t0) * 1000)
        parity = float(np.abs(np.asarray(np_proba) - sk_proba[:, sk_order]).max())
        assert parity < 1e-6, f"numpy runtime disagrees with sklearn: {parity}"
        tp = [CLASSES[int(np.argmax(p))] for p in np_proba]
        tc = [float(np.max(p)) for p in np_proba]
        results["tfidf_lr"] = report("TF-IDF + LogReg (ships)", yte, tp, tc, lat)
        results["tfidf_lr"].update({"cv_macro_f1_by_C": cv_scores, "C": best_C, "parity_max_abs_diff": parity,
                                    "features": int(runtime.coef.shape[1])})
        if emit_errors:
            results["tfidf_lr_errors"] = errors(Xte, yte, tp)

        ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT.write_text(json.dumps(spec, separators=(",", ":")))
        results["artifact_sha256"] = sha256_file(ARTIFACT)
        fixture = [{"text": x, "probs": [round(float(v), 8) for v in p]} for x, p in zip(Xte[:12], np_proba[:12])]
        (ARTIFACT.parent / "parity_fixture.json").write_text(json.dumps(fixture, indent=1))

        # 3. MiniLM + LR (comparison only, when training)
        if not args.no_minilm:
            from sentence_transformers import SentenceTransformer

            enc = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2", device="cpu")
            Etr = enc.encode(Xtr, normalize_embeddings=True, batch_size=64)
            lat = []
            Ete = []
            for x in Xte:
                t0 = time.perf_counter()
                Ete.append(enc.encode([x], normalize_embeddings=True)[0])
                lat.append((time.perf_counter() - t0) * 1000)
            lr = LogisticRegression(C=10.0, max_iter=5000).fit(Etr, ytr)
            pr = lr.predict_proba(np.asarray(Ete))
            mp = [lr.classes_[int(np.argmax(p))] for p in pr]
            results["minilm_lr"] = report("MiniLM + LogReg", yte, mp, [float(p.max()) for p in pr], lat)
            if emit_errors:
                results["minilm_lr_errors"] = errors(Xte, yte, mp)

    out = HERE / "results" / f"{args.eval_set}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=1) + "\n")
    for key in ("rules", "tfidf_lr", "minilm_lr"):
        if key in results:
            r = results[key]
            print(f"{r['model']:<26} acc {r['accuracy']:.3f} {r['accuracy_ci95']}  macroF1 {r['macro_f1']:.3f} "
                  f"(gold {r['macro_f1_present_gold']:.3f})  routing {r['routing_accuracy']:.3f} {r['routing_accuracy_ci95']}  "
                  f"p50 {r.get('latency_ms_p50', '-')} ms")
    print(f"wrote {out} (eval sha256={results['eval_file_sha256'][:12]}..., frozen_errors_inspected={results.get('frozen_errors_inspected', 'n/a')})")


if __name__ == "__main__":
    main()
