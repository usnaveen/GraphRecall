"""API tests for Graph3D visualization endpoint."""

from unittest.mock import AsyncMock

import pytest

from backend.routers import graph3d as graph3d_router


@pytest.mark.asyncio
async def test_get_3d_graph_returns_communities(monkeypatch):
    mock_neo4j = AsyncMock()

    def execute_query(query, params=None):
        if "RETURN c as concept" in query:
            return [
                {
                    "concept": {
                        "id": "c1",
                        "name": "Node 1",
                        "definition": "Test",
                        "domain": "General",
                        "complexity_score": 5,
                    }
                }
            ]
        if "count(r) as count" in query:
            return [{"count": 1}]
        if "relationship_type" in query and "MATCH (c1:Concept)" in query:
            return [
                {
                    "source": "c1",
                    "target": "c1",
                    "relationship_type": "RELATED_TO",
                    "strength": 1.0,
                    "edge_id": "e1",
                }
            ]
        return []

    queries = []

    def execute_and_record(query, params=None):
        queries.append(query)
        return execute_query(query, params)

    mock_neo4j.execute_query = AsyncMock(side_effect=execute_and_record)

    async def fake_get_neo4j_client():
        return mock_neo4j

    mock_pg = AsyncMock()
    mock_pg.execute_query = AsyncMock(return_value=[])

    async def fake_get_postgres_client():
        return mock_pg

    async def fake_get_communities(self, user_id: str):
        return [
            {
                "id": "comm-1",
                "title": "General Cluster",
                "level": 0,
                "parent": None,
                "children": [],
                "entity_ids": ["c1"],
                "size": 1,
            }
        ]

    monkeypatch.setattr(graph3d_router, "get_neo4j_client", fake_get_neo4j_client)
    monkeypatch.setattr(graph3d_router, "get_postgres_client", fake_get_postgres_client)
    monkeypatch.setattr(graph3d_router.CommunityService, "get_communities", fake_get_communities)

    response = await graph3d_router.get_3d_graph(
        current_user={"id": "user-1"},
        center_concept_id=None,
        max_depth=3,
    )

    assert response.total_nodes == 1
    assert response.total_edges == 1
    assert len(response.communities) == 1
    edge_queries = [q for q in queries if "relationship_type" in q]
    assert edge_queries, "paged load should query edges"
    assert "c1.id IN $node_ids OR c2.id IN $node_ids" in edge_queries[-1]
    assert "c1.id IN $node_ids AND c2.id IN $node_ids" not in edge_queries[-1]


def test_edge_scope_keeps_cross_page_links_and_contains_focus():
    paged = graph3d_router.edge_endpoint_scope(focused=False)
    focused = graph3d_router.edge_endpoint_scope(focused=True)
    assert paged == "(c1.id IN $node_ids OR c2.id IN $node_ids)"
    assert focused == "c1.id IN $node_ids AND c2.id IN $node_ids"
