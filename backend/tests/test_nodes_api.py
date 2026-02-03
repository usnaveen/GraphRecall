"""API tests for manual node creation and linking."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.routers import nodes as nodes_router


@pytest.mark.asyncio
async def test_create_node_persists_position(monkeypatch):
    mock_neo4j = AsyncMock()
    mock_node = {
        "id": "node-1",
        "name": "Semantic Search",
        "definition": "Search with embeddings",
        "domain": "General",
        "x": 10.0,
        "y": 20.0,
        "z": -5.0,
    }
    mock_neo4j.execute_query = AsyncMock(return_value=[{"c": mock_node}])

    async def fake_get_neo4j_client():
        return mock_neo4j

    mock_pg = AsyncMock()
    mock_pg.execute_update = AsyncMock(return_value=None)

    async def fake_get_postgres_client():
        return mock_pg

    monkeypatch.setattr(nodes_router, "get_neo4j_client", fake_get_neo4j_client)
    monkeypatch.setattr(nodes_router, "get_postgres_client", fake_get_postgres_client)

    req = nodes_router.CreateNodeRequest(
        name="Semantic Search",
        description="Search with embeddings",
        position={"x": 10.0, "y": 20.0, "z": -5.0},
    )
    response = await nodes_router.create_node(req, current_user={"id": "user-1"})

    assert response["status"] == "created"
    assert response["node"]["id"] == "node-1"
    assert response["node"]["x"] == 10.0


@pytest.mark.asyncio
async def test_suggest_links_returns_targets(monkeypatch):
    async def fake_run_link_suggestions(node_id: str, user_id: str):
        return {
            "links": [
                {
                    "target_id": "node-2",
                    "target_name": "Vector Embeddings",
                    "relationship_type": "DEPENDS_ON",
                    "strength": 0.8,
                    "reason": "Embeddings power semantic search",
                }
            ]
        }

    monkeypatch.setattr(nodes_router, "run_link_suggestions", fake_run_link_suggestions)

    response = await nodes_router.suggest_links("node-1", current_user={"id": "user-1"})

    assert response["node_id"] == "node-1"
    assert response["links"][0]["target_id"] == "node-2"
    assert response["links"][0]["target_name"] == "Vector Embeddings"


@pytest.mark.asyncio
async def test_apply_links_creates_relationships(monkeypatch):
    mock_neo4j = AsyncMock()

    def execute_query(query, params=None):
        if "MATCH (c:Concept {id: $id" in query:
            return [{"c": {"id": "node-1", "name": "Semantic Search"}}]
        return [{"relationship": "RELATED_TO"}]

    mock_neo4j.execute_query = AsyncMock(side_effect=execute_query)

    async def fake_get_neo4j_client():
        return mock_neo4j

    monkeypatch.setattr(nodes_router, "get_neo4j_client", fake_get_neo4j_client)

    request = nodes_router.ApplyLinksRequest(
        links=[
            nodes_router.LinkSuggestion(
                target_id="node-2",
                relationship_type="RELATED_TO",
                strength=0.6,
            )
        ]
    )

    response = await nodes_router.apply_links("node-1", request, current_user={"id": "user-1"})

    assert response["status"] == "linked"
    assert response["created"] == ["RELATED_TO"]
