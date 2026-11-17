"""Build the GraphRecall QA eval set from GraphRAG-Bench (medical): Xiang et al. 2025,
"When to use Graphs in RAG", huggingface.co/datasets/GraphRAG-Bench/GraphRAG-Bench.

Why this set: GraphRecall's extractor (backend/prompts/extraction.txt) is built for educational
content and pulls out concepts, definitions and relations, not named entities. Entity-hopping
benchmarks (MuSiQue, HotpotQA) bridge through people and places, which never become graph nodes
here (checked on a smoke ingest before any scoring), so they would test something the product does
not try to do. The medical corpus is concept-dense guideline text, and its questions are typed:
Fact Retrieval, Complex Reasoning, Contextual Summarize (Creative Generation is not used).

The corpus is one 1.05 MB string. It is split deterministically into notes of about NOTE_CHARS
characters, each ending at a sentence boundary. Every question is assigned to the note its evidence
best matches (TF-IDF over evidence + gold answer), which lets a slice ingest a prefix of the corpus
and ask only questions whose evidence lies inside it.

    python eval/graphrag/fetch_graphrag_bench.py                       # 20 per type over the whole corpus
    python eval/graphrag/fetch_graphrag_bench.py --upto-note 24 --per-type 4 --out questions_slice.json
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import random
import re
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "grb"
BASE = "https://huggingface.co/datasets/GraphRAG-Bench/GraphRAG-Bench/resolve/main/Datasets"
NOTE_CHARS = 5000
TYPES = ("Fact Retrieval", "Complex Reasoning", "Contextual Summarize")


def fetch() -> tuple[str, list[dict]]:
    DATA.mkdir(parents=True, exist_ok=True)
    for name, url in (("medical.json", f"{BASE}/Corpus/medical.json"),
                      ("medical_questions.json", f"{BASE}/Questions/medical_questions.json")):
        if not (DATA / name).exists():
            urllib.request.urlretrieve(url, DATA / name)
    ctx = json.loads((DATA / "medical.json").read_text())[0]["context"]
    return ctx, json.loads((DATA / "medical_questions.json").read_text())


def split(ctx: str) -> list[str]:
    notes, start = [], 0
    while start < len(ctx):
        end = min(len(ctx), start + NOTE_CHARS)
        if end < len(ctx):
            m = re.search(r"[.!?]\s", ctx[end:end + 1500])
            end = end + m.end() if m else end
        notes.append(ctx[start:end].strip())
        start = end
    return notes


TOKEN = re.compile(r"[a-z][a-z0-9\-]{2,}")


def tokens(s: str) -> list[str]:
    return TOKEN.findall(s.lower())


def evidence_text(q: dict) -> str:
    ev = q.get("evidence")
    if isinstance(ev, str):
        try:
            ev = ast.literal_eval(ev)
        except Exception:  # noqa: BLE001
            ev = [ev]
    flat = []
    stack = [ev]
    while stack:
        x = stack.pop()
        if isinstance(x, list):
            stack.extend(x)
        else:
            flat.append(str(x))
    return " ".join(flat) + " " + q.get("answer", "")


def assign(notes: list[str], questions: list[dict]) -> list[tuple[int, float]]:
    docs = [Counter(tokens(n)) for n in notes]
    df = Counter(t for d in docs for t in d)
    idf = {t: math.log(len(docs) / c) for t, c in df.items()}

    def vec(cnt: Counter) -> dict:
        v = {t: (1 + math.log(c)) * idf.get(t, 0.0) for t, c in cnt.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    dvecs = [vec(d) for d in docs]
    out = []
    for q in questions:
        qv = vec(Counter(tokens(evidence_text(q))))
        sims = [sum(w * dv.get(t, 0.0) for t, w in qv.items()) for dv in dvecs]
        best = max(range(len(sims)), key=sims.__getitem__)
        second = sorted(sims)[-2] if len(sims) > 1 else 0.0
        out.append((best, round(sims[best] - second, 4)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-type", type=int, default=20)
    ap.add_argument("--upto-note", type=int, default=None, help="only questions whose evidence is in notes [0, N)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="questions_grb.json")
    args = ap.parse_args()

    ctx, questions = fetch()
    notes = split(ctx)
    with (DATA / "corpus.jsonl").open("w") as f:
        for i, n in enumerate(notes):
            key = hashlib.sha1(n.encode()).hexdigest()[:12]
            f.write(json.dumps({"key": key, "order": i, "title": f"NCCN patient guide excerpt {i + 1:03d}",
                                "text": n}, ensure_ascii=False) + "\n")

    homes = assign(notes, questions)
    rng = random.Random(args.seed)
    picked = []
    for t in TYPES:
        pool = [(q, h) for q, h in zip(questions, homes) if q["question_type"] == t
                and (args.upto_note is None or h[0] < args.upto_note)]
        pool.sort(key=lambda x: x[0]["id"])
        picked += rng.sample(pool, min(args.per_type, len(pool)))
    rng.shuffle(picked)

    meta = {
        "source": "GraphRAG-Bench medical (Xiang et al. 2025), huggingface.co/datasets/GraphRAG-Bench/GraphRAG-Bench",
        "seed": args.seed, "per_type": args.per_type, "types": list(TYPES), "note_chars": NOTE_CHARS,
        "corpus_notes": len(notes), "upto_note": args.upto_note,
        "note": "Corpus text is in data/grb/corpus.jsonl (not committed; rebuild with this script). "
                "home_note = the note whose text best matches the question's evidence (TF-IDF).",
    }
    out = [{"id": q["id"], "type": q["question_type"], "question": q["question"], "answer": q["answer"],
            "evidence": evidence_text(q).replace(q.get("answer", ""), "").strip(),
            "home_note": h[0], "home_margin": h[1]} for q, h in picked]
    (HERE / args.out).write_text(json.dumps({"meta": meta, "questions": out}, indent=1, ensure_ascii=False))
    print(json.dumps(meta, indent=1))
    print(Counter(q["type"] for q in out), "home notes:", sorted(q["home_note"] for q in out))


if __name__ == "__main__":
    main()
