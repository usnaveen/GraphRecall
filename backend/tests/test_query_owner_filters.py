"""Regression guard for per-user isolation: every SQL/Cypher string in routers and services that reads
or writes user-owned data must filter by its owner, or be on the reviewed allowlist below with the
reason it is safe (typically: the ids come from a query that already filtered by user).

A new unfiltered query fails this test until someone checks it and either adds the owner filter or
documents why it's safe. Found and fixed on 2026-11-21: a concept-title lookup by id alone
(routers/concepts.py), which could read another user's concept title.
"""

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
USER_TABLES = (r"(notes|chunks|flashcards|quizzes|chat_conversations|chat_messages|user_uploads|saved_responses|"
               r"proficiency_scores|study_sessions|propositions|quiz_candidates|generated_content|communities)")

# (file, start of the normalised query): reason it is safe. Keep reasons short and specific.
REVIEWED = {
    ("routers/notes.py", "SELECT id, title, content_text, resource_type, source_url, created_at FROM notes"):
        "WHERE clause built in an f-string, always starts with user_id = :user_id",
    ("routers/notes.py", "SELECT COUNT(*) as count FROM notes"): "same f-string WHERE clause",
    ("routers/uploads.py", "SELECT COUNT(*) as count FROM user_uploads WHERE"): "f-string WHERE clause with user_id",
    ("routers/uploads.py", "UPDATE user_uploads SET"): "f-string SET; WHERE id AND user_id",
    ("routers/chat.py", "SELECT id, role, content, sources_json, created_at FROM chat_messages WHERE conversation_id"):
        "conversation ownership checked earlier in get_conversation",
    ("routers/chat.py", "SELECT role, content FROM chat_messages WHERE conversation_id"):
        "conversation ownership checked earlier in add_message_to_conversation",
    ("routers/chat.py", "UPDATE chat_conversations SET updated_at = NOW() WHERE id = :conversation_id"):
        "conversation ownership checked earlier (add_message_to_conversation, stream_chat)",
    ("routers/chat.py", "UPDATE chat_messages SET is_saved_for_quiz = TRUE WHERE id = :message_id"):
        "message fetched with cc.user_id = :user_id just before",
    ("routers/chat.py", "SELECT title FROM chat_conversations WHERE id = :id"):
        "conversation ownership checked earlier in add_conversation_to_knowledge",
    ("routers/chat.py", "UPDATE chat_conversations SET is_saved_to_knowledge = TRUE"):
        "conversation ownership checked earlier in add_conversation_to_knowledge",
    ("routers/graph3d.py", "SELECT images FROM chunks WHERE note_id = :note_id"):
        "note ids come from the user-filtered concept query",
    ("routers/concepts.py", "SELECT c.id, c.content, c.chunk_level, c.chunk_index"):
        "note ids come from notes filtered by user_id = :uid",
    ("routers/concepts.py", "UPDATE chunks SET embedding = cast(:emb as vector) WHERE id = :id"):
        "chunk ids come from a select filtered by n.user_id",
    ("services/community_service.py", "UPDATE communities SET summary = :summary WHERE id = :id"):
        "community ids come from the user's own communities",
    ("services/feed_service.py", "UPDATE quiz_candidates SET status = 'generated' WHERE id = :id"):
        "candidate ids come from a select filtered by user_id",
}


def unfiltered_queries():
    out = []
    for p in sorted(list((ROOT / "routers").glob("*.py")) + list((ROOT / "services").rglob("*.py"))):
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                s = node.value
                sql = re.search(r"\b(SELECT|UPDATE|DELETE)\b", s) and re.search(rf"\b(FROM|UPDATE|JOIN)\s+{USER_TABLES}\b", s)
                cypher = re.search(r"\bMATCH\b", s) and re.search(r"\{\s*id:\s*\$", s)
                if (sql or cypher) and "user_id" not in s and "uid" not in s:
                    out.append((str(p.relative_to(ROOT)), " ".join(s.split()), node.lineno))
    return out


def test_every_user_data_query_filters_by_owner_or_is_reviewed():
    unreviewed = []
    for f, q, line in unfiltered_queries():
        if not any(f == rf and q.startswith(rq) for rf, rq in REVIEWED):
            unreviewed.append(f"{f}:{line}  {q[:110]}")
    assert not unreviewed, "queries on user data without an owner filter:\n" + "\n".join(unreviewed)
