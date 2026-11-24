"""Account deletion against real Postgres (a scratch database, migrated) and the local Neo4j.

Two users each get a note, a chunk with an image, an upload and a concept. Deleting one account must
remove all of its rows, nodes and files and leave the other user's untouched. Skipped when either
database is unreachable.
"""

import os
import uuid

import pytest

pytestmark = pytest.mark.asyncio


class FakeStorage:
    def __init__(self):
        self.deleted = []

    async def delete_file(self, url, *, owner_id):
        self.deleted.append(url)
        return True

    async def delete_user_prefix(self, owner_id):
        self.prefixes = getattr(self, "prefixes", []) + [owner_id]
        return 0


@pytest.fixture
async def stores(scratch_db):
    from neo4j import AsyncGraphDatabase

    from backend.db import migrate as M
    from backend.db.neo4j_client import Neo4jClient

    pg, _ = scratch_db
    await M.migrate(pg)
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    auth = (os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", ""))
    try:
        d = AsyncGraphDatabase.driver(uri, auth=auth)
        await d.verify_connectivity()
        await d.close()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"no Neo4j: {e}")
    neo = Neo4jClient()
    await neo.initialize()
    yield pg, neo
    await neo.close()


async def _make_user(pg, neo, tag):
    email = f"del-test-{tag}-{uuid.uuid4().hex[:6]}@example.invalid"
    await pg.execute_update("INSERT INTO users (email, name) VALUES (:e, :n)", {"e": email, "n": tag})
    uid = str((await pg.execute_query("SELECT id FROM users WHERE email = :e", {"e": email}))[0]["id"])
    nid = str(uuid.uuid4())
    await pg.execute_update("INSERT INTO notes (id, user_id, title, content_text) VALUES (CAST(:n AS uuid), CAST(:u AS uuid), :t, 'x')",
                            {"n": nid, "u": uid, "t": f"note {tag}"})
    await pg.execute_update("INSERT INTO chunks (id, note_id, content, chunk_index, chunk_level, images) VALUES "
                            "(uuid_generate_v4(), CAST(:n AS uuid), 'c', 0, 'parent', CAST(:im AS jsonb))",
                            {"n": nid, "im": f'[{{"url": "https://files.example/{tag}.png"}}]'})
    await pg.execute_update("INSERT INTO user_uploads (user_id, file_url) VALUES (CAST(:u AS uuid), :f)",
                            {"u": uid, "f": f"https://files.example/upload-{tag}.pdf"})
    await neo.execute_query("CREATE (:Concept {id: $id, user_id: $u, name: $n})", {"id": str(uuid.uuid4()), "u": uid, "n": f"C {tag}"})
    await neo.execute_query("CREATE (:NoteSource {id: $id, user_id: $u})", {"id": nid, "u": uid})
    return uid


async def _counts(pg, neo, uid):
    rows = await pg.execute_query(
        "SELECT (SELECT count(*) FROM users WHERE id = CAST(:u AS uuid)) AS users,"
        " (SELECT count(*) FROM notes WHERE user_id = CAST(:u AS uuid)) AS notes,"
        " (SELECT count(*) FROM user_uploads WHERE user_id = CAST(:u AS uuid)) AS uploads", {"u": uid})
    nodes = await neo.execute_query("MATCH (n {user_id: $u}) RETURN count(n) AS n", {"u": uid})
    return {**rows[0], "nodes": nodes[0]["n"]}


async def test_delete_account_removes_everything_and_only_that_user(stores):
    from backend.services.account_deletion import delete_user_data

    pg, neo = stores
    a, b = await _make_user(pg, neo, "a"), await _make_user(pg, neo, "b")
    try:
        storage = FakeStorage()
        out = await delete_user_data(a, delete_account=True, pg=pg, neo4j=neo, storage=storage)
        assert await _counts(pg, neo, a) == {"users": 0, "notes": 0, "uploads": 0, "nodes": 0}
        assert await _counts(pg, neo, b) == {"users": 1, "notes": 1, "uploads": 1, "nodes": 2}
        assert sorted(storage.deleted) == ["https://files.example/a.png", "https://files.example/upload-a.pdf"]
        assert out["neo4j_nodes"] == 2 and out["account"] == 1
        # chunks went with the note (cascade): none left for user a
        left = await pg.execute_query("SELECT count(*) AS n FROM chunks WHERE images::text LIKE '%/a.png%'")
        assert left[0]["n"] == 0
    finally:
        await neo.execute_query("MATCH (n) WHERE n.user_id IN [$a, $b] DETACH DELETE n", {"a": a, "b": b})


async def _checkpoint_tables(pg):
    # The real ones are created by AsyncPostgresSaver.setup(); deletion only needs thread_id.
    for t in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
        await pg.execute_update(f"CREATE TABLE IF NOT EXISTS {t} (thread_id TEXT NOT NULL, payload TEXT)")


