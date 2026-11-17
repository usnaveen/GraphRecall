"""Build the GraphRecall QA eval set from MuSiQue-Ans dev (multi-hop questions over Wikipedia paragraphs).

MuSiQue (Trivedi et al., TACL 2022, CC BY 4.0) composes 2-4 single-hop questions so that no single
paragraph answers the question. Each question comes with 20 paragraphs: the supporting ones plus
hard distractors retrieved to look relevant.

This script:
  1. downloads musique_ans_v1.0_dev.jsonl into eval/graphrag/data/ (git-ignored),
  2. draws a seeded sample stratified by hop count,
  3. keeps every supporting paragraph plus K distractors per question,
  4. pools all kept paragraphs into one corpus, one paragraph per note (deduplicated),
  5. writes data/corpus.jsonl (paragraph text, git-ignored) and questions.json (committed:
     ids, question, gold answer and aliases, and the corpus keys of the supporting paragraphs).

    python eval/graphrag/fetch_musique.py            # default sample: 20 two-hop, 15 three-hop, 10 four-hop
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SRC_URL = "https://huggingface.co/datasets/bdsaglam/musique/resolve/main/musique_ans_v1.0_dev.jsonl"
SRC = DATA / "musique_ans_v1.0_dev.jsonl"


def para_key(title: str, text: str) -> str:
    return hashlib.sha1(f"{title}\n{text}".encode()).hexdigest()[:12]


def hop_group(qid: str) -> str:
    return qid.split("__")[0][:4]  # 2hop / 3hop / 4hop


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n2", type=int, default=20)
    ap.add_argument("--n3", type=int, default=15)
    ap.add_argument("--n4", type=int, default=10)
    ap.add_argument("--distractors", type=int, default=6, help="distractor paragraphs kept per question")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    if not SRC.exists():
        urllib.request.urlretrieve(SRC_URL, SRC)
    rows = [json.loads(line) for line in SRC.open()]
    rows = [r for r in rows if r.get("answerable", True) and len(r["paragraphs"]) == 20]

    rng = random.Random(args.seed)
    picked = []
    for group, n in (("2hop", args.n2), ("3hop", args.n3), ("4hop", args.n4)):
        pool = sorted((r for r in rows if hop_group(r["id"]) == group), key=lambda r: r["id"])
        picked += rng.sample(pool, n)
    # Interleave hop groups so any prefix (the slice) has a mix of difficulties.
    rng.shuffle(picked)

    corpus: dict[str, dict] = {}
    questions = []
    for r in picked:
        sup = [p for p in r["paragraphs"] if p["is_supporting"]]
        dis = [p for p in r["paragraphs"] if not p["is_supporting"]]
        keep = sup + rng.sample(dis, min(args.distractors, len(dis)))
        sup_keys = []
        for p in keep:
            k = para_key(p["title"], p["paragraph_text"])
            corpus.setdefault(k, {"key": k, "title": p["title"], "text": p["paragraph_text"], "from": []})
            corpus[k]["from"].append(r["id"])
            if p["is_supporting"]:
                sup_keys.append(k)
        questions.append({
            "id": r["id"],
            "hops": int(r["id"][0]),
            "question": r["question"],
            "answer": r["answer"],
            "answer_aliases": r.get("answer_aliases", []),
            "supporting_keys": sup_keys,
            "decomposition": [d["question"] for d in r.get("question_decomposition", [])],
        })

    with (DATA / "corpus.jsonl").open("w") as f:
        for p in corpus.values():
            f.write(json.dumps(p, ensure_ascii=False) + "\n")
    meta = {
        "source": "MuSiQue-Ans v1.0 dev (Trivedi et al., TACL 2022, CC BY 4.0), via huggingface.co/datasets/bdsaglam/musique",
        "seed": args.seed,
        "per_hop": {"2": args.n2, "3": args.n3, "4": args.n4},
        "distractors_per_question": args.distractors,
        "corpus_paragraphs": len(corpus),
        "note": "One paragraph = one note. Paragraph text is in data/corpus.jsonl (not committed; rebuild with this script).",
    }
    (HERE / "questions.json").write_text(json.dumps({"meta": meta, "questions": questions}, indent=1, ensure_ascii=False))
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
