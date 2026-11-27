"""Build a retrieval golden set: GraphRAG-Bench questions labelled with the chunks that hold their evidence.

Labels are at child-chunk level, the unit retrieval ranks. The answer-level benchmark (eval/graphrag/run_eval.py) needs an LLM judge and only fits ~10 questions
per run. Retrieval can be measured without any LLM: GraphRAG-Bench ships, for every question, the
evidence sentences a correct answer rests on. A child chunk is *relevant* to a question when it
contains one of those sentences (token recall >= MATCH, after lower-casing and dropping stopwords),
so labels are mechanical and reproducible, not judged.

Corpus: the notes already ingested through the product pipeline for an eval run (EVAL_RUN tag, eval
database). Only questions whose evidence is found in that corpus are kept.

    EVAL_RUN=r3 PYTHONPATH=. python eval/retrieval/build_golden.py            # -> eval/retrieval/golden.r3.jsonl

Caveats, stated in the output too: the questions are human-written benchmark questions about medical
guidelines, not GraphRecall users' study questions; labels mark *a* supporting chunk, not every
chunk that could help; evidence matched by tokens favours near-verbatim evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "graphrag"))

import _env  # noqa: E402  (sets DATABASE_URL to the eval database, throttles Gemini)

MATCH = 0.8          # share of an evidence sentence's content words that must appear in the chunk
MIN_SENT_WORDS = 5   # shorter evidence sentences match too easily to be a label
TYPES = ("Fact Retrieval", "Complex Reasoning", "Contextual Summarize")
STOP = set("""a an the of and or to in on for with by from as at is are was were be been being this that these
those it its into than then there their they them which who whom whose what when where why how can could may
might should would will not no do does did done such also more most other any each all both either neither""".split())


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP and len(w) > 1}


def sentences(evidence) -> list[str]:
    items = evidence if isinstance(evidence, list) else [evidence or ""]
    out = []
    for item in items:
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+", item) if s.strip()]
    return out


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-type", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    _env.setup()
    from backend.db.postgres_client import get_postgres_client

    user_id = await _env.eval_user_id("grb")
    pg = await get_postgres_client()
    children = await pg.execute_query(
        "SELECT c.id, c.parent_chunk_id, c.chunk_index, c.content, p.chunk_index AS parent_index "
        "FROM chunks c JOIN chunks p ON p.id = c.parent_chunk_id "
        "WHERE c.user_id = CAST(:u AS uuid) AND c.chunk_level = 'child' AND c.embedding IS NOT NULL "
        "ORDER BY c.note_id, p.chunk_index, c.chunk_index",
        {"u": user_id},
    )
    if not children:
        sys.exit(f"no ingested corpus for eval user {user_id}; run eval/graphrag/ingest_corpus.py first")
    parents = {str(c["parent_chunk_id"]) for c in children}
    # Label at child level (what retrieval ranks). A sentence cut across two neighbouring children of
    # the same parent is matched against the pair and labels both.
    units = [([str(c["id"])], words(c["content"])) for c in children]
    for a_, b_ in zip(children, children[1:]):
        if a_["parent_chunk_id"] == b_["parent_chunk_id"]:
            units.append(([str(a_["id"]), str(b_["id"])], words(a_["content"] + " " + b_["content"])))
    pw = units

    questions = json.loads((HERE.parent / "graphrag/data/grb/medical_questions.json").read_text())
    kept, reasons = [], Counter()
    for q in questions:
        if q.get("question_type") not in TYPES:
            continue
        relevant, matched_sents, total = {}, 0, 0
        for sent in sentences(q.get("evidence")):
            sw = words(sent)
            if len(sw) < MIN_SENT_WORDS:
                continue
            total += 1
            scored = [(len(sw & cw) / len(sw), ids) for ids, cw in pw]
            singles = [(sc, ids) for sc, ids in scored if sc >= MATCH and len(ids) == 1]
            hits = singles or [(sc, ids) for sc, ids in scored if sc >= MATCH]   # pairs only if no single child holds it
            if hits:
                matched_sents += 1
                for score, ids in hits:
                    for cid in ids:
                        relevant[cid] = max(relevant.get(cid, 0.0), round(score, 3))
        if not total:
            reasons["no usable evidence sentence"] += 1
        elif not relevant:
            reasons["evidence not in ingested corpus"] += 1
        else:
            kept.append({"id": q["id"], "type": q["question_type"], "question": q["question"],
                         "answer": q.get("answer"), "relevant_child_ids": sorted(relevant),
                         "evidence_match": relevant, "evidence_sentences_matched": f"{matched_sents}/{total}"})

    rng = random.Random(args.seed)
    by_type: dict[str, list] = {}
    for k in kept:
        by_type.setdefault(k["type"], []).append(k)
    sample = []
    for t in TYPES:
        pool = by_type.get(t, [])
        rng.shuffle(pool)
        sample += pool[: args.per_type]

    out = HERE / f"golden.{_env.run_key('grb').split('-', 1)[-1]}.jsonl"
    with out.open("w") as fh:
        for row in sample:
            fh.write(json.dumps(row) + "\n")
    print(f"corpus: {len(children)} child / {len(parents)} parent chunks for eval user {user_id}")
    print(f"questions with evidence in corpus: {len(kept)} (dropped: {dict(reasons)})")
    print(f"sampled {len(sample)} -> {out}  by type: {Counter(r['type'] for r in sample)}")
    print(f"relevant children per question: mean {sum(len(r['relevant_child_ids']) for r in sample) / max(1, len(sample)):.2f}")


if __name__ == "__main__":
    asyncio.run(main())
