"""In-memory fakes for agent-bridge tests (Neo4j + Postgres reads used by KnowledgeService).

The fakes *enforce* user filtering the same way the real stores would: every query must
pass ``user_id`` and only that user's rows come back. They also record every call so tests
can assert no query was issued without a user filter.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

USER_A = "11111111-1111-1111-1111-111111111111"
USER_B = "22222222-2222-2222-2222-222222222222"


def _concept(cid, uid, name, domain="Machine Learning", definition=""):
    return {"id": cid, "user_id": uid, "name": name, "domain": domain,
            "definition": definition or f"{name} definition", "complexity_score": 5}


CONCEPTS = [
    _concept("a-backprop", USER_A, "Backpropagation"),
    _concept("a-gd", USER_A, "Gradient Descent"),
    _concept("a-secret", USER_A, "Alice Private Topic"),
    _concept("b-sql", USER_B, "SQL Joins", domain="Database Systems"),
    _concept("b-index", USER_B, "B-Tree Index", domain="Database Systems"),
]
EDGES = [("a-backprop", "RELATED_TO", "a-gd"), ("b-sql", "RELATED_TO", "b-index"),
         # A cross-user edge should never exist, but if it did the bridge must not follow it.
         ("b-sql", "RELATED_TO", "a-secret")]
SCORES = {(USER_A, "a-backprop"): 0.3, (USER_A, "a-gd"): 0.8, (USER_A, "a-secret"): 0.2,
          (USER_B, "b-sql"): 0.4, (USER_B, "b-index"): 0.9}


class FakeNeo4j:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute_query(self, query: str, params=None):
        params = params or {}
        self.calls.append((query, params))
        uid = params["user_id"]  # KeyError == test failure: query without user filter
        mine = [c for c in CONCEPTS if c["user_id"] == uid]
        by_id = {c["id"]: c for c in mine}
        if "OPTIONAL MATCH (c)-[r]-(n:Concept {user_id: $user_id})" in query:
            center = by_id.get(params["id"])
            if not center:
                return []
            rows = []
            for s, rel, t in EDGES:
                if center["id"] in (s, t):
                    other = t if s == center["id"] else s
                    if other in by_id:  # neighbour must also be the user's
                        rows.append({"c": center, "rel": rel, "n": by_id[other],
                                     "dir": "out" if s == center["id"] else "in"})
            return rows[: params.get("limit", 25)] or [{"c": center, "rel": None, "n": None,
                                                        "dir": None}]
        if "c.id IN $ids" in query:
            return [{"c": by_id[i]} for i in params["ids"] if i in by_id]
        if "CONTAINS" in query:
            q = params["q"].lower()
            return [{"c": c} for c in mine
                    if q in c["name"].lower() or q in c["definition"].lower()][: params["limit"]]
        if "RETURN c.id AS id" in query:
            return [{"id": c["id"], "name": c["name"], "domain": c["domain"]} for c in mine]
        raise AssertionError(f"unexpected cypher: {query}")


class FakePG:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def execute_query(self, query: str, params=None):
        params = params or {}
        self.calls.append((query, params))
        uid = params["user_id"]
        mine = {cid: s for (u, cid), s in SCORES.items() if u == uid}
        if "ps.concept_id as item_id" in query:  # SpacedRepetitionService.get_due_items
            past = datetime.now(timezone.utc) - timedelta(days=1)
            return [{"item_id": cid, "item_type": "concept", "easiness_factor": 2.5,
                     "interval": 1, "repetition": 0, "last_review": None, "next_review": past,
                     "total_reviews": 0, "correct_streak": 0, "mastery_score": s}
                    for cid, s in mine.items()]
        if "FROM proficiency_scores" in query and "last_reviewed" in query:
            now = datetime.now(timezone.utc)
            return [{"concept_id": cid, "score": s, "last_reviewed": now}
                    for cid, s in mine.items()]
        if "FROM proficiency_scores" in query:
            cids = params.get("cids")
            return [{"concept_id": cid, "score": s} for cid, s in mine.items()
                    if cids is None or cid in cids]
        if "FROM notes" in query:
            return []
        raise AssertionError(f"unexpected sql: {query}")
