"""Freeze the 57 GraphRAG benchmark questions as an untouched router held-out set (`heldout_v2.jsonl`).

Combines:
  - 45 multi-hop factual lookup questions from `eval/graphrag/questions.json` (MuSiQue-Ans v1.0 dev)
  - 12 medical GraphRAG questions from `eval/graphrag/questions_slice.json` (GraphRAG-Bench medical)
Total = 57 questions that the router templates (`make_dataset.py`) were never tuned against.

Labels are assigned once from question phrasing + benchmark question type BEFORE running any
router evaluation (`label_source = "agent_provisional"`).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent

# Explicit pre-registered intent labels for the 12 GraphRAG-Bench medical questions,
# assigned strictly from question wording before scoring.
MEDICAL_SLICE_LABELS: dict[str, str] = {
    "Medical-1a7ab06f": "compare",    # "...suggest an aldosteronoma rather than a cortisol-producing adenoma?"
    "Medical-8217a825": "find",       # "What is the biggest risk factor for lung cancer?"
    "Medical-166bcaa7": "explain",    # "Why is Siewert type classification particularly important..."
    "Medical-915df475": "summarize",  # "What are the connections between risk factors, symptoms, and anatomical location..."
    "Medical-24373ebe": "explain",    # "How does the disease phase of CML affect the types of blood cells present?"
    "Medical-b2552c99": "compare",    # "How do the symptoms and diagnostic approaches differ between..."
    "Medical-081395a7": "summarize",  # "Which diagnostic methods are commonly used to evaluate adrenal tumors and what is their purpose?"
    "Medical-643b2b9d": "explain",    # "What constitutes recurrence in basal cell carcinoma and how is it managed?"
    "Medical-e3da3cd7": "compare",    # "Which diagnostic methods are common to both ACC and pheochromocytoma, and which are unique..."
    "Medical-34c3dd3d": "find",       # "Which cancer subtype arises from mucus-secreting cells in the esophagus?"
    "Medical-6a38af6d": "find",       # "What is a key biomarker used in risk assessment for CSCC?"
    "Medical-d675eecd": "find",       # "What is a flat, pale or yellow area on the skin indicative of in BCC?"
}


def main() -> None:
    musique_path = ROOT / "eval" / "graphrag" / "questions.json"
    slice_path = ROOT / "eval" / "graphrag" / "questions_slice.json"

    musique_qs = json.loads(musique_path.read_text())["questions"]
    slice_qs = json.loads(slice_path.read_text())["questions"]

    rows: list[dict] = []
    # 1. 45 MuSiQue multi-hop fact-lookup questions -> `find`
    for q in musique_qs:
        rows.append({
            "id": q["id"],
            "text": q["question"],
            "intent": "find",
            "label_source": "agent_provisional",
            "benchmark_source": "musique_dev_45",
        })

    # 2. 12 GraphRAG-Bench medical questions -> pre-registered intents above
    for q in slice_qs:
        qid = q["id"]
        if qid not in MEDICAL_SLICE_LABELS:
            raise KeyError(f"Missing pre-registered label for {qid}")
        rows.append({
            "id": qid,
            "text": q["question"],
            "intent": MEDICAL_SLICE_LABELS[qid],
            "label_source": "agent_provisional",
            "benchmark_source": "graphrag_bench_medical_12",
        })

    assert len(rows) == 57, f"Expected 57 GraphRAG benchmark questions, got {len(rows)}"

    out_path = HERE / "data" / "heldout_v2.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
    dist: dict[str, int] = {}
    for r in rows:
        dist[r["intent"]] = dist.get(r["intent"], 0) + 1
    print(f"froze {len(rows)} questions -> {out_path}")
    print(f"sha256: {digest}")
    print(f"label distribution: {dist}")


if __name__ == "__main__":
    main()
