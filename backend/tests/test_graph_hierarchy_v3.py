"""Tests for GR-V3-GRAPH-API-01 hierarchy, recall outline, and Spec §0.5 bug fixes."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from backend.db.neo4j_client import Neo4jClient
from backend.models.schemas import GraphResponse
from backend.services.feed_service import FeedService
from backend.services.graph_hierarchy import (
    build_recall_outline,
    get_hierarchy,
    normalize_edge_type,
    normalize_subject,
)


class _FakeNeo4jDateTime:
    def iso_format(self) -> str:
        return "2026-11-26T20:00:00+00:00"


class _FakeGraphNeo4j:
    def __init__(self):
        self.concepts = [
            {"id": "c-att", "name": "Attention Mechanism", "domain": "Natural Language Processing", "definition": "Weighted focus", "complexity_score": 6},
            {"id": "c-mha", "name": "Multi-Head Attention", "domain": "Deep Learning", "definition": "Parallel attention heads", "complexity_score": 7},
            {"id": "c-la", "name": "Matrix Multiplication", "domain": "Math and Geometry", "definition": "Linear transform", "complexity_score": 4},
        ]
        self.edges = [
            {"source": "c-la", "target": "c-att", "raw_type": "PREREQUISITE_OF", "strength": 0.9, "edge_id": "e1"},
            {"source": "c-mha", "target": "c-att", "raw_type": "SUBTOPIC_OF", "strength": 0.85, "edge_id": "e2"},
            {"source": "c-mha", "target": "c-la", "raw_type": "BUILDS_ON", "strength": 0.6, "edge_id": "e3"},
            {"source": "c-att", "target": "c-mha", "raw_type": "APPLIES_TO", "strength": 0.5, "edge_id": "e4"},
            {"source": "c-att", "target": "c-la", "raw_type": "RELATED_TO", "strength": 0.4, "edge_id": "e5"},
        ]

    async def execute_query(self, query: str, params=None):
        if "RETURN c.id AS id, c.name AS name" in query:
            return self.concepts
        if "RETURN c1.id AS source" in query:
            return self.edges
        return []


class _FakeGraphPG:
    def __init__(self):
        self._fake_communities = [
            {"id": "comm-ml", "title": "Transformers", "level": 1, "summary": "Attention family", "entity_ids": ["c-att", "c-mha"], "size": 2},
            {"id": "comm-math", "title": "Linear Algebra", "level": 1, "summary": "Vectors and matrices", "entity_ids": ["c-la"], "size": 1},
        ]

    async def execute_query(self, query: str, params=None):
        if "FROM knowledge_evidence" in query:
            return [
                {"concept_id": "c-la", "skill_key": "matrix multiplication", "kind": "quiz", "signal": 0.9, "weight": 1.0, "created_at": datetime.now(timezone.utc), "detail": {}},
                {"concept_id": "c-att", "skill_key": "attention mechanism", "kind": "quiz", "signal": 0.35, "weight": 1.0, "created_at": datetime.now(timezone.utc), "detail": {}},
            ]
        return []


def test_normalize_edge_type_contract_compliance():
    assert normalize_edge_type("PREREQUISITE_OF") == ("prerequisite", "forward")
    assert normalize_edge_type("SUBTOPIC_OF") == ("subtopic", "forward")
    assert normalize_edge_type("PART_OF") == ("subtopic", "forward")
    assert normalize_edge_type("BUILDS_ON") == ("builds_on", "forward")
    assert normalize_edge_type("APPLIES_TO") == ("applies_to", "forward")
    assert normalize_edge_type("RELATED_TO") == ("related", "none")


@pytest.mark.asyncio
async def test_hierarchy_levels_and_related_filter():
    neo = _FakeGraphNeo4j()
    pg = _FakeGraphPG()

    uni = await get_hierarchy("user-1", "universe", include_related=False, neo4j=neo, pg=pg)
    assert uni["level"] == "universe"
    labels = {n["label"] for n in uni["nodes"]}
    assert labels == {"Machine Learning", "Mathematics"}
    assert all(n["color_key"] == n["label"] for n in uni["nodes"])
    assert all(e["type"] != "related" for e in uni["edges"])

    gal = await get_hierarchy("user-1", "galaxy", domain="Machine Learning", include_related=False, neo4j=neo, pg=pg)
    assert [n["id"] for n in gal["nodes"]] == ["comm-ml"]
    assert gal["nodes"][0]["color_key"] == "comm-ml"

    cons_default = await get_hierarchy("user-1", "concepts", include_related=False, neo4j=neo, pg=pg)
    assert all(e["type"] != "related" for e in cons_default["edges"])
    status_by_id = {n["id"]: n["status"] for n in cons_default["nodes"]}
    assert status_by_id["c-la"] == "strong"
    assert status_by_id["c-att"] == "shaky"
    assert status_by_id["c-mha"] == "seen"
    assert all(s in {"strong", "shaky", "seen", "unexposed"} for s in status_by_id.values())

    cons_rel = await get_hierarchy("user-1", "concepts", include_related=True, neo4j=neo, pg=pg)
    assert any(e["type"] == "related" and e["direction"] == "none" for e in cons_rel["edges"])


@pytest.mark.asyncio
async def test_recall_outline_cycle_safe_and_color_hints():
    neo = _FakeGraphNeo4j()
    neo.edges.append({"source": "c-att", "target": "c-mha", "raw_type": "SUBTOPIC_OF", "strength": 0.5, "edge_id": "cycle"})
    pg = _FakeGraphPG()
    outline = await build_recall_outline("user-1", neo4j=neo, pg=pg, max_depth=4)
    assert outline["total_concepts"] == 3
    assert len(outline["roots"]) >= 1
    first = outline["roots"][0]
    assert first["color_hint"] in {"green", "red", "amber", "grey"}


@pytest.mark.asyncio
async def test_spec_05_bug_fixes():
    # Bug #1: Neo4j DateTime in edge properties must serialize cleanly to GraphResponse
    client = Neo4jClient.__new__(Neo4jClient)
    client.execute_query = AsyncMock(return_value=[{
        "node": {
            "id": "n1",
            "name": "KV Cache",
            "domain": "ML",
            "complexity_score": 6,
            "relationships": [{"target": "n2", "type": "PREREQUISITE_OF", "properties": {"created_at": _FakeNeo4jDateTime()}}],
        }
    }])
    graph = await client.get_graph_for_user("user-1")
    resp = GraphResponse(nodes=graph["nodes"], edges=graph["edges"], total_concepts=1, total_relationships=1)
    assert resp.edges[0]["properties"]["created_at"] == "2026-11-26T20:00:00+00:00"

    # Bug #2: FeedService.get_daily_goal must not query non-existent s.item_id
    queries: list[str] = []

    class _PG:
        async def execute_query(self, q, p=None):
            queries.append(q)
            return [{"cnt": 0}]

    svc = FeedService(pg_client=_PG(), neo4j_client=AsyncMock())
    svc.sr_service = AsyncMock()
    svc.sr_service.get_due_items = AsyncMock(return_value=[])
    svc.get_completed_today = AsyncMock(return_value=1)
    await svc.get_daily_goal("user-1")
    assert all("s.item_id" not in q for q in queries)
    assert any("q.concept_id = s.concept_id" in q for q in queries)
