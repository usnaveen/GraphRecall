"""Ingest the eval corpus through GraphRecall's real ingestion graph, one paragraph per note.

Uses the product's node functions and edges (parse → chunk → extract_concepts → store_note →
embed_chunks → save_chunks → find_related → [synthesize → user_review] → create_concepts →
link_synthesis) with skip_review=True. The flashcard and quiz nodes are left off: they create study
cards, not anything chat retrieval reads, and they are the most expensive part of ingestion.

After the notes, communities are computed once (Louvain + LLM summaries), the same three calls the
API makes after an ingest (backend/routers/ingest_v2.py, _recompute_communities).

Resumable: notes already ingested are recorded in data/ingested.json and skipped.

    python eval/graphrag/ingest_corpus.py --questions 10    # paragraphs of the first 10 questions
    python eval/graphrag/ingest_corpus.py                   # all
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
import uuid

import _env

_env.setup()

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402

from backend import telemetry  # noqa: E402
from backend.agents.states import IngestionState  # noqa: E402
import importlib  # noqa: E402

# backend.graphs re-exports the compiled graph under the module's own name, so fetch the module itself.
ig = importlib.import_module("backend.graphs.ingestion_graph")



def build_eval_graph():
    """The product graph (ingestion_graph.create_ingestion_graph) minus flashcards and quizzes."""
    b = StateGraph(IngestionState)
    for name, fn in (("parse", ig.parse_node), ("chunk", ig.chunk_node), ("extract_concepts", ig.extract_concepts_node),
                     ("store_note", ig.store_note_node), ("embed_chunks", ig.embed_node),
                     ("save_chunks", ig.save_chunks_node), ("find_related", ig.find_related_node),
                     ("synthesize", ig.synthesize_node), ("user_review", ig.user_review_node),
                     ("create_concepts", ig.create_concepts_node), ("link_synthesis", ig.link_synthesis_node)):
        b.add_node(name, fn)
    b.add_edge(START, "parse")
    b.add_edge("parse", "chunk")
    b.add_edge("chunk", "extract_concepts")
    b.add_conditional_edges("extract_concepts", ig.route_after_extract_concepts, {"store_note": "store_note", "end": END})
    b.add_edge("store_note", "embed_chunks")
    b.add_edge("embed_chunks", "save_chunks")
    b.add_edge("save_chunks", "find_related")
    b.add_conditional_edges("find_related", ig.route_after_find_related,
                            {"synthesize": "synthesize", "create_concepts": "create_concepts"})
    b.add_edge("synthesize", "user_review")
    b.add_conditional_edges("user_review", ig.route_after_user_review, {"create_concepts": "create_concepts", "end": END})
    b.add_edge("create_concepts", "link_synthesis")
    b.add_edge("link_synthesis", END)
    return b.compile(checkpointer=MemorySaver())


def initial_state(user_id: str, title: str, text: str) -> dict:
    thread_id = str(uuid.uuid4())
    return {
        "thread_id": thread_id, "user_id": user_id, "raw_content": text, "title": title, "note_id": None,
        "skip_review": True, "content_hash": hashlib.sha256(text.encode()).hexdigest(), "resource_type": None,
        "extracted_concepts": [], "related_concepts": [], "needs_synthesis": False, "synthesis_completed": False,
        "created_concept_ids": [], "concept_name_to_id": {}, "term_card_ids": [], "quiz_ids": [],
        "processing_metadata": {"progress": {"current_node": "parse", "completed_nodes": [], "failed_batches": 0,
                                             "concepts_extracted": 0, "chunk_save_total": 0, "chunk_save_done": 0,
                                             "chunk_save_stage": None, "chunk_save_error": None}},
        "status_reason": None, "next_action": None, "error": None,
    }


def llm_totals() -> dict:
    return telemetry.snapshot()["llm"]


def diff_totals(after: dict, before: dict) -> dict:
    out = {}
    for model, t in after.items():
        b = before.get(model, {})
        d = {k: t[k] - b.get(k, 0) for k in t}
        if any(d.values()):
            out[model] = d
    return out


async def chunk_count(pg, note_id: str | None) -> tuple[int, int]:
    """(child chunks, child chunks with an embedding). embed_node saves chunks even when embedding failed."""
    if not note_id:
        return 0, 0
    rows = await pg.execute_query(
        "SELECT count(*) AS n, count(embedding) AS v FROM chunks WHERE note_id = CAST(:id AS uuid) AND chunk_level = 'child'",
        {"id": note_id})
    return (int(rows[0]["n"]), int(rows[0]["v"])) if rows else (0, 0)


async def purge_unfinished(pg, user_id: str, log: dict) -> int:
    """Delete this eval user's notes that aren't recorded as completed, before they are re-ingested.

    A retried note gets a new note id, so without this its partial first attempt (chunks, some without
    vectors, and its NoteSource) would stay in the graph next to the retry and skew retrieval. Concepts
    are kept: the retry merges into them by name. Deleting a note cascades to its chunks and
    propositions. Refuses to run outside the eval database or for a non-eval user.
    """
    import os

    from backend.db.neo4j_client import get_neo4j_client

    if "graphrecall_eval" not in os.environ.get("DATABASE_URL", ""):
        raise SystemExit("purge_unfinished: DATABASE_URL is not the graphrecall_eval database; refusing")
    owner = await pg.execute_query("SELECT email FROM users WHERE id = CAST(:u AS uuid)", {"u": user_id})
    if not owner or not owner[0]["email"].startswith("graphrag-eval+"):
        raise SystemExit("purge_unfinished: not an eval user; refusing")
    done = {v["note_id"] for v in log["notes"].values() if v.get("status") == "completed" and v.get("note_id")}
    rows = await pg.execute_query("SELECT id::text AS id FROM notes WHERE user_id = CAST(:u AS uuid)", {"u": user_id})
    stale = [r["id"] for r in rows if r["id"] not in done]
    if not stale:
        return 0
    neo4j = await get_neo4j_client()
    await neo4j.execute_query("MATCH (n:NoteSource {user_id: $u}) WHERE n.id IN $ids DETACH DELETE n",
                              {"u": user_id, "ids": stale})
    # Concepts that only the purged attempts explained are now orphans; the retry recreates whatever
    # it extracts. (Before this run every eval concept had an EXPLAINS edge, so nothing else matches.)
    await neo4j.execute_query("MATCH (c:Concept {user_id: $u}) WHERE NOT (c)-[:EXPLAINS]-() DETACH DELETE c",
                              {"u": user_id})
    for nid in stale:
        await pg.execute_update("DELETE FROM notes WHERE id = CAST(:n AS uuid) AND user_id = CAST(:u AS uuid)",
                                {"n": nid, "u": user_id})
    for v in log["notes"].values():
        if v.get("note_id") in stale:
            v["note_id"], v["purged_partial"] = None, True
    return len(stale)


async def main(dataset: str, upto: int | None, communities_only: bool, limit: int | None, skip_communities: bool) -> None:
    from backend.db.postgres_client import get_postgres_client

    _env.throttle_llm()
    pg = await get_postgres_client()
    await pg.initialize_schema()
    user_id = await _env.eval_user_id(dataset)
    corpus_path = _env.DATA / ("grb/corpus.jsonl" if dataset == "grb" else "corpus.jsonl")
    log_path = _env.DATA / f"ingested_{_env.run_key(dataset)}.json"

    corpus = [json.loads(l) for l in corpus_path.open()]
    corpus = corpus[:upto] if upto else corpus

    log = json.loads(log_path.read_text()) if log_path.exists() else {"user_id": user_id, "models": _env.models(), "notes": {}}
    graph = build_eval_graph()

    if not communities_only:
        purged = await purge_unfinished(pg, user_id, log)
        if purged:
            log_path.write_text(json.dumps(log, indent=1, ensure_ascii=False))
            print(f"removed {purged} partially ingested note(s) before retrying them", flush=True)
        todo = [p for p in corpus if log["notes"].get(p["key"], {}).get("status") != "completed"]
        todo = todo[:limit] if limit else todo
        print(f"{len(corpus)} notes in scope; {len(todo)} to ingest", flush=True)
        for i, p in enumerate(todo, 1):
            k = p["key"]
            before, t0, embed_err_before = llm_totals(), time.time(), _env.EMBED_ERRORS["count"]
            try:
                res = await graph.ainvoke(initial_state(user_id, p["title"], p["text"]),
                                          {"configurable": {"thread_id": str(uuid.uuid4())}})
                rec = {"note_id": str(res.get("note_id")) if res.get("note_id") else None,
                       "concepts": len([c for c in res.get("created_concept_ids", []) if c]),
                       "relationships": (res.get("processing_metadata") or {}).get("relationships_created", 0),
                       "error": (str(res.get("error"))[:300] if res.get("error") else None)}
            except Exception as e:  # noqa: BLE001
                rec = {"note_id": None, "concepts": 0, "error": f"{type(e).__name__}: {e}"[:300]}
            rec.update(title=p["title"], order=p.get("order"), seconds=round(time.time() - t0, 1),
                       llm=diff_totals(llm_totals(), before))
            rec["chunks"], rec["chunks_embedded"] = await chunk_count(pg, rec["note_id"])
            llm_errors = sum(v.get("errors", 0) for v in rec["llm"].values())
            embed_errors = _env.EMBED_ERRORS["count"] - embed_err_before
            # "completed" only if every chunk is searchable (has a vector), the graph got concepts, and
            # no chat or embedding call failed along the way (failures inside nodes are swallowed, so
            # a quota hit would otherwise leave a thinner graph that still looks ingested).
            rec["status"] = ("completed" if rec["chunks"] > 0 and rec["chunks_embedded"] == rec["chunks"]
                             and rec["concepts"] > 0 and not rec["error"] and not llm_errors and not embed_errors
                             else "incomplete")
            rec["llm_errors"], rec["embed_errors"] = llm_errors, embed_errors
            log["notes"][k] = rec
            log_path.write_text(json.dumps(log, indent=1, ensure_ascii=False))
            calls = sum(v["calls"] for v in rec["llm"].values())
            print(f"[{i}/{len(todo)}] {rec['status']:10s} {rec['seconds']:5.1f}s calls={calls} err={llm_errors} "
                  f"chunks={rec['chunks_embedded']}/{rec['chunks']} concepts={rec['concepts']} {p['title'][:40]} {rec.get('error') or ''}", flush=True)
            if "RESOURCE_EXHAUSTED" in (rec.get("error") or "") or _env.EMBED_ERRORS["daily_quota"]:
                print("Gemini quota exhausted (daily embedding cap or chat quota); stopping. Rerun to resume.", flush=True)
                return

    if skip_communities:
        return
    from backend.services.community_service import CommunityService

    before, t0 = llm_totals(), time.time()
    svc = CommunityService()
    comms = await svc.compute_communities(user_id)
    await svc.persist_communities(user_id, comms)
    await svc.generate_community_summaries(user_id)
    log["communities"] = {"count": len(comms), "seconds": round(time.time() - t0, 1),
                          "llm": diff_totals(llm_totals(), before), "after_notes": len(log["notes"])}
    log_path.write_text(json.dumps(log, indent=1, ensure_ascii=False))
    print("communities:", log["communities"], flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", choices=["grb", "musique"], default="grb")
    ap.add_argument("--upto", type=int, default=None, help="only the first N corpus notes (the slice)")
    ap.add_argument("--communities-only", action="store_true")
    ap.add_argument("--skip-communities", action="store_true")
    ap.add_argument("--limit", type=int, default=None, help="ingest at most N notes this run")
    a = ap.parse_args()
    asyncio.run(main(a.dataset, a.upto, a.communities_only, a.limit, a.skip_communities))
