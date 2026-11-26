"""Tests for Spec §5 agent memory upgrades: get_knowledge_frontier and record_exposure."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.agent_bridge.keys import SCOPE_READ_KNOWLEDGE, SCOPE_WRITE_FEED, AgentPrincipal
from backend.agent_bridge.knowledge import KnowledgeService
from backend.agent_bridge.repository import InMemoryBridgeRepository
from backend.agent_bridge.tools import TOOLS, BridgeServices, call_tool
from backend.tests.agent_bridge_fakes import CONCEPTS, EDGES, USER_A, USER_B, FakeNeo4j, FakePG


class _FrontierNeo4j(FakeNeo4j):
    async def execute_query(self, query: str, params=None):
        params = params or {}
        uid = params.get("user_id")
        if "MATCH (ch:Concept)-[:SUBTOPIC_OF]->(p:Concept)" in query:
            self.calls.append((query, params))
            return []
        if "WHERE s.id IN $seed_ids" in query:
            self.calls.append((query, params))
            mine = {c["id"]: c for c in CONCEPTS if c["user_id"] == uid}
            seed_ids = set(params.get("seed_ids") or [])
            rows = []
            for s, _, t in EDGES:
                if s in seed_ids and t in mine and t not in seed_ids:
                    rows.append(mine[t])
                elif t in seed_ids and s in mine and s not in seed_ids:
                    rows.append(mine[s])
            return rows
        if "MATCH (n:NoteSource" in query:
            self.calls.append((query, params))
            return []
        return await super().execute_query(query, params)


class _FrontierPG(FakePG):
    def __init__(self):
        super().__init__()
        self.inserted_evidence: list[dict] = []
        self.upserted_skills: list[dict] = []

    async def execute_query(self, query: str, params=None):
        params = params or {}
        if "FROM knowledge_evidence" in query:
            if "signal < 0.45" in query:
                return [{
                    "concept_id": "a-backprop",
                    "kind": "quiz",
                    "signal": 0.25,
                    "detail": {"missed": "chain rule sign"},
                    "created_at": datetime.now(timezone.utc),
                }]
            return [{
                "concept_id": "a-gd",
                "skill_key": "gradient descent",
                "kind": "quiz",
                "signal": 0.9,
                "weight": 1.0,
                "created_at": datetime.now(timezone.utc),
                "detail": {},
            }]
        if "FROM user_skills" in query:
            return []
        if "FROM proficiency_scores" in query and "u" in params:
            return [{
                "concept_id": "a-gd",
                "score": 0.85,
                "total_reviews": 2,
                "repetition_count": 2,
                "last_reviewed": datetime.now(timezone.utc),
            }]
        if "FROM user_resumes" in query:
            return [{"skills": [{"name": "Backpropagation", "section": "Skills"}, {"name": "Triton Kernels", "section": "Projects"}]}]
        if "FROM notes" in query or "FROM ingested_resources" in query:
            return []
        return await super().execute_query(query, params)

    async def execute_update(self, query: str, params=None):
        params = params or {}
        self.calls.append((query, params))
        if "INSERT INTO knowledge_evidence" in query:
            self.inserted_evidence.append(params)
        elif "INSERT INTO user_skills" in query:
            self.upserted_skills.append(params)
        return []


@pytest.mark.asyncio
async def test_get_knowledge_frontier_partitions_anchors_frontier_gaps():
    pg = _FrontierPG()
    neo = _FrontierNeo4j()
    services = BridgeServices(repo=InMemoryBridgeRepository(), knowledge=KnowledgeService(pg, neo))
    p = AgentPrincipal(user_id=USER_A, key_id="k1", scopes=frozenset({SCOPE_READ_KNOWLEDGE}))

    assert TOOLS["get_knowledge_frontier"].scope == SCOPE_READ_KNOWLEDGE
    res = await call_tool(
        "get_knowledge_frontier",
        p,
        services,
        {"query": "Why did gradient descent fail on backpropagation?", "concept_names": ["Backpropagation", "Gradient Descent", "Triton Kernels"]},
    )
    assert res["ok"] is True, res
    data = res["data"]
    assert len(data["profile_prefix_hash"]) == 64
    assert any(a["concept_id"] == "a-gd" for a in data["anchors"])
    assert any(g["name"] == "Triton Kernels" for g in data["gaps"])
    assert len(data["misconceptions"]) == 1
    assert any(r["skill"] in {"Backpropagation", "Triton Kernels"} for r in data["resume_claims_at_risk"])
    # Cross-user isolation: Alice's frontier never leaks Bob's concepts
    assert all("SQL Joins" not in str(v) for v in data.values())


@pytest.mark.asyncio
async def test_record_exposure_requires_write_scope_and_persists():
    pg = _FrontierPG()
    neo = _FrontierNeo4j()
    services = BridgeServices(repo=InMemoryBridgeRepository(), knowledge=KnowledgeService(pg, neo))

    read_only = AgentPrincipal(user_id=USER_A, key_id="k1", scopes=frozenset({SCOPE_READ_KNOWLEDGE}))
    denied = await call_tool("record_exposure", read_only, services, {"concept": "Gradient Descent", "context": "Discussed AdamW"})
    assert denied["ok"] is False and denied["error"]["code"] == "forbidden"

    writer = AgentPrincipal(user_id=USER_A, key_id="k2", scopes=frozenset({SCOPE_WRITE_FEED}))
    bad_url = await call_tool(
        "record_exposure",
        writer,
        services,
        {"concept": "Gradient Descent", "context": "Discussed AdamW", "source_url": "file:///etc/passwd"},
    )
    assert bad_url["ok"] is False and bad_url["error"]["code"] == "invalid_arguments"

    ok = await call_tool(
        "record_exposure",
        writer,
        services,
        {"concept": "Gradient Descent", "context": "Reviewed learning rate decay in Claude session", "source": "claude", "confidence": 0.6},
    )
    assert ok["ok"] is True, ok
    assert ok["data"]["concept_id"] == "a-gd"
    assert ok["data"]["matched_existing"] is True
    assert len(pg.inserted_evidence) == 1
    assert pg.inserted_evidence[0]["kind"] == "agent"
    assert len(pg.upserted_skills) == 1
