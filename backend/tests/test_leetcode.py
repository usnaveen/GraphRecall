"""LeetCode recall cards, lookup parser/cache, and router endpoints."""
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI

from backend.auth.middleware import get_current_user
from backend.routers.leetcode import router as leetcode_router
from backend.services.leetcode import (
    LeetCodeUpstreamError,
    build_cards,
    lookup_problem,
    parse_graphql_question,
    pseudocode_cloze,
    suggest_pattern,
)

PSEUDO = """def lengthOfLongestSubstring(s):
    seen = {}
    left = best = 0
    for right, ch in enumerate(s):
        if ch in seen and seen[ch] >= left:
            left = seen[ch] + 1
        seen[ch] = right
        best = max(best, right - left + 1)
    return best"""


def test_pseudocode_cloze_hides_key_lines_keeps_signature_and_indent():
    cloze, hidden = pseudocode_cloze(PSEUDO)
    lines = cloze.split("\n")
    assert hidden == 3 and lines[0].startswith("def ")
    assert sum("[___]" in l for l in lines) == 3
    for orig, new in zip(PSEUDO.split("\n"), lines):
        if "[___]" in new:  # indentation preserved
            assert new.index("[") == len(orig) - len(orig.lstrip())
    assert "best = max(best, right - left + 1)" not in cloze  # the core update is hidden


def test_short_pseudocode_makes_no_cloze():
    assert pseudocode_cloze("x = 1") == ("", 0)


def test_build_cards_all_kinds():
    problem = {"title": "Longest Substring Without Repeating Characters", "pattern": "Sliding Window",
               "key_insight": "Move left past the last repeat", "complexity": "O(n)", "pseudocode": PSEUDO}
    attempts = [{"mistake": "Forgot seen[ch] >= left, so left jumped backwards", "mistake_tag": "edge_case"},
                {"mistake": "", "mistake_tag": None}]
    cards = build_cards(problem, attempts)
    assert [c.kind for c in cards] == ["pattern", "pseudocode", "mistake"]
    assert "Pattern: Sliding Window" in cards[0].back and "O(n)" in cards[0].back
    assert "(missed an edge case)" in cards[2].front
    assert cards[2].back.startswith("Forgot")


_FIXTURE_146 = {
    "data": {
        "questionList": {
            "questions": [
                {
                    "questionFrontendId": "1460",
                    "title": "Make Two Arrays Equal by Reversing Subarrays",
                    "titleSlug": "make-two-arrays-equal-by-reversing-subarrays",
                    "difficulty": "Easy",
                    "isPaidOnly": False,
                    "topicTags": [{"name": "Array"}, {"name": "Hash Table"}],
                },
                {
                    "questionFrontendId": "146",
                    "title": "LRU Cache",
                    "titleSlug": "lru-cache",
                    "difficulty": "Medium",
                    "isPaidOnly": False,
                    "topicTags": [
                        {"name": "Hash Table"},
                        {"name": "Linked List"},
                        {"name": "Design"},
                        {"name": "Doubly-Linked List"},
                    ],
                },
            ]
        }
    }
}


def test_parse_graphql_question_exact_id_and_pattern():
    item = parse_graphql_question(_FIXTURE_146, 146)
    assert item is not None
    assert item == {
        "number": 146,
        "title": "LRU Cache",
        "slug": "lru-cache",
        "url": "https://leetcode.com/problems/lru-cache/",
        "difficulty": "medium",
        "tags": ["Hash Table", "Linked List", "Design", "Doubly-Linked List"],
        "pattern": "Linked List",
        "paid_only": False,
    }
    assert parse_graphql_question(_FIXTURE_146, 99999) is None
    assert suggest_pattern(["Sliding Window", "Hash Table"]) == "Sliding Window"
    assert suggest_pattern(["Unknown Tag"]) is None


