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
               r"proficiency_scores|study_sessions|propositions|quiz_candidates|generated_content|communities|"
               r"intent_decisions|later_items|coding_problems|coding_attempts|knowledge_evidence|user_skills|"
               r"user_profile|user_courses|user_projects|user_resumes|embedding_cache)")

# Every directory that runs queries. agents/, graphs/ and db/ were added on 2026-11-24 after a review
# found unscoped concept lookups there that the routers/services-only scan had missed.
SCANNED_DIRS = ("routers", "services", "agents", "graphs", "db", "agent_v2", "mcp")

# The owner must be *bound to a parameter* (user_id = :x, {user_id: $x}, CAST(:x ...)). The old check
# accepted any mention of "user_id", so a self-join like `ps.user_id = n.user_id` passed with no filter.
OWNER_BOUND = re.compile(r"(user_id|\buid)\s*(=|:|IN)\s*(CAST\(\s*|ANY\(\s*)?[:$]\w+", re.I)

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
    ("routers/graph3d.py", "MATCH (c:Concept) {} RETURN c as concept"):
        "where_clauses list always starts with c.user_id = $user_id",
    ("routers/uploads.py", "SELECT id, user_id, upload_type, file_url"):
        "where_clauses list always starts with user_id = :user_id",
    ("services/ingestion/reembed.py", "UPDATE chunks SET embedding = CAST(:e AS vector) WHERE id = CAST(:id AS uuid)"):
        "chunk ids come from _MISSING_SQL, filtered by n.user_id",
}

# Graph modules whose LLM tools take a topic but no user context. They are unreachable today (no
# router, service or worker imports them); test_unscoped_graphs_stay_unreachable keeps it that way.
UNREACHABLE = ("graphs/content_graph.py", "graphs/quiz_graph.py", "graphs/research_graph.py")


def unfiltered_queries():
    out = []
    files = []
    for d in SCANNED_DIRS:
        files += list((ROOT / d).rglob("*.py"))
    for p in sorted(files):
        try:
            tree = ast.parse(p.read_text())
        except SyntaxError:
            continue
        # f-strings: judge the literal text of the whole f-string, not each fragment, and skip the
        # fragments themselves (otherwise `MATCH ... {where}` splits away its user_id filter).
        fstring_parts = set()
        texts = []
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                parts = [v for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)]
                fstring_parts.update(id(v) for v in parts)
                texts.append((node, " {} ".join(v.value for v in parts)))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in fstring_parts:
                texts.append((node, node.value))
        for node, s in texts:
            if True:
                sql = re.search(r"\b(SELECT|UPDATE|DELETE)\b", s) and re.search(rf"\b(FROM|UPDATE|JOIN)\s+{USER_TABLES}\b", s)
                cypher = re.search(r"\bMATCH\b", s) and (
                    re.search(r"\{\s*id:\s*\$", s) or re.search(r":(Concept|NoteSource)\b", s))
                if (sql or cypher) and not OWNER_BOUND.search(s):
                    out.append((str(p.relative_to(ROOT)), " ".join(s.split()), node.lineno))
    return out


def test_every_user_data_query_filters_by_owner_or_is_reviewed():
    unreviewed = []
    for f, q, line in unfiltered_queries():
        if f in UNREACHABLE:
            continue
        if not any(f == rf and q.startswith(rq) for rf, rq in REVIEWED):
            unreviewed.append(f"{f}:{line}  {q[:110]}")
    assert not unreviewed, "queries on user data without an owner filter:\n" + "\n".join(unreviewed)


def test_unscoped_graphs_stay_unreachable():
    """content/quiz/research graphs query concepts and notes with no user filter. Wiring one into a
    request path must come with user scoping; until then nothing reachable may import them, by
    module path or by any name they export through backend.graphs."""
    modules = [pathlib.Path(u).stem for u in UNREACHABLE] + ["supervisor_graph"]
    exported = {"quiz_graph", "run_quiz_generation", "research_agent", "run_research", "get_research_history",
                "content_graph", "run_content_generation", "supervisor_graph"}
    offenders = []
    files = [ROOT / "main.py"]
    for d in ("routers", "services", "agents", "agent_v2", "mcp"):
        files += list((ROOT / d).rglob("*.py"))
    for p in files:
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names = {a.name for a in node.names}
                if node.module == "backend.graphs" and names & exported:
                    offenders.append(f"{p.relative_to(ROOT)} imports {sorted(names & exported)} from backend.graphs")
                if any(node.module == f"backend.graphs.{m}" for m in modules):
                    offenders.append(f"{p.relative_to(ROOT)} imports {node.module}")
            elif isinstance(node, ast.Import):
                offenders += [f"{p.relative_to(ROOT)} imports {a.name}" for a in node.names
                              if any(a.name == f"backend.graphs.{m}" for m in modules)]
    assert not offenders, "\n".join(offenders)
