"""HITL state must survive an API restart.

Runs a tiny graph with the same shape as ingestion (work → interrupt() review →
commit) in one Python process, stops at the interrupt, then resumes the same
thread_id from a *fresh* process — which is what a restart of the API looks like.

Needs a real Postgres: set TEST_POSTGRES_URL (e.g. postgresql://postgres@localhost:5439/grtest).
The checkpointer module is loaded by file path so this test does not import the
whole backend (LLM clients, Neo4j, …).
"""

import json
import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

PG_URL = os.getenv("TEST_POSTGRES_URL")
CHECKPOINTER_PY = Path(__file__).resolve().parents[1] / "graphs" / "checkpointer.py"

pytestmark = pytest.mark.skipif(not PG_URL, reason="TEST_POSTGRES_URL not set")

SCRIPT = textwrap.dedent(
    """
    import asyncio, importlib.util, json, sys
    from typing import TypedDict
    from langgraph.graph import StateGraph, START, END
    from langgraph.types import interrupt, Command

    spec = importlib.util.spec_from_file_location("checkpointer", sys.argv[1])
    cp = importlib.util.module_from_spec(spec); spec.loader.exec_module(cp)

    class S(TypedDict, total=False):
        concepts: list
        approved: bool
        committed: bool

    def extract(state):
        return {"concepts": ["eigenvector", "eigenvalue"]}

    def review(state):
        decision = interrupt({"concepts": state["concepts"]})
        return {"approved": bool(decision.get("approved"))}

    def commit(state):
        return {"committed": state.get("approved", False)}

    b = StateGraph(S)
    b.add_node("extract", extract); b.add_node("review", review); b.add_node("commit", commit)
    b.add_edge(START, "extract"); b.add_edge("extract", "review"); b.add_edge("review", "commit"); b.add_edge("commit", END)
    graph = b.compile(checkpointer=cp.get_checkpointer())   # compiled before the pool opens, like the app

    async def main(phase, thread_id, lazy):
        # lazy: behave like a standalone script that never calls open_checkpointer()
        backend = cp.checkpointer_status()["backend"] if lazy else await cp.open_checkpointer()
        cfg = {"configurable": {"thread_id": thread_id}}
        if phase == "start":
            out = await graph.ainvoke({}, cfg)
            snap = await graph.aget_state(cfg)
            print(json.dumps({"backend": backend, "next": list(snap.next), "interrupted": "__interrupt__" in out}))
        else:
            snap = await graph.aget_state(cfg)
            if not snap.next:
                print(json.dumps({"backend": backend, "found": False})); await cp.close_checkpointer(); return
            out = await graph.ainvoke(Command(resume={"approved": True}), cfg)
            print(json.dumps({"backend": backend, "found": True, "committed": out.get("committed"), "concepts": out.get("concepts")}))
        await cp.close_checkpointer()

    asyncio.run(main(sys.argv[2], sys.argv[3], sys.argv[4] == "lazy"))
    """
)


def _run(phase: str, thread_id: str, mode: str, lazy: bool = False) -> dict:
    env = {**os.environ, "DATABASE_URL": PG_URL, "CHECKPOINTER": mode}
    proc = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(CHECKPOINTER_PY), phase, thread_id, "lazy" if lazy else "explicit"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_interrupt_survives_restart_with_postgres():
    thread_id = f"test-{uuid.uuid4()}"
    first = _run("start", thread_id, "postgres")
    assert first == {"backend": "postgres", "next": ["review"], "interrupted": True}

    second = _run("resume", thread_id, "postgres")  # new process = restarted API
    assert second["found"] is True
    assert second["committed"] is True
    assert second["concepts"] == ["eigenvector", "eigenvalue"]


def test_scripts_without_lifespan_open_the_pool_themselves():
    """backend/scripts/seed_content.py and scripts/ingest_book.py never call open_checkpointer()."""
    thread_id = f"test-{uuid.uuid4()}"
    first = _run("start", thread_id, "postgres", lazy=True)
    assert first["next"] == ["review"] and first["interrupted"] is True
    second = _run("resume", thread_id, "postgres", lazy=True)
    assert second["found"] is True and second["committed"] is True


def test_memory_backend_loses_state_on_restart():
    """Control: the old behaviour. Proves the test above is measuring persistence."""
    thread_id = f"test-{uuid.uuid4()}"
    first = _run("start", thread_id, "memory")
    assert first["backend"] == "memory" and first["next"] == ["review"]
    assert _run("resume", thread_id, "memory") == {"backend": "memory", "found": False}


def test_sqlalchemy_style_url_is_normalised():
    import importlib.util

    spec = importlib.util.spec_from_file_location("checkpointer_under_test", CHECKPOINTER_PY)
    cp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cp)
    assert cp._psycopg_conninfo("postgresql+asyncpg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    assert cp._psycopg_conninfo("postgres://u@h/db") == "postgresql://u@h/db"
