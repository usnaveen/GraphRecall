"""Build the local showcase account: a fictional learner (Jordan Avery) with a copy of a real
account's knowledge graph, for screenshots and demo videos.

Why: recording the app on the developer's own account puts their resume, sources and real
review history on screen. The showcase learner has the same graph (so every screen looks like
the real product), but nothing personal: no notes, no sources, no figures from books, and a
made-up record of what they are strong and weak at.

What it does (all writes scoped to the showcase user, never the source):
- Neo4j: copies every Concept and the links between them, with new ids (concept ids are unique
  across users). NoteSource nodes are not copied.
- Postgres: copies flashcards and quizzes with their concept ids remapped and every link to a
  note or source URL removed.
- Seeds review scores by subject with a fixed RNG: language models and deep learning strong,
  algorithms mixed, MLOps / systems weak. Scores drive both the Graph's mastery colours and the
  knowledge map (strong / shaky need a tested score; everything in the graph counts as studied).
- Seeds two weeks of review activity so Profile has a streak and a week chart.

Local DEBUG backends only: refuses non-local databases. Sign in as the learner with Bearer
`showcase-token` (backend/auth/google_oauth.py). Re-running replaces the showcase data.

    PYTHONPATH=. .venv/bin/python scripts/showcase_account.py --source-user <uuid> [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import random
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from neo4j import GraphDatabase
from sqlalchemy import create_engine, text

SHOWCASE_GOOGLE_ID = "showcase-google-id"
SHOWCASE_EMAIL = "jordan.avery@example.com"
SHOWCASE_NAME = "Jordan Avery"
ID_NAMESPACE = uuid.UUID("7d6c3f0e-9a41-4f7b-8d1e-5b0c2a9e4f11")

# Per-user tables the showcase may hold; purged before every run (child tables first).
PURGE = ("study_sessions", "knowledge_evidence", "proficiency_scores", "flashcards", "quizzes",
         "daily_stats", "user_skills", "user_resumes", "saved_responses", "later_items")

# Subject groups: (probability a concept has been reviewed, mean score, spread).
STRONG = {"Natural Language Processing", "Deep Learning", "Large Language Models", "Information Retrieval",
          "Linear Algebra", "Probability and Statistics", "Statistics", "Statistics and Machine Learning",
          "Mathematics", "Multimodal Machine Learning", "Computer Vision"}
WEAK = {"MLOps", "Machine Learning Engineering", "Data Engineering", "Distributed Computing",
        "Distributed Machine Learning", "Model Optimization", "Inference Optimization",
        "High-Performance Computing", "Software Engineering", "Database Systems", "Software Design Patterns"}
PROFILE = {"strong": (0.65, 0.86, 0.07), "mixed": (0.5, 0.62, 0.14), "weak": (0.85, 0.3, 0.12)}


def group(domain: str | None) -> str:
    if domain in STRONG:
        return "strong"
    if domain in WEAK:
        return "weak"
    return "mixed"


def due_offset(rng: random.Random) -> int:
    """Days until a card is due: a handful overdue, a couple of dozen today, the rest spread out."""
    r = rng.random()
    return -1 if r < 0.03 else 0 if r < 0.1 else rng.randint(1, 12)


def new_id(old: str) -> str:
    return str(uuid.uuid5(ID_NAMESPACE, f"showcase:{old}"))


def _local(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host in {"localhost", "127.0.0.1", "::1"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-user", required=True, help="account whose graph is copied (read only)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL", f"postgresql://{os.environ.get('USER')}@localhost:5432/graphrecall")
    db_url = re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql+psycopg://", db_url)
    neo_url = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    if not (_local(db_url) and _local(neo_url)):
        raise SystemExit("refusing: showcase data is for local databases only")

    pg = create_engine(db_url)
    neo = GraphDatabase.driver(neo_url, auth=(os.environ.get("NEO4J_USER", "neo4j"),
                                              os.environ.get("NEO4J_PASSWORD", "graphrecall-dev")))
    src = str(uuid.UUID(args.source_user))
    rng = random.Random(args.seed)
    now = datetime.now(timezone.utc)

    with pg.begin() as c:
        row = c.execute(text("SELECT id FROM users WHERE google_id = :g"), {"g": SHOWCASE_GOOGLE_ID}).first()
        if row is None and not args.dry_run:
            row = c.execute(text("INSERT INTO users (google_id, email, name, last_login) VALUES (:g, :e, :n, NOW()) "
                                 "RETURNING id"), {"g": SHOWCASE_GOOGLE_ID, "e": SHOWCASE_EMAIL, "n": SHOWCASE_NAME}).first()
        dst = str(row[0]) if row else "00000000-0000-0000-0000-000000000000"
    if dst == src:
        raise SystemExit("refusing: the source account is the showcase account")
    print(f"source {src}  ->  showcase {dst} ({SHOWCASE_NAME})")

    # ---- read the source graph -------------------------------------------------------------
    with neo.session() as s:
        concepts = s.run("MATCH (c:Concept {user_id: $u}) RETURN c.id AS id, properties(c) AS p", u=src).data()
        links = s.run("MATCH (a:Concept {user_id: $u})-[r]->(b:Concept {user_id: $u}) "
                      "RETURN a.id AS a, b.id AS b, type(r) AS t, properties(r) AS p", u=src).data()
    ids = {r["id"]: new_id(r["id"]) for r in concepts}
    print(f"graph: {len(concepts)} concepts, {len(links)} links "
          f"({dict(Counter(l['t'] for l in links))})")

    with pg.connect() as c:
        cards = c.execute(text("SELECT concept_id, front_content, back_content, difficulty, source FROM flashcards "
                               "WHERE user_id = CAST(:u AS uuid)"), {"u": src}).mappings().all()
        quizzes = c.execute(text("SELECT concept_id, question_text, question_type, options_json, correct_answer, "
                                 "explanation, source, language, initial_code FROM quizzes WHERE user_id = CAST(:u AS uuid)"),
                            {"u": src}).mappings().all()
    cards = [r for r in cards if r["concept_id"] in ids]
    quizzes = [r for r in quizzes if r["concept_id"] in ids]

    # ---- made-up record: who is strong at what ---------------------------------------------
    scores = []
    for r in concepts:
        p_test, mean, spread = PROFILE[group(r["p"].get("domain"))]
        if rng.random() > p_test:
            continue
        score = min(0.98, max(0.05, rng.gauss(mean, spread)))
        reviews = rng.randint(2, 8)
        last = now - timedelta(days=rng.randint(0, 12), hours=rng.randint(0, 20))
        due = now + timedelta(days=due_offset(rng))
        scores.append({"c": ids[r["id"]], "s": round(score, 2), "n": reviews, "last": last, "due": due,
                       "iv": max(1, (due - last).days), "streak": rng.randint(0, 4)})
    by_group = Counter(group(r["p"].get("domain")) for r in concepts)
    print(f"subjects: {dict(by_group)}; reviewed concepts: {len(scores)}")

    # Two weeks of review activity, a 9-day streak ending today.
    tested = [s["c"] for s in scores]
    activity = []
    for day in range(0, 14):
        if day >= 9 and rng.random() < 0.5:
            continue
        for _ in range(rng.randint(6, 16) if day else 7):
            at = (now - timedelta(days=day)).replace(hour=rng.randint(7, 22), minute=rng.randint(0, 59))
            if at > now:
                at = now - timedelta(minutes=rng.randint(5, 300))
            good = rng.random() < 0.78
            activity.append({"c": rng.choice(tested), "at": at, "ok": good,
                             "kind": "review:good" if good else "review:again", "rating": 3 if good else 1})

    if args.dry_run:
        print(f"dry run: would write {len(cards)} flashcards, {len(quizzes)} quizzes, "
              f"{len(scores)} scores, {len(activity)} reviews")
        return

    # ---- write (showcase user only) --------------------------------------------------------
    with neo.session() as s:
        s.run("MATCH (n {user_id: $u}) DETACH DELETE n", u=dst)
        # New ids are set before the node exists: copying the old id first trips the uniqueness constraint.
        rows = [{**r["p"], "id": ids[r["id"]], "user_id": dst} for r in concepts]
        for i in range(0, len(rows), 500):
            s.run("UNWIND $rows AS props CREATE (n:Concept) SET n = props", rows=rows[i:i + 500])
        for rel_type in sorted({l["t"] for l in links}):
            if not re.fullmatch(r"[A-Z_]+", rel_type):
                raise SystemExit(f"unexpected relationship type {rel_type!r}")
            batch = [{"a": ids[l["a"]], "b": ids[l["b"]],
                      "p": {**(l["p"] or {}), **({"user_id": dst} if "user_id" in (l["p"] or {}) else {})}}
                     for l in links if l["t"] == rel_type]
            for i in range(0, len(batch), 1000):
                s.run(f"UNWIND $rows AS row MATCH (a:Concept {{id: row.a, user_id: $dst}}), "
                      f"(b:Concept {{id: row.b, user_id: $dst}}) CREATE (a)-[r:{rel_type}]->(b) SET r = row.p",
                      rows=batch[i:i + 1000], dst=dst)

    with pg.begin() as c:
        for t in PURGE:
            c.execute(text(f"DELETE FROM {t} WHERE user_id = CAST(:u AS uuid)"), {"u": dst})
        for r in cards:
            c.execute(text("INSERT INTO flashcards (user_id, concept_id, front_content, back_content, difficulty, "
                           "source_note_ids, source) VALUES (CAST(:u AS uuid), :c, :f, :b, :d, '{}', :s)"),
                      {"u": dst, "c": ids[r["concept_id"]], "f": r["front_content"], "b": r["back_content"],
                       "d": r["difficulty"], "s": r["source"]})
        for r in quizzes:
            c.execute(text("INSERT INTO quizzes (user_id, concept_id, question_text, question_type, options_json, "
                           "correct_answer, explanation, source, language, initial_code) VALUES (CAST(:u AS uuid), :c, "
                           ":q, :t, CAST(:o AS jsonb), :a, :e, :s, :l, :i)"),
                      {"u": dst, "c": ids[r["concept_id"]], "q": r["question_text"], "t": r["question_type"],
                       "o": __import__("json").dumps(r["options_json"]) if r["options_json"] is not None else None,
                       "a": r["correct_answer"], "e": r["explanation"], "s": r["source"], "l": r["language"],
                       "i": r["initial_code"]})
        for s_ in scores:
            c.execute(text("INSERT INTO proficiency_scores (user_id, concept_id, score, last_reviewed, next_review_due, "
                           "next_review, total_reviews, repetition_count, interval_days, easiness_factor, streak_count, "
                           "correct_streak) VALUES (CAST(:u AS uuid), :c, :s, :last, :due, :due, :n, :n, :iv, 2.5, "
                           ":streak, :streak)"), {"u": dst, **s_})
        for a in activity:
            c.execute(text("INSERT INTO study_sessions (user_id, session_type, start_time, concept_id, item_type, "
                           "interaction_type, is_correct, reviewed_at, rating) VALUES (CAST(:u AS uuid), 'quiz', :at, :c, "
                           "'flashcard', :kind, :ok, :at, :rating)"), {"u": dst, **a})
    print(f"wrote {len(cards)} flashcards, {len(quizzes)} quizzes, {len(scores)} scores, {len(activity)} reviews")
    neo.close()


if __name__ == "__main__":
    main()