async def test_delete_account_removes_checkpoints_and_upload_prefix(stores):
    from backend.services.account_deletion import delete_user_data

    pg, neo = stores
    await _checkpoint_tables(pg)
    a, b = await _make_user(pg, neo, "ca"), await _make_user(pg, neo, "cb")
    conv = await pg.execute_insert(
        "INSERT INTO chat_conversations (user_id, title) VALUES (CAST(:u AS uuid), 't') RETURNING id", {"u": a})
    threads_a = [f"chat:{a}:{conv}", f"ingest:{a}:{uuid.uuid4()}", str(conv)]  # last: pre-namespacing id
    threads_b = [f"chat:{b}:x", f"ingest:{b}:y"]
    for t in threads_a + threads_b:
        for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
            await pg.execute_update(f"INSERT INTO {table} (thread_id, payload) VALUES (:t, 'note text')", {"t": t})
    try:
        storage = FakeStorage()
        out = await delete_user_data(a, delete_account=True, pg=pg, neo4j=neo, storage=storage)
        assert out["checkpoint_threads"] == 3
        for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
            left = {r["thread_id"] for r in await pg.execute_query(f"SELECT thread_id FROM {table}")}
            assert not left & set(threads_a) and set(threads_b) <= left
        assert storage.prefixes == [a]  # every object under uploads/{a}/, referenced or not
    finally:
        await neo.execute_query("MATCH (n) WHERE n.user_id IN [$a, $b] DETACH DELETE n", {"a": a, "b": b})


async def test_note_deletion_removes_only_its_orphan_concepts(stores):
    from backend.routers.notes import delete_note_graph

    pg, neo = stores
    u, other = str(uuid.uuid4()), str(uuid.uuid4())
    n1, n2 = str(uuid.uuid4()), str(uuid.uuid4())
    await neo.execute_query(
        """
        CREATE (s1:NoteSource {id: $n1, user_id: $u}), (s2:NoteSource {id: $n2, user_id: $u}),
               (only:Concept {id: 'only-' + $n1, user_id: $u, name: 'only in note 1'}),
               (shared:Concept {id: 'shared-' + $n1, user_id: $u, name: 'in both notes'}),
               (s1)-[:EXPLAINS]->(only), (s1)-[:EXPLAINS]->(shared), (s2)-[:EXPLAINS]->(shared),
               (theirs:Concept {id: 'theirs-' + $n1, user_id: $other, name: 'only in note 1'})
        """, {"n1": n1, "n2": n2, "u": u, "other": other})
    try:
        assert await delete_note_graph(neo, n1, u) == [f"only-{n1}"]
        ids = {r["id"] for r in await neo.execute_query(
            "MATCH (n) WHERE n.user_id IN [$u, $o] RETURN n.id AS id", {"u": u, "o": other})}
        assert ids == {n2, f"shared-{n1}", f"theirs-{n1}"}
    finally:
        await neo.execute_query("MATCH (n) WHERE n.user_id IN [$u, $o] DETACH DELETE n", {"u": u, "o": other})


async def test_note_deletion_removes_study_rows_of_deleted_concepts(stores):
    from backend.routers.notes import delete_concept_rows

    pg, neo = stores
    a, b = await _make_user(pg, neo, "ra"), await _make_user(pg, neo, "rb")
    try:
        for uid in (a, b):
            for cid in ("gone", "kept"):
                await pg.execute_update(
                    "INSERT INTO flashcards (user_id, concept_id, front_content, back_content) "
                    "VALUES (CAST(:u AS uuid), :c, 'q', 'a')", {"u": uid, "c": cid})
        assert await delete_concept_rows(pg, a, ["gone"]) == 1
        left = {(str(r["user_id"]), r["concept_id"]) for r in await pg.execute_query(
            "SELECT user_id, concept_id FROM flashcards WHERE user_id IN (CAST(:a AS uuid), CAST(:b AS uuid))",
            {"a": a, "b": b})}
        assert left == {(a, "kept"), (b, "gone"), (b, "kept")}
    finally:
        await neo.execute_query("MATCH (n) WHERE n.user_id IN [$a, $b] DETACH DELETE n", {"a": a, "b": b})


async def test_purge_keeps_the_account(stores):
    from backend.services.account_deletion import delete_user_data

    pg, neo = stores
    a = await _make_user(pg, neo, "p")
    try:
        await delete_user_data(a, delete_account=False, pg=pg, neo4j=neo, storage=FakeStorage())
        assert await _counts(pg, neo, a) == {"users": 1, "notes": 0, "uploads": 0, "nodes": 0}
    finally:
        await neo.execute_query("MATCH (n {user_id: $a}) DETACH DELETE n", {"a": a})


from backend.tests.test_migrate import scratch_db  # noqa: E402,F401  (shared real-Postgres fixture)
