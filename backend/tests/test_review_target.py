"""Feed reviews must update the *concept's* schedule, not the card's id.

Unit tests use fakes; the SQL test runs against a real Postgres when
TEST_POSTGRES_URL is set (e.g. postgresql://postgres@localhost:5439/grtest).
The module is loaded by file path so the test doesn't import the whole backend.
"""

import asyncio
import importlib.util
import os
import uuid
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "review_target", Path(__file__).resolve().parents[1] / "services" / "review_target.py"
)
rt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rt)


class FakePG:
    def __init__(self, rows):  # rows: {(table, id, user): concept_id}
        self.rows = rows

    async def execute_query(self, sql, params):
        table = "quizzes" if "FROM quizzes" in sql else "flashcards"
        cid = self.rows.get((table, params["id"], params["uid"]))
        return [{"concept_id": cid}] if cid else []


class FakeNeo:
    def __init__(self, concepts):  # {(id, user)}
        self.concepts = concepts

    async def execute_query(self, cypher, params):
        return [{"id": params["id"]}] if (params["id"], params["uid"]) in self.concepts else []


def run(coro):
    return asyncio.run(coro)


def test_explicit_concept_id_wins():
    pg = FakePG({("quizzes", "q1", "u"): "other"})
    assert run(rt.resolve_review_concept(pg, None, "u", "q1", "c-explicit")) == ("c-explicit", "explicit")


def test_quiz_and_flashcard_ids_map_to_their_concept():
    pg = FakePG({("quizzes", "q1", "u"): "c-quiz", ("flashcards", "f1", "u"): "c-card"})
    assert run(rt.resolve_review_concept(pg, None, "u", "q1")) == ("c-quiz", "quiz")
    assert run(rt.resolve_review_concept(pg, None, "u", "f1")) == ("c-card", "flashcard")


def test_legacy_clients_sending_a_concept_id_still_work():
    assert run(rt.resolve_review_concept(FakePG({}), FakeNeo({("c9", "u")}), "u", "c9")) == ("c9", "concept")


def test_unknown_ids_are_rejected_not_scheduled():
    with pytest.raises(rt.UnresolvableReviewTarget):
        run(rt.resolve_review_concept(FakePG({}), FakeNeo(set()), "u", str(uuid.uuid4())))


def test_other_users_rows_do_not_resolve():
    pg = FakePG({("quizzes", "q1", "someone-else"): "c-quiz"})
    with pytest.raises(rt.UnresolvableReviewTarget):
        run(rt.resolve_review_concept(pg, None, "u", "q1"))


PG_URL = os.getenv("TEST_POSTGRES_URL")


@pytest.mark.skipif(not PG_URL, reason="TEST_POSTGRES_URL not set")
def test_sql_against_postgres_with_uuid_ids():
    """Real schema shape: uuid primary keys; a non-uuid item id must not raise."""
    import psycopg
    from psycopg.rows import dict_row

    class PG:
        async def execute_query(self, sql, params):
            q = sql.replace(":id", "%(id)s").replace(":uid", "%(uid)s")
            async with await psycopg.AsyncConnection.connect(PG_URL, row_factory=dict_row) as conn:
                cur = await conn.execute(q, params)
                return await cur.fetchall()

    quiz_id, card_id, user = uuid.uuid4(), uuid.uuid4(), str(uuid.uuid4())
    with psycopg.connect(PG_URL, autocommit=True) as conn:
        for t in ("quizzes", "flashcards"):
            conn.execute(f"CREATE TABLE IF NOT EXISTS {t} (id uuid PRIMARY KEY, user_id text, concept_id text)")
        conn.execute("INSERT INTO quizzes VALUES (%s, %s, 'c-q')", (quiz_id, user))
        conn.execute("INSERT INTO flashcards VALUES (%s, %s, 'c-f')", (card_id, user))
    pg = PG()
    assert run(rt.resolve_review_concept(pg, None, user, str(quiz_id))) == ("c-q", "quiz")
    assert run(rt.resolve_review_concept(pg, None, user, str(card_id))) == ("c-f", "flashcard")
    with pytest.raises(rt.UnresolvableReviewTarget):
        run(rt.resolve_review_concept(pg, None, user, "demo-transformer-mcq-123"))   # not a uuid
