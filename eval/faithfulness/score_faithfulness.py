"""Score GraphRecall chat answers for claim-level faithfulness using a local NLI cross-encoder.

Replaces same-family Gemini judging on groundedness with an independent Apache-2.0
cross-encoder (`cross-encoder/nli-deberta-v3-xsmall`, INT8 ONNX, no PyTorch or LLM API calls).

Two-step workflow:
  1. Export a blind human calibration sample BEFORE running NLI on the slice:
       python eval/faithfulness/score_faithfulness.py --export-calibration-blind
  2. Hand-label those ~31 claims in `eval/faithfulness/calibration_labels.jsonl`, then score all
     arms and evaluate NLI vs blind human agreement (exact %, binary %, Cohen's kappa, 3x3 matrix):
       python eval/faithfulness/score_faithfulness.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from claims import candidate_premises_for_claim, split_claims, split_premise_sentences
from nli import LocalNLIModel

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_RESULTS = ROOT / "eval" / "graphrag" / "results" / "questions_slice.r3.json"
DEFAULT_CALIBRATION = HERE / "calibration_labels.jsonl"
ARMS = ("closed_book", "vector_only", "graph_only", "global_only", "shipped")
LABELS = ("entailed", "neutral", "contradicted")


def resolve_corpus_path(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.exists():
            raise FileNotFoundError(f"Corpus file not found: {p}")
        return p
    candidates = [
        ROOT / "eval" / "graphrag" / "data" / "grb" / "corpus.jsonl",
        ROOT.parent / "GraphRecall-backend" / "eval" / "graphrag" / "data" / "grb" / "corpus.jsonl",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Could not locate grb/corpus.jsonl automatically; pass --corpus /path/to/corpus.jsonl"
    )


def load_corpus(path: Path) -> dict[str, str]:
    by_title: dict[str, str] = {}
    for line in path.open():
        if not line.strip():
            continue
        doc = json.loads(line)
        title = str(doc.get("title") or "").strip()
        text = str(doc.get("text") or doc.get("content") or "").strip()
        if title and text:
            by_title[title] = text
    return by_title


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sample_calibration_items(
    rows: list[dict],
    corpus: dict[str, str],
    target_n: int = 33,
    seed: int = 42,
) -> list[dict]:
    """Deterministically sample ~33 unique `(question_id, claim)` pairs without leaking arm names."""
    rng = random.Random(seed)
    grounded_pool: list[dict] = []
    closed_pool: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    for row in rows:
        qid = row["id"]
        note_titles = row["retrieval"].get("note_titles", [])
        notes_text = [f"{t}: {corpus[t]}" for t in note_titles if t in corpus]
        for arm in ("shipped", "graph_only", "vector_only", "global_only"):
            ans = (row["arms"][arm].get("answer") or "").strip()
            for claim in split_claims(ans):
                key = (qid, claim)
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    grounded_pool.append({
                        "question_id": qid,
                        "question": row["question"],
                        "claim": claim,
                        "note_titles": note_titles,
                        "notes_text": notes_text,
                    })
        cb_ans = (row["arms"]["closed_book"].get("answer") or "").strip()
        for claim in split_claims(cb_ans):
            key = (qid, claim)
            if key not in seen_pairs:
                seen_pairs.add(key)
                closed_pool.append({
                    "question_id": qid,
                    "question": row["question"],
                    "claim": claim,
                    "note_titles": note_titles,
                    "notes_text": notes_text,
                })

    selected: list[dict] = []
    by_q_grounded: dict[str, list[dict]] = {}
    for item in grounded_pool:
        by_q_grounded.setdefault(item["question_id"], []).append(item)
    by_q_closed: dict[str, list[dict]] = {}
    for item in closed_pool:
        by_q_closed.setdefault(item["question_id"], []).append(item)

    for row in rows:
        qid = row["id"]
        g_items = by_q_grounded.get(qid, [])
        if g_items:
            selected.extend(rng.sample(g_items, min(2, len(g_items))))
        c_items = by_q_closed.get(qid, [])
        if c_items:
            selected.append(rng.choice(c_items))

    selected = selected[:target_n]
    rng.shuffle(selected)
    out = []
    for idx, item in enumerate(selected, 1):
        out.append({
            "calib_id": idx,
            "question_id": item["question_id"],
            "question": item["question"],
            "claim": item["claim"],
            "note_titles": item["note_titles"],
            "notes_text": item["notes_text"],
        })
    return out


def aggregate_claim_verdict(
    window_scores: list[tuple[int, dict]],
    entail_thresh: float = 0.5,
    contra_thresh: float = 0.7,
    min_contra_overlap: int = 2,
) -> dict:
    """SummaC-ZS sentence-pair max aggregation with topic-overlap gating for contradictions."""
    if not window_scores:
        return {
            "verdict": "neutral",
            "max_entailment": 0.0,
            "max_contradiction": 0.0,
            "max_neutral": 1.0,
            "best_window_idx": -1,
        }
    best_ent_idx = max(range(len(window_scores)), key=lambda i: window_scores[i][1]["entailment"])
    rel_con_indices = [
        i
        for i, (ov, sc) in enumerate(window_scores)
        if ov >= min_contra_overlap and sc["label"] == "contradiction"
    ]
    max_ent = window_scores[best_ent_idx][1]["entailment"]
    max_con = max((window_scores[i][1]["contradiction"] for i in rel_con_indices), default=0.0)
    max_neu = max(sc["neutral"] for _, sc in window_scores)
    top_ent_score = window_scores[best_ent_idx][1]

    if top_ent_score["label"] == "entailment" and max_ent >= entail_thresh:
        verdict = "entailed"
        best_idx = best_ent_idx
    elif max_con >= contra_thresh:
        verdict = "contradicted"
        best_idx = max(rel_con_indices, key=lambda i: window_scores[i][1]["contradiction"])
    else:
        verdict = "neutral"
        best_idx = best_ent_idx
    return {
        "verdict": verdict,
        "max_entailment": round(float(max_ent), 4),
        "max_contradiction": round(float(max_con), 4),
        "max_neutral": round(float(max_neu), 4),
        "best_window_idx": best_idx,
    }


def cohens_kappa(y_true: list[str], y_pred: list[str], labels: tuple[str, ...]) -> dict:
    n = len(y_true)
    if n == 0:
        return {"n": 0, "agreement": 0.0, "kappa": 0.0, "labels": list(labels), "matrix": []}
    idx = {l: i for i, l in enumerate(labels)}
    mat = [[0] * len(labels) for _ in range(len(labels))]
    for yt, yp in zip(y_true, y_pred):
        if yt in idx and yp in idx:
            mat[idx[yt]][idx[yp]] += 1
    agree = sum(mat[i][i] for i in range(len(labels))) / n
    c_true = Counter(y_true)
    c_pred = Counter(y_pred)
    pe = sum((c_true[l] / n) * (c_pred[l] / n) for l in labels)
    kappa = (agree - pe) / (1.0 - pe) if (1.0 - pe) > 1e-12 else 0.0
    return {
        "n": n,
        "agreement": round(agree, 4),
        "expected_chance_agreement": round(pe, 4),
        "kappa": round(kappa, 4),
        "labels": list(labels),
        "matrix": mat,
    }


def score_all(
    results_path: Path,
    corpus_path: Path,
    calibration_path: Path,
    out_dir: Path,
    fp32: bool = False,
) -> dict:
    data = json.loads(results_path.read_text())
    rows = data["rows"]
    corpus = load_corpus(corpus_path)
    model = LocalNLIModel(fp32=fp32)

    # Deduplicate NLI inference across identical (question_id, claim) strings.
    question_sentences: dict[str, list[str]] = {}
    question_evidence_sents: dict[str, list[str]] = {}
    unique_pairs: dict[tuple[str, str], dict] = {}
    pair_list: list[tuple[str, str]] = []
    pair_keys: list[tuple[str, str]] = []
    pair_overlaps: list[int] = []

    for row in rows:
        qid = row["id"]
        note_titles = row["retrieval"].get("note_titles", [])
        note_texts = [corpus[t] for t in note_titles if t in corpus]
        sents = split_premise_sentences(note_texts)
        question_sentences[qid] = sents
        ev = (row.get("evidence") or "").strip()
        question_evidence_sents[qid] = split_premise_sentences([ev]) if ev else []

        for arm in ARMS:
            ans = (row["arms"][arm].get("answer") or "").strip()
            for claim in split_claims(ans):
                key = (qid, claim)
                if key not in unique_pairs:
                    cands = candidate_premises_for_claim(sents, claim, top_k=30)
                    unique_pairs[key] = {"n_candidates": len(cands)}
                    for premise, ov in cands:
                        pair_list.append((premise, claim))
                        pair_keys.append(key)
                        pair_overlaps.append(ov)

    raw_scores = model.score_pairs(pair_list, batch_size=32)
    grouped: dict[tuple[str, str], list[tuple[int, dict]]] = {k: [] for k in unique_pairs}
    for k, ov, s in zip(pair_keys, pair_overlaps, raw_scores):
        grouped[k].append((ov, s))

    claim_verdicts: dict[tuple[str, str], dict] = {
        k: aggregate_claim_verdict(v) for k, v in grouped.items()
    }
    claim_verdicts_strict: dict[tuple[str, str], dict] = {
        k: aggregate_claim_verdict(v, entail_thresh=0.7, contra_thresh=0.7) for k, v in grouped.items()
    }

    # Secondary check against gold benchmark evidence (only 7/11 questions have non-empty evidence).
    ev_pairs: list[tuple[str, str]] = []
    ev_keys: list[tuple[str, str]] = []
    ev_overlaps: list[int] = []
    for qid, claim in unique_pairs:
        ev_sents = question_evidence_sents[qid]
        if not ev_sents:
            continue
        for premise, ov in candidate_premises_for_claim(ev_sents, claim, top_k=30):
            ev_pairs.append((premise, claim))
            ev_keys.append((qid, claim))
            ev_overlaps.append(ov)
    ev_scores = model.score_pairs(ev_pairs, batch_size=32)
    ev_grouped: dict[tuple[str, str], list[tuple[int, dict]]] = {}
    for k, ov, s in zip(ev_keys, ev_overlaps, ev_scores):
        ev_grouped.setdefault(k, []).append((ov, s))
    ev_verdicts = {k: aggregate_claim_verdict(v) for k, v in ev_grouped.items()}

    # Audit cross-arm answer identity in r3.
    identical_non_empty_rag_arms = 0
    for row in rows:
        rag_ans = [
            row["arms"][a].get("answer")
            for a in ("vector_only", "graph_only", "global_only", "shipped")
            if row["arms"][a].get("answer")
        ]
        if rag_ans and len(set(rag_ans)) == 1:
            identical_non_empty_rag_arms += 1

    arm_summary: dict[str, dict] = {}
    per_question: list[dict] = []

    for arm in ARMS:
        counts = Counter()
        counts_strict = Counter()
        ev_counts = Counter()
        ans_with_claims = 0
        empty_answers = 0
        entailed_rates: list[float] = []
        contradicted_rates: list[float] = []

        for row in rows:
            qid = row["id"]
            ans = (row["arms"][arm].get("answer") or "").strip()
            if not ans:
                empty_answers += 1
                continue
            claims = split_claims(ans)
            if not claims:
                continue
            ans_with_claims += 1
            q_counts = Counter(claim_verdicts[(qid, c)]["verdict"] for c in claims)
            entailed_rates.append(q_counts["entailed"] / len(claims))
            contradicted_rates.append(q_counts["contradicted"] / len(claims))
            for c in claims:
                counts[claim_verdicts[(qid, c)]["verdict"]] += 1
                counts_strict[claim_verdicts_strict[(qid, c)]["verdict"]] += 1
                if (qid, c) in ev_verdicts:
                    ev_counts[ev_verdicts[(qid, c)]["verdict"]] += 1

        total = sum(counts.values())
        ev_total = sum(ev_counts.values())
        arm_summary[arm] = {
            "non_empty_answers": ans_with_claims,
            "empty_answers": empty_answers,
            "total_claims": total,
            "entailed_claims": counts["entailed"],
            "neutral_claims": counts["neutral"],
            "contradicted_claims": counts["contradicted"],
            "pct_entailed": round(100.0 * counts["entailed"] / total, 1) if total else 0.0,
            "pct_neutral": round(100.0 * counts["neutral"] / total, 1) if total else 0.0,
            "pct_contradicted": round(100.0 * counts["contradicted"] / total, 1) if total else 0.0,
            "mean_answer_entailed_rate": round(100.0 * sum(entailed_rates) / len(entailed_rates), 1) if entailed_rates else 0.0,
            "mean_answer_contradicted_rate": round(100.0 * sum(contradicted_rates) / len(contradicted_rates), 1) if contradicted_rates else 0.0,
            "strict_p07_pct_entailed": round(100.0 * counts_strict["entailed"] / total, 1) if total else 0.0,
            "gold_evidence_subset": {
                "claims_with_evidence": ev_total,
                "pct_entailed": round(100.0 * ev_counts["entailed"] / ev_total, 1) if ev_total else 0.0,
                "pct_neutral": round(100.0 * ev_counts["neutral"] / ev_total, 1) if ev_total else 0.0,
                "pct_contradicted": round(100.0 * ev_counts["contradicted"] / ev_total, 1) if ev_total else 0.0,
            },
        }

    for row in rows:
        qid = row["id"]
        q_arms = {}
        for arm in ARMS:
            ans = (row["arms"][arm].get("answer") or "").strip()
            claims = split_claims(ans) if ans else []
            scored = [{"claim": c, **claim_verdicts[(qid, c)]} for c in claims]
            c_arm = Counter(x["verdict"] for x in scored)
            q_arms[arm] = {
                "n_claims": len(claims),
                "entailed": c_arm["entailed"],
                "neutral": c_arm["neutral"],
                "contradicted": c_arm["contradicted"],
                "claims": scored,
            }
        per_question.append({
            "id": qid,
            "type": row["type"],
            "question": row["question"],
            "note_titles": row["retrieval"].get("note_titles", []),
            "n_sentences": len(question_sentences[qid]),
            "arms": q_arms,
        })

    calibration_eval = None
    if calibration_path.exists():
        cal_rows = [json.loads(l) for l in calibration_path.open() if l.strip()]
        h_labels = []
        m_labels = []
        cal_details = []
        for item in cal_rows:
            key = (item["question_id"], item["claim"])
            if key not in claim_verdicts:
                # Re-score directly if not in unique_pairs.
                note_titles = item.get("note_titles") or next(
                    (r["retrieval"].get("note_titles", []) for r in rows if r["id"] == item["question_id"]), []
                )
                sents = split_premise_sentences([corpus[t] for t in note_titles if t in corpus])
                cands = candidate_premises_for_claim(sents, item["claim"], top_k=30)
                ws = model.score_pairs([(p, item["claim"]) for p, _ in cands], batch_size=32)
                pred = aggregate_claim_verdict([(ov, sc) for (_, ov), sc in zip(cands, ws)])
            else:
                pred = claim_verdicts[key]
            h_labels.append(item["human_label"])
            m_labels.append(pred["verdict"])
            cal_details.append({
                "calib_id": item["calib_id"],
                "question_id": item["question_id"],
                "claim": item["claim"],
                "human_label": item["human_label"],
                "nli_verdict": pred["verdict"],
                "max_entailment": pred["max_entailment"],
                "max_contradiction": pred["max_contradiction"],
                "match": item["human_label"] == pred["verdict"],
            })

        three_way = cohens_kappa(h_labels, m_labels, LABELS)
        hb = ["entailed" if x == "entailed" else "not_entailed" for x in h_labels]
        mb = ["entailed" if x == "entailed" else "not_entailed" for x in m_labels]
        binary = cohens_kappa(hb, mb, ("entailed", "not_entailed"))
        calibration_eval = {
            "calibration_file": calibration_path.name,
            "calibration_sha256": sha256_file(calibration_path),
            "blind": all(bool(r.get("blind")) for r in cal_rows),
            "three_way": three_way,
            "binary_entailed_vs_not": binary,
            "human_distribution": dict(Counter(h_labels)),
            "nli_distribution": dict(Counter(m_labels)),
            "items": cal_details,
        }

    report = {
        "meta": {
            "results_file": str(results_path.relative_to(ROOT)) if results_path.is_relative_to(ROOT) else str(results_path),
            "results_sha256": sha256_file(results_path),
            "corpus_sha256": sha256_file(corpus_path),
            "n_questions": len(rows),
            "n_unique_claims": len(unique_pairs),
            "n_nli_pair_evaluations": len(pair_list),
            "nli_model": {
                "repo": "cross-encoder/nli-deberta-v3-xsmall",
                "revision": "a150876415327c80daeff35ca6f68f5ed8cf5c24",
                "license": "Apache-2.0",
                "onnx_file": model.onnx_path.name,
                "onnx_sha256": sha256_file(model.onnx_path),
            },
            "aggregation": "SummaC-ZS sentence-pair max over top-30 (1- and 2-sentence) candidates per claim sorted by content-stem overlap; entailment argmax >= 0.50 -> entailed, else contradiction argmax >= 0.70 (gated on stem overlap >= 2) -> contradicted, else neutral",
            "r3_audit": {
                "questions_with_identical_non_empty_rag_answers": identical_non_empty_rag_arms,
                "total_questions": len(rows),
                "note": "In r3, questions_slice.r3.json stores note_titles rather than per-arm formatted context strings, so groundedness is scored against the retrieved note passages (plus gold evidence on the 7/11 questions that carry it).",
            },
        },
        "arms": arm_summary,
        "human_calibration": calibration_eval,
        "questions": per_question,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    json_out = out_dir / "faithfulness.r3.json"
    md_out = out_dir / "faithfulness.r3.md"
    json_out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    md_out.write_text(render_markdown(report))
    return report


def render_markdown(report: dict) -> str:
    meta = report["meta"]
    arms = report["arms"]
    cal = report.get("human_calibration")

    lines = [
        "# Independent Local NLI Faithfulness Report (`questions_slice.r3`)",
        "",
        f"- **Judge:** `{meta['nli_model']['repo']}` (`{meta['nli_model']['onnx_file']}`, Apache-2.0, pinned rev `{meta['nli_model']['revision'][:12]}`, **zero Gemini/LLM calls**)",
        f"- **Slice:** `{meta['results_file']}` (`n={meta['n_questions']}` questions, `{meta['n_unique_claims']}` unique atomic claims, `{meta['n_nli_pair_evaluations']}` `(premise, claim)` NLI inferences)",
        f"- **Aggregation:** {meta['aggregation']}",
        "",
        "## Per-Arm Claim Groundedness (vs. Retrieved Notes)",
        "",
        "| Arm | Answered Qs | Claims | % Entailed | % Neutral (Ungrounded) | % Contradicted | Mean Answer % Entailed | Strict p>=0.7 % Entailed |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for arm in ARMS:
        a = arms[arm]
        lines.append(
            f"| `{arm}` | {a['non_empty_answers']}/{meta['n_questions']} | {a['total_claims']} | "
            f"**{a['pct_entailed']:.1f}%** | {a['pct_neutral']:.1f}% | {a['pct_contradicted']:.1f}% | "
            f"{a['mean_answer_entailed_rate']:.1f}% | {a['strict_p07_pct_entailed']:.1f}% |"
        )

    lines += [
        "",
        f"> **Slice audit note:** `{meta['r3_audit']['questions_with_identical_non_empty_rag_answers']}/{meta['r3_audit']['total_questions']}` "
        "questions in `questions_slice.r3.json` produced byte-identical answer text across all non-empty grounded arms (`vector_only`, `graph_only`, `global_only`, `shipped`). "
        "Only `global_only` differs substantially by returning empty answers on `5/11` questions when map-reduce summary is absent, while `graph_only` is empty on `1/11` and `closed_book` writes long parametric essays (`15/15+` claims per answer).",
    ]

    if cal:
        tw = cal["three_way"]
        bi = cal["binary_entailed_vs_not"]
        m = tw["matrix"]
        lines += [
            "",
            "## Blind Human Calibration",
            "",
            f"- **Sample size:** `n={tw['n']}` claims hand-labeled blindly before running NLI (`blind={cal['blind']}`)",
            f"- **3-way (`entailed` / `neutral` / `contradicted`):** exact agreement = **{tw['agreement']*100:.1f}%**, Cohen's $\\kappa$ = **{tw['kappa']:.3f}** (chance = {tw['expected_chance_agreement']*100:.1f}%)",
            f"- **Binary (`entailed` vs `not_entailed`):** agreement = **{bi['agreement']*100:.1f}%**, Cohen's $\\kappa$ = **{bi['kappa']:.3f}**",
            "",
            "### Confusion Matrix (rows = human, cols = NLI)",
            "",
            "| Human \\ NLI | entailed | neutral | contradicted |",
            "|---|---|---|---|",
        ]
        for lbl, row_vals in zip(tw["labels"], m):
            lines.append(f"| **{lbl}** | {row_vals[0]} | {row_vals[1]} | {row_vals[2]} |")

    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(DEFAULT_RESULTS))
    ap.add_argument("--corpus", default=None)
    ap.add_argument("--calibration", default=str(DEFAULT_CALIBRATION))
    ap.add_argument("--out-dir", default=str(HERE / "results"))
    ap.add_argument("--fp32", action="store_true")
    ap.add_argument("--export-calibration-blind", action="store_true",
                    help="Sample ~33 blind claims + retrieved excerpts WITHOUT running NLI")
    ap.add_argument("--blind-out", default="/Users/naveenus/.gemini/antigravity/brain/b6f58e06-cfc1-4b3e-b370-cb1b287c8169/scratch/calibration_blind_export.json")
    args = ap.parse_args()

    results_path = Path(args.results)
    corpus_path = resolve_corpus_path(args.corpus)
    rows = json.loads(results_path.read_text())["rows"]
    corpus = load_corpus(corpus_path)

    if args.export_calibration_blind:
        items = sample_calibration_items(rows, corpus, target_n=33, seed=42)
        blind_path = Path(args.blind_out)
        blind_path.parent.mkdir(parents=True, exist_ok=True)
        blind_path.write_text(json.dumps(items, indent=1, ensure_ascii=False) + "\n")
        print(f"Exported {len(items)} blind calibration items -> {blind_path} (NO NLI run, NO arm names).")
        return

    report = score_all(
        results_path=results_path,
        corpus_path=corpus_path,
        calibration_path=Path(args.calibration),
        out_dir=Path(args.out_dir),
        fp32=args.fp32,
    )
    print(render_markdown(report))


if __name__ == "__main__":
    main()
