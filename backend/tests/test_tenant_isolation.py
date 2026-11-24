"""Two users with overlapping concept names, real Postgres + Neo4j: neither can see the other's data.

Behavioural complement to test_query_owner_filters.py (which only scans query strings). User A has a
private concept and note about "Kubernetes Secrets"; user B has "Kubernetes Basics". Every lookup
that matches by name as B must return only B's things. These are the code paths a 2026-11-24 review
found leaking (GR-SEC-01).
"""

import uuid

import pytest

from backend.tests.test_account_deletion import stores  # noqa: F401  (real Postgres + Neo4j fixture)
from backend.tests.test_migrate import scratch_db  # noqa: F401

pytestmark = pytest.mark.asyncio

A_SECRET = "A-PRIVATE-DEFINITION-do-not-leak"


async def _user(pg, neo, tag, concept, definition, note_text):
    email = f"iso-{tag}-{uuid.uuid4().hex[:6]}@example.invalid"
    await pg.execute_update("INSERT INTO users (email, name) VALUES (:e, :n)", {"e": email, "n": tag})
    uid = str((await pg.execute_query("SELECT id FROM users WHERE email = :e", {"e": email}))[0]["id"])
    nid, cid = str(uuid.uuid4()), str(uuid.uuid4())
    await pg.execute_update(
        "INSERT INTO notes (id, user_id, title, content_text) VALUES (CAST(:n AS uuid), CAST(:u AS uuid), :t, :c)",
        {"n": nid, "u": uid, "t": f"{concept} notes", "c": note_text})
    await neo.execute_query("CREATE (:Concept {id: $id, user_id: $u, name: $n, definition: $d})",
                            {"id": cid, "u": uid, "n": concept, "d": definition})
    await neo.execute_query(
        "MATCH (c:Concept {id: $cid}) CREATE (:NoteSource {id: $nid, user_id: $u})-[:EXPLAINS]->(c)",
        {"cid": cid, "nid": nid, "u": uid})
    return {"id": uid, "note": nid, "concept": cid}


@pytest.fixture
async def two_tenants(stores, monkeypatch):  # noqa: F811
    pg, neo = stores
    a = await _user(pg, neo, "a", "Kubernetes Secrets", A_SECRET, "kubernetes secrets are base64 " + A_SECRET)
    b = await _user(pg, neo, "b", "Kubernetes Basics", "pods and nodes", "kubernetes basics for b")

    async def get_pg():
        return pg

    async def get_neo():
        return neo
    from backend.routers import feed
    monkeypatch.setattr(feed, "get_postgres_client", get_pg)
    monkeypatch.setattr(feed, "get_neo4j_client", get_neo)
    yield pg, neo, a, b
    await neo.execute_query("MATCH (n) WHERE n.user_id IN [$a, $b] DETACH DELETE n", {"a": a["id"], "b": b["id"]})


def _leaks(payload, a):
    text = repr(payload)
    return [x for x in (A_SECRET, a["note"], a["concept"]) if x in text]


async def test_resources_by_concept_name_are_scoped(two_tenants):
    from backend.routers.feed import get_resources_for_concept

    _, _, a, b = two_tenants
    out = await get_resources_for_concept("kubernetes", current_user={"id": b["id"]}, resource_type=None)
    assert not _leaks(out, a)
    assert any(r.get("id") == b["concept"] for r in out["resources"])  # B still sees B's own concept


async def test_research_resource_check_is_scoped(two_tenants):
    from backend.agents.research_agent import WebResearchAgent

    pg, neo, a, b = two_tenants
    agent = WebResearchAgent.__new__(WebResearchAgent)
    agent.pg_client, agent.neo4j_client = pg, neo
    _, resources = await agent.check_resources_sufficient("kubernetes", b["id"], min_resources=1)
    assert not _leaks(resources, a)
    assert resources, "B's own note and concept should be found"
