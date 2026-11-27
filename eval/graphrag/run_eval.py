"""Score GraphRecall's chat retrieval on GraphRAG-Bench questions: vector vs graph vs global vs shipped hybrid.

Per question, the product's own nodes run once:
  analyze_query_node  → intent, entities
  get_context_node    → graph_context (seed concepts + k-hop, maybe global map-reduce) and rag_context (top-5 chunks)
and the result is reused across arms, so the arms differ only in what reaches the generator:

  closed_book   no context, plain "answer the question" prompt (the product prompt would only say "add notes")
  vector_only   rag_context only
  graph_only    graph side only: concepts, relationships, and a global summary if the product produced one
  global_only   community map-reduce summary only (get_context_node rerun with intent forced to "summarize")
  shipped       everything get_context_node returned: what the app sends today

Each arm's answer comes from generate_response_node (closed_book excepted) and is scored with the
benchmark's own metric definitions (GraphRAG-Bench Evaluation/metrics), re-implemented here:
  answer_correctness = 0.75 * statement-level F1 (TP/FP/FN vs the gold answer) + 0.25 * embedding cosine
  factual_recall     = TP / (TP + FN), reported separately because the app's answers are long and
                       educational, which costs precision for every arm alike
  context_recall     = share of gold-answer statements attributable to the context the generator saw
                       (formatted exactly as generate_response_node formats it: a window around the matched chunk)
The judge is the same model as the generator (gemini-3.5-flash-lite, the only model this key can run).

    python eval/graphrag/run_eval.py --questions questions_slice.json
Writes results/<name>.json and results/<name>.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import re
import time

import _env

_env.setup()

from langchain_core.messages import HumanMessage  # noqa: E402

from backend import telemetry  # noqa: E402

ARMS = ("closed_book", "vector_only", "graph_only", "global_only", "shipped")
RESULTS = _env.HERE / "results"


# ---------------------------------------------------------------- context formatting (mirrors generate_response_node)

def format_context(graph_context: dict, rag_context: list[dict]) -> str:
    parts = []
    if graph_context.get("concepts"):
        lines = []
        for c in graph_context["concepts"]:
            hops = c.get("hops", 0)
            conf = c.get("confidence", 0.8)
            tag = " [high confidence]" if conf >= 0.85 else (" [low confidence]" if conf < 0.5 else "")
            if hops and hops >= 2:
                lines.append(f"- {c.get('name', 'Unknown')}{tag} (hop {hops})")
            else:
                suffix = f" (hop {hops})" if hops else ""
                lines.append(f"- {c.get('name', 'Unknown')}{tag}{suffix}: {c.get('definition', 'No definition')}")
        parts.append("**Knowledge Graph Concepts:**\n" + "\n".join(lines))
    if graph_context.get("global_summary"):
        parts.append(f"**Global Summary:**\n{graph_context['global_summary']}")
    if graph_context.get("relationships"):
        rels = []
        for r in graph_context["relationships"][:15]:
            strength = r.get("strength", 1.0)
            tag = f" (strength: {strength:.1f})" if strength < 1.0 else ""
            rels.append(f"- {r.get('src_name') or r.get('src')} --[{r.get('type')}]--> {r.get('tgt_name') or r.get('tgt')}{tag}")
        parts.append("**Relationships:**\n" + "\n".join(rels))
    if rag_context:
        # Same snippet generate_response_node sends: a window centred on the matched child chunk.
        from backend.services.retrieval_service import extract_child_centered_window
        notes = [f"[{i}] {n.get('title', 'Note')}: "
                 + (n.get("window_content") or extract_child_centered_window(
                     n.get("parent_content") or n.get("content") or "", n.get("child_content") or ""))
                 for i, n in enumerate(rag_context, 1)]
        parts.append("**Relevant Notes:**\n" + "\n".join(notes))
    return "\n\n".join(parts)


def arm_inputs(arm: str, gc: dict, rag: list[dict], gc_global: dict) -> tuple[dict, list[dict]]:
    empty = {"concepts": [], "relationships": []}
    if arm == "vector_only":
        return empty, rag
    if arm == "graph_only":
        return gc, []
    if arm == "global_only":
        return {**empty, **({"global_summary": gc_global["global_summary"]} if gc_global.get("global_summary") else {})}, []
    if arm == "shipped":
        return gc, rag
    return empty, []


# ---------------------------------------------------------------- metrics (GraphRAG-Bench definitions)

STATEMENTS_PROMPT = """Generate concise independent statements from the given text that represent factual claims.
Respond ONLY with a JSON array of strings. Do not include any other text.
Example Input:
"The sun is powered by nuclear fusion. This process creates light and heat."
Example Output:
["The sun is powered by nuclear fusion", "Nuclear fusion creates light and heat"]
Input Text:
{text}
Generated Statements:
"""

CORRECTNESS_PROMPT = """Analyze statements from an answer compared to ground truth. Classify each as:
- TP (True Positive): Present in answer and supported by ground truth
- FP (False Positive): Present in answer but unsupported
- FN (False Negative): Missing from answer but present in ground truth
Provide JSON output with lists of TP, FP, FN objects containing 'statement' and 'reason'.
Example:
Question: "What powers the sun and its primary function?"
Answer Statements: ["The sun is powered by nuclear fission", "Its primary function is providing light"]
Ground Truth Statements: ["The sun is powered by nuclear fusion", "Fusion creates energy for heat and light", "Sunlight is essential for Earth's climate"]
Output: {{"TP": [{{"statement": "Its primary function is providing light", "reason": "Matches ground truth about light"}}],
 "FP": [{{"statement": "The sun is powered by nuclear fission", "reason": "Contradicts fusion fact"}}],
 "FN": [{{"statement": "The sun is powered by nuclear fusion", "reason": "Missing correct power source"}},
        {{"statement": "Fusion creates energy for heat and light", "reason": "Missing energy creation detail"}}]}}