class _FakeLeetCodePG:
    def __init__(self) -> None:
        self.catalog: dict[int, dict] = {}
        self.problems: dict[tuple[str, str], dict] = {}

    async def execute_query(self, sql: str, params: dict):
        if "FROM leetcode_catalog" in sql:
            row = self.catalog.get(int(params["n"]))
            return [dict(row)] if row else []
        if "INSERT INTO coding_problems" in sql:
            key = (params["u"], params["title"].strip().lower())
            existing = self.problems.get(key)
            now = datetime.now(timezone.utc)
            if existing is None:
                row = {
                    "id": str(uuid.uuid4()),
                    "number": params.get("number"),
                    "title": params["title"],
                    "url": params.get("url"),
                    "difficulty": params.get("difficulty"),
                    "pattern": params.get("pattern"),
                    "tags": list(params.get("tags") or []),
                    "key_insight": params.get("key_insight"),
                    "pseudocode": params.get("pseudocode"),
                    "solution": params.get("solution"),
                    "language": params.get("language"),
                    "complexity": params.get("complexity"),
                    "concept_id": None,
                    "pattern_concept_id": None,
                    "created_at": now,
                    "updated_at": now,
                }
            else:
                row = dict(existing)
                for f in ("number", "url", "difficulty", "pattern", "key_insight", "pseudocode",
                          "solution", "language", "complexity"):
                    if params.get(f) is not None:
                        row[f] = params[f]
                if params.get("tags"):
                    row["tags"] = list(params["tags"])
                row["updated_at"] = now
            self.problems[key] = row
            return [dict(row)]
        if "FROM coding_attempts" in sql:
            return []
        if "FROM flashcards" in sql:
            return []
        return []

    async def execute_update(self, sql: str, params: dict):
        if "INSERT INTO leetcode_catalog" in sql:
            self.catalog[int(params["number"])] = {
                "number": int(params["number"]),
                "title": params["title"],
                "slug": params["slug"],
                "url": params["url"],
                "difficulty": params["difficulty"],
                "tags": list(params.get("tags") or []),
                "paid_only": bool(params.get("paid_only", False)),
            }
        return 1


class _FakeLeetCodeNeo4j:
    async def execute_query(self, sql: str, params: dict):
        if "RETURN c.id AS id" in sql:
            return []
        return []


@pytest.mark.asyncio
async def test_lookup_caches_in_postgres_and_avoids_repeat_upstream():
    pg = _FakeLeetCodePG()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_FIXTURE_146)

    transport = httpx.MockTransport(handler)
    first = await lookup_problem(pg, 146, transport=transport)
    assert first is not None and first["title"] == "LRU Cache"
    assert calls == 1

    # Second call reads from catalog cache without hitting upstream even if upstream fails
    def failing_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Should have served from cache!")

    second = await lookup_problem(pg, 146, transport=httpx.MockTransport(failing_handler))
    assert second == first


@pytest.mark.asyncio
async def test_router_lookup_404_502_and_upsert_with_number(monkeypatch: pytest.MonkeyPatch):
    import backend.routers.leetcode as lc_router_mod

    pg = _FakeLeetCodePG()
    neo = _FakeLeetCodeNeo4j()

    async def fake_pg():
        return pg

    async def fake_neo():
        return neo

    monkeypatch.setattr(lc_router_mod, "get_postgres_client", fake_pg)
    monkeypatch.setattr(lc_router_mod, "get_neo4j_client", fake_neo)

    app = FastAPI()
    app.include_router(leetcode_router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "00000000-0000-0000-0000-000000000001"}

    async def fake_lookup_ok(pg_arg, number: int):
        if number == 146:
            return parse_graphql_question(_FIXTURE_146, 146)
        if number == 502:
            raise LeetCodeUpstreamError("timeout")
        return None

    monkeypatch.setattr(lc_router_mod.lc, "lookup_problem", fake_lookup_ok)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ok = await client.get("/api/leetcode/lookup/146")
        assert ok.status_code == 200
        assert ok.json()["slug"] == "lru-cache"

        nf = await client.get("/api/leetcode/lookup/99999")
        assert nf.status_code == 404
        assert nf.json() == {"detail": "No LeetCode problem #99999"}

        down = await client.get("/api/leetcode/lookup/502")
        assert down.status_code == 502

        created = await client.post(
            "/api/leetcode/problems",
            json={
                "number": 146,
                "title": "LRU Cache",
                "url": "https://leetcode.com/problems/lru-cache/",
                "difficulty": "medium",
                "tags": ["Hash Table", "Linked List", "Design"],
            },
        )
        assert created.status_code == 200
        body = created.json()
        assert body["number"] == 146
        assert body["tags"] == ["Hash Table", "Linked List", "Design"]
        assert body["pattern"] == "Linked List"

        # Legacy upsert by title without number preserves stored number & tags
        legacy = await client.post(
            "/api/leetcode/problems",
            json={"title": "LRU Cache", "key_insight": "Doubly linked list + hash map"},
        )
        assert legacy.status_code == 200
        assert legacy.json()["number"] == 146
        assert legacy.json()["key_insight"] == "Doubly linked list + hash map"
