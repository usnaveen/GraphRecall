"""Train and evaluate the chat intent router.

Compares three models on the hand-written test set (data/test.jsonl):
  1. keyword rules        - a hand-written regex baseline, the "do we even need ML" check
  2. TF-IDF + LogReg      - word 1-2 grams + char 2-5 grams; servable with numpy only (ships)
  3. MiniLM + LogReg      - all-MiniLM-L6-v2 sentence embeddings; needs torch at serve time
Reports accuracy, macro-F1, routing-equivalent accuracy (only intents that change retrieval
behaviour are kept apart), per-class F1, confusion matrix, bootstrap 95% CIs, selective
accuracy/coverage at confidence thresholds, and per-query latency. Writes the TF-IDF model to
backend/services/intent_router/artifacts/ after a parity check against the numpy runtime.

Run from the repo root with an environment that has scikit-learn (and sentence-transformers for
model 3):  python eval/router/train.py [--no-minilm]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import FeatureUnion, make_pipeline

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
VERSION = "tfidf-lr-v1"


def load(name: str) -> tuple[list[str], list[str], list[str]]:
    rows = [json.loads(line) for line in (HERE / "data" / name).open()]
    return [r["text"] for r in rows], [r["intent"] for r in rows], [r.get("label_source", "synthetic") for r in rows]


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


# --------------------------------------------------------------------------- 2. TF-IDF + LR
def make_tfidf(C: float = 10.0):
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


# --------------------------------------------------------------------------- metrics
def route(labels):
    return [ROUTE_GROUP[x] for x in labels]


def bootstrap_ci(y, p, fn, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    y, p = np.asarray(y), np.asarray(p)
    vals = []
    for _ in range(n):
        idx = rng.integers(0, len(y), len(y))
        vals.append(fn(y[idx], p[idx]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def report(name, y, pred, conf=None, latency_ms=None) -> dict:
    acc = accuracy_score(y, pred)
    mf1 = f1_score(y, pred, average="macro", labels=CLASSES)
    racc = accuracy_score(route(y), route(pred))
    out = {
        "model": name,
        "accuracy": round(acc, 4),
        "accuracy_ci95": [round(v, 4) for v in bootstrap_ci(y, pred, accuracy_score)],
        "macro_f1": round(mf1, 4),
        "macro_f1_ci95": [round(v, 4) for v in bootstrap_ci(
            y, pred, lambda a, b: f1_score(a, b, average="macro", labels=CLASSES))],
        "routing_accuracy": round(racc, 4),
        "per_class_f1": {c: round(v, 3) for c, v in zip(CLASSES, f1_score(y, pred, average=None, labels=CLASSES))},
        "confusion": {"labels": CLASSES, "matrix": confusion_matrix(y, pred, labels=CLASSES).tolist()},
    }
    if conf is not None:
        sel = []
        for t in (0.0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8):
            keep = np.asarray(conf) >= t
            cov = float(keep.mean())
            a = float((np.asarray(y)[keep] == np.asarray(pred)[keep]).mean()) if keep.any() else float("nan")
            sel.append({"threshold": t, "coverage": round(cov, 3), "accuracy_on_kept": round(a, 4)})
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
    ap.add_argument("--threshold", type=float, default=0.6,
                    help="chosen on dev: 84%% coverage at 93%% accuracy")
    ap.add_argument("--eval-set", default="dev", choices=["dev", "test"],
                    help="iterate on dev; score test once, at the end")
    args = ap.parse_args()

    Xtr, ytr, _ = load("train.jsonl")
    Xte, yte, src = load(f"{args.eval_set}.jsonl")
    results: dict = {
        "eval_set": args.eval_set, "train_size": len(Xtr), "eval_size": len(Xte),
        "test_label_sources": {s: src.count(s) for s in sorted(set(src))},
    }

    # 1. rules
    t0 = time.perf_counter()
    rp = [rules_predict(x) for x in Xte]
    lat = (time.perf_counter() - t0) * 1000 / len(Xte)
    results["rules"] = report("keyword rules", yte, rp, latency_ms=[lat])

    # 2. TF-IDF + LR: choose C by 5-fold CV on the synthetic train set only
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
    results["tfidf_lr_errors"] = errors(Xte, yte, tp)

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(spec, separators=(",", ":")))
    fixture = [{"text": x, "probs": [round(float(v), 8) for v in p]} for x, p in zip(Xte[:12], np_proba[:12])]
    (ARTIFACT.parent / "parity_fixture.json").write_text(json.dumps(fixture, indent=1))

    # 3. MiniLM + LR (comparison only)
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
        results["minilm_lr_errors"] = errors(Xte, yte, mp)

    out = HERE / "results" / f"{args.eval_set}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=1))
    for key in ("rules", "tfidf_lr", "minilm_lr"):
        if key in results:
            r = results[key]
            print(f"{r['model']:<26} acc {r['accuracy']:.3f} {r['accuracy_ci95']}  macroF1 {r['macro_f1']:.3f}  "
                  f"routing {r['routing_accuracy']:.3f}  p50 {r.get('latency_ms_p50', '-')} ms")
    print(f"wrote {out} and {ARTIFACT} ({ARTIFACT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