Current Analysis:
Question: "{question}"
Answer Statements: {answer}
Ground Truth Statements: {ground_truth}
"""

CONTEXT_RECALL_PROMPT = """Analyze each sentence in the Answer and determine if it can be attributed to the Context.
Respond ONLY with a JSON object containing a "classifications" list. Each item should have:
- "statement": the exact sentence from Answer
- "reason": brief explanation (1 sentence)
- "attributed": 1 for yes, 0 for no
Input:
Context: "Einstein won the Nobel Prize in 1921 for physics."
Answer: "Einstein received the Nobel Prize. He was born in Germany."
Output:
{{"classifications": [{{"statement": "Einstein received the Nobel Prize", "reason": "Matches context about Nobel Prize", "attributed": 1}},
 {{"statement": "He was born in Germany", "reason": "Birth information not in context", "attributed": 0}}]}}
Context: "{context}"
Answer: "{answer}"
Question: "{question}" (for reference only)
"""


def parse_json(text: str):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = text.find(opener), text.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(text[i:j + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"no JSON in judge output: {text[:200]}")


async def judge(prompt: str, retries: int = 2):
    from backend.config.llm import get_fast_model

    llm = get_fast_model(temperature=0)
    last = None
    for _ in range(retries + 1):
        try:
            return parse_json((await llm.ainvoke(prompt)).text)
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


async def statements(text: str) -> list[str]:
    out = await judge(STATEMENTS_PROMPT.format(text=text[:6000]))
    return [str(s) for s in out] if isinstance(out, list) else []


async def cosine(a: str, b: str) -> float:
    from backend.config.llm import get_embeddings, get_embedding_dims

    emb, dims = get_embeddings(), get_embedding_dims()
    va = await emb.aembed_query(a[:8000], output_dimensionality=dims)
    vb = await emb.aembed_query(b[:8000], output_dimensionality=dims)
    dot = sum(x * y for x, y in zip(va, vb))
    return dot / (math.sqrt(sum(x * x for x in va)) * math.sqrt(sum(y * y for y in vb)) or 1.0)


async def answer_correctness(question: str, answer: str, gold: str, gold_stmts: list[str]) -> dict:
    ans_stmts = await statements(answer)
    cls = await judge(CORRECTNESS_PROMPT.format(question=question, answer=json.dumps(ans_stmts), ground_truth=json.dumps(gold_stmts)))
    tp, fp, fn = (len(cls.get(k, []) or []) for k in ("TP", "FP", "FN"))
    precision, recall = tp / (tp + fp + 1e-10), tp / (tp + fn + 1e-10)
    f1 = 2 * precision * recall / (precision + recall + 1e-10)
    sim = await cosine(answer, gold)
    return {"score": 0.75 * f1 + 0.25 * sim, "f1": f1, "factual_recall": recall, "factual_precision": precision,
            "similarity": sim, "tp": tp, "fp": fp, "fn": fn, "classification": cls}


async def context_recall(question: str, context: str, gold: str) -> dict:
    if not context.strip():
        return {"score": 0.0, "classifications": []}
    out = await judge(CONTEXT_RECALL_PROMPT.format(context=context[:10000], answer=gold[:2000], question=question))
    cls = out.get("classifications", []) if isinstance(out, dict) else []
    vals = [int(c.get("attributed", 0)) for c in cls]
    return {"score": sum(vals) / len(vals) if vals else 0.0, "classifications": cls}


# ---------------------------------------------------------------- one question

def calls() -> int:
    return sum(v["calls"] for v in telemetry.snapshot()["llm"].values())


async def closed_book_answer(question: str) -> str:
    from backend.config.llm import get_chat_model

    return (await get_chat_model(temperature=0.3).ainvoke(f"Answer the question.\n\nQuestion: {question}")).text


async def run_question(q: dict, user_id: str) -> dict:
    cb = importlib_chat()
    state = {"messages": [HumanMessage(content=q["question"])], "user_id": user_id, "focused_source_ids": []}

    c0, t0 = calls(), time.time()
    analysis = await cb.analyze_query_node(state)
    intent = analysis.get("intent", "general")
    overridden = intent == "quiz"  # the quiz branch spawns background card generation instead of answering
    if overridden:
        analysis["intent"] = "find"
    ctx = await cb.get_context_node({**state, **analysis})
    gc, rag = ctx["graph_context"], ctx["rag_context"]
    retrieval = {"intent": intent, "intent_overridden": overridden, "entities": analysis.get("entities", []),
                 "search_mode": gc.get("search_mode"), "vector_seeds": gc.get("vector_seeds"),
                 "concepts": len(gc.get("concepts", [])),
                 "relationships": len(gc.get("relationships", [])), "notes": len(rag),
                 "note_titles": [n.get("title") for n in rag], "llm_calls": calls() - c0, "seconds": round(time.time() - t0, 1)}

    if gc.get("global_summary"):
        gc_global = gc
    else:
        c1 = calls()
        gctx = await cb.get_context_node({**state, **analysis, "intent": "summarize", "entities": []})
        gc_global = gctx["graph_context"]
        retrieval["global_extra_llm_calls"] = calls() - c1
    retrieval["global_search_mode"] = gc_global.get("search_mode")

    gold_stmts = await statements(q["answer"])
    arms = {}
    for arm in ARMS:
        a_gc, a_rag = arm_inputs(arm, gc, rag, gc_global)
        context = format_context(a_gc, a_rag)
        c_arm, t_arm = calls(), time.time()
        if arm == "closed_book":
            answer = await closed_book_answer(q["question"])
        elif not context:
            answer = None  # nothing retrieved for this arm; the product would answer from "No specific context found."
        else:
            out = await cb.generate_response_node({**state, **analysis, "graph_context": a_gc, "rag_context": a_rag})
            answer = out["messages"][-1].content
        rec = {"context_chars": len(context), "gen_seconds": round(time.time() - t_arm, 1), "gen_llm_calls": calls() - c_arm,
               "answer": answer}
        if answer is not None:
            rec["correctness"] = await answer_correctness(q["question"], answer, q["answer"], gold_stmts)
        else:
            rec["correctness"] = {"score": 0.0, "f1": 0.0, "factual_recall": 0.0, "factual_precision": 0.0, "similarity": 0.0,
                                  "empty_context": True}
        if arm != "closed_book":
            rec["context_recall"] = await context_recall(q["question"], context, q["answer"])
        arms[arm] = rec
    # Diagnostic: the same retrieved notes in full, not just the window the prompt sends.
    full_notes = "\n".join(f"[{i}] {n.get('title')}: {n.get('content') or ''}" for i, n in enumerate(rag, 1))
    retrieval["vector_untruncated_context_recall"] = (await context_recall(q["question"], full_notes, q["answer"]))["score"]
    return {**q, "retrieval": retrieval, "gold_statements": gold_stmts, "arms": arms}


def importlib_chat():
    import importlib

    return importlib.import_module("backend.graphs.chat_graph")


# ---------------------------------------------------------------- aggregation

def bootstrap_diff(a: list[float], b: list[float], n: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    rng = random.Random(seed)
    d = [x - y for x, y in zip(a, b)]
    means = sorted(sum(rng.choice(d) for _ in d) / len(d) for _ in range(n))
    return sum(d) / len(d), means[int(0.025 * n)], means[int(0.975 * n)]


def aggregate(rows: list[dict]) -> dict:
    types = sorted({r["type"] for r in rows})
    out = {"n": len(rows), "by_type": {}, "overall": {}, "vs_vector_only": {}}

    def stats(subset):
        res = {}
        for arm in ARMS:
            vals = [r["arms"][arm] for r in subset]
            res[arm] = {
                "answer_correctness": sum(v["correctness"]["score"] for v in vals) / len(vals),
                "factual_recall": sum(v["correctness"]["factual_recall"] for v in vals) / len(vals),
                "context_recall": (sum(v["context_recall"]["score"] for v in vals) / len(vals)) if arm != "closed_book" else None,
                "empty_context": sum(1 for v in vals if v["correctness"].get("empty_context")),
            }
        return res

    out["overall"] = stats(rows)
    for t in types:
        out["by_type"][t] = {"n": sum(r["type"] == t for r in rows), **stats([r for r in rows if r["type"] == t])}
    base = [r["arms"]["vector_only"]["correctness"]["score"] for r in rows]
    for arm in ARMS:
        if arm != "vector_only":
            mean, lo, hi = bootstrap_diff([r["arms"][arm]["correctness"]["score"] for r in rows], base)
            out["vs_vector_only"][arm] = {"mean_diff": mean, "ci95": [lo, hi]}
    out["retrieval"] = {
        "search_modes": {m: sum(r["retrieval"]["search_mode"] == m for r in rows) for m in {r["retrieval"]["search_mode"] for r in rows}},
        "questions_with_seed_concepts": sum(r["retrieval"]["concepts"] > 0 for r in rows),
        "mean_concepts": sum(r["retrieval"]["concepts"] for r in rows) / len(rows),
        "mean_relationships": sum(r["retrieval"]["relationships"] for r in rows) / len(rows),
        "mean_get_context_llm_calls": sum(r["retrieval"]["llm_calls"] for r in rows) / len(rows),
        "vector_context_recall_prompt": sum(r["arms"]["vector_only"]["context_recall"]["score"] for r in rows) / len(rows),
        "vector_context_recall_untruncated": sum(r["retrieval"]["vector_untruncated_context_recall"] for r in rows) / len(rows),
        "intents": {i: sum(r["retrieval"]["intent"] == i for r in rows) for i in {r["retrieval"]["intent"] for r in rows}},
    }
    return out


def markdown(name: str, meta: dict, agg: dict) -> str:
    f = lambda x: "–" if x is None else f"{x:.2f}"  # noqa: E731
    L = [f"# GraphRecall retrieval eval: {name}", "",
         f"_Generated by `eval/graphrag/run_eval.py` on {meta['run_at']}. {agg['n']} GraphRAG-Bench medical questions; "
         f"corpus: first {meta['corpus_notes']} notes ingested through the product pipeline. Models: {meta['models']}. "
         "Judge = generator model. Metric definitions follow GraphRAG-Bench (answer correctness = 0.75·statement F1 + 0.25·cosine)._", "",
         "## Answer correctness (context recall)", "",
         "| Question type | n | " + " | ".join(ARMS) + " |", "|---|---|" + "---|" * len(ARMS)]
    rows = [("All", agg["n"], agg["overall"])] + [(t, v["n"], v) for t, v in agg["by_type"].items()]
    for label, n, s in rows:
        cells = []
        for arm in ARMS:
            a = s[arm]
            cells.append(f"{f(a['answer_correctness'])}" + (f" ({f(a['context_recall'])})" if a["context_recall"] is not None else ""))
        L.append(f"| {label} | {n} | " + " | ".join(cells) + " |")
    L += ["", "## Difference from vector-only (answer correctness, paired bootstrap 95% CI)", ""]
    for arm, d in agg["vs_vector_only"].items():
        L.append(f"- {arm}: {d['mean_diff']:+.3f} [{d['ci95'][0]:+.3f}, {d['ci95'][1]:+.3f}]")
    r = agg["retrieval"]
    L += ["", "## Retrieval diagnostics", "",
          f"- Questions where seed-concept matching found any graph concept: {r['questions_with_seed_concepts']}/{agg['n']}",
          f"- Mean concepts / relationships in graph context: {r['mean_concepts']:.1f} / {r['mean_relationships']:.1f}",
          f"- search_mode counts (shipped path): {r['search_modes']}",
          f"- Intents: {r['intents']}",
          f"- Mean LLM calls inside get_context_node (map-reduce): {r['mean_get_context_llm_calls']:.1f}",
          f"- Vector context recall as the prompt sees it (matched-chunk window): {r['vector_context_recall_prompt']:.2f}; "
          f"same notes untruncated: {r['vector_context_recall_untruncated']:.2f}"]
    return "\n".join(L) + "\n"


async def main(questions_file: str, limit: int | None) -> None:
    _env.throttle_llm()
    user_id = await _env.eval_user_id("grb")
    spec = json.loads((_env.HERE / questions_file).read_text())
    qs = spec["questions"][:limit] if limit else spec["questions"]
    name = (questions_file.removesuffix(".json") + (f".{os.getenv('EVAL_RUN')}" if os.getenv("EVAL_RUN") else "")
            + ("" if os.getenv("GRAPH_SEED_MODE", "substring") == "substring" else "." + os.getenv("GRAPH_SEED_MODE")))
    RESULTS.mkdir(exist_ok=True)
    partial = RESULTS / f"{name}.partial.jsonl"
    done = {json.loads(l)["id"]: json.loads(l) for l in partial.open()} if partial.exists() else {}
    invalid: list[str] = []
    for i, q in enumerate(qs, 1):
        if q["id"] in done:
            continue
        t0, c0 = time.time(), calls()
        e0 = _env.EMBED_ERRORS["count"]
        l0 = sum(v["errors"] for v in telemetry.snapshot()["llm"].values())
        try:
            row = await run_question(q, user_id)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(qs)}] FAILED {q['id']}: {type(e).__name__}: {str(e)[:200]}", flush=True)
            continue
        row["seconds"], row["llm_calls"] = round(time.time() - t0, 1), calls() - c0
        # Product nodes swallow model errors (an empty vector context, a skipped map step), which would
        # score as a real zero. Such rows are kept on disk but excluded from every aggregate.
        row["embed_errors"] = _env.EMBED_ERRORS["count"] - e0
        row["llm_errors"] = sum(v["errors"] for v in telemetry.snapshot()["llm"].values()) - l0
        row["valid"] = not row["embed_errors"] and not row["llm_errors"]
        if not row["valid"]:
            invalid.append(q["id"])
            print(f"[{i}/{len(qs)}] INVALID {q['id']} (embed_errors={row['embed_errors']}, llm_errors={row['llm_errors']}); "
                  "not saved, a rerun retries it", flush=True)
            if _env.EMBED_ERRORS["daily_quota"]:
                print("Daily embedding quota hit; stopping (rerun resumes).", flush=True)
                break
            continue
        done[q["id"]] = row
        with partial.open("a") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        s = {a: round(row["arms"][a]["correctness"]["score"], 2) for a in ARMS}
        print(f"[{i}/{len(qs)}] {q['type'][:12]:12s} {row['seconds']:5.0f}s calls={row['llm_calls']} mode={row['retrieval']['search_mode']} {s}", flush=True)

    rows = [done[q["id"]] for q in qs if q["id"] in done]
    ingest_log = json.loads((_env.DATA / f"ingested_{_env.run_key('grb')}.json").read_text())
    meta = {"run_at": time.strftime("%Y-%m-%d %H:%M"), "questions_file": questions_file, "models": _env.models(),
            "corpus_notes": len(ingest_log["notes"]), "communities": ingest_log.get("communities", {}).get("count"),
            "incomplete_notes": sum(n.get("status") != "completed" for n in ingest_log["notes"].values()),
            "seed_mode": os.getenv("GRAPH_SEED_MODE", "substring"),
            "missing": [q["id"] for q in qs if q["id"] not in done],
            "invalid_this_run": invalid}
    agg = aggregate(rows) if rows else {}
    (RESULTS / f"{name}.json").write_text(json.dumps({"meta": meta, "aggregate": agg, "rows": rows}, indent=1, ensure_ascii=False))
    if rows:
        (RESULTS / f"{name}.md").write_text(markdown(name, meta, agg))
        print((RESULTS / f"{name}.md").read_text())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions", default="questions_slice.json")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    asyncio.run(main(a.questions, a.limit))
