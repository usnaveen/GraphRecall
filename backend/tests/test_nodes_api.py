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

    # Graph placement is graph_registry's job (its own Neo4j client and an LLM call); this test is
    # about the router persisting the node and its canvas position.
    async def fake_resolve_graph(user_id, **kwargs):
        return {"graph": "Machine Learning", "created": False, "reason": "test"}

    monkeypatch.setattr(nodes_router, "resolve_graph", fake_resolve_graph)

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
    assert response["links"] == [{"target_id": "node-2", "relationship_type": "RELATED_TO"}]


@pytest.mark.asyncio
async def test_fetch_context_tops_up_sparse_vector_candidates_with_domain_hub(monkeypatch):
    import importlib
    lsg = importlib.import_module("backend.graphs.link_suggestion_graph")

    mock_neo4j = AsyncMock()

    async def fake_execute_query(query, params=None):
        if "RETURN c" in query and "MATCH (c:Concept {id: $id" in query:
            return [{
                "c": {
                    "id": "sl-1",
                    "name": "Supervised learning",
                    "definition": "Training models on labeled data.",
                    "domain": "Machine Learning",
                    "embedding": [0.1, 0.2],
                }
            }]
        if "RETURN DISTINCT n.id AS id" in query:
            return [{"id": "already-linked"}]
        if "AS domain_rank" in query:
            assert "already-linked" in params["exclude_ids"]
            return [
                {
                    "id": "ml-hub",
                    "name": "Machine Learning",
                    "definition": "Core discipline of learning from data.",
                    "domain": "Machine Learning",
                    "domain_rank": 2,
                },
                {
                    "id": "lr-1",
                    "name": "Logistic Regression",
                    "definition": "Supervised classifier.",
                    "domain": "Machine Learning",
                    "domain_rank": 1,
                },
            ]
        return []

    mock_neo4j.execute_query = AsyncMock(side_effect=fake_execute_query)

    async def fake_get_neo4j_client():
        return mock_neo4j

    async def fake_similar_to_embedding(*args, **kwargs):
        assert "already-linked" in kwargs["exclude_ids"]
        return [
            {"id": "vec-1", "name": "Dropout", "definition": "Regularization", "domain": "Machine Learning", "score": 0.72},
            {"id": "vec-2", "name": "K-Means", "definition": "Clustering", "domain": "Machine Learning", "score": 0.68},
        ]

    monkeypatch.setattr(lsg, "get_neo4j_client", fake_get_neo4j_client)
    monkeypatch.setattr(lsg, "similar_to_embedding", fake_similar_to_embedding)

    state = await lsg.fetch_context_node({"node_id": "sl-1", "user_id": "user-1"})
    candidate_names = [c["name"] for c in state["candidates"]]
    assert "Machine Learning" in candidate_names
    assert "Logistic Regression" in candidate_names
    assert "Dropout" in candidate_names
    assert state["candidates"][0]["id"] == "ml-hub"


@pytest.mark.asyncio
async def test_generate_links_does_not_truncate_json_for_large_candidate_list(monkeypatch):
    import importlib
    import json
    lsg = importlib.import_module("backend.graphs.link_suggestion_graph")

    captured_prompts = []

    class FakeResponse:
        def __init__(self, text):
            self.text = text

    class FakeLLM:
        async def ainvoke(self, prompt_text):
            captured_prompts.append(prompt_text)
            return FakeResponse(json.dumps({
                "links": [{
                    "target_id": "ml-hub",
                    "relationship_type": "SUBTOPIC_OF",
                    "strength": 0.92,
                    "reason": "Supervised learning is a primary branch of Machine Learning.",
                }]
            }))

    monkeypatch.setattr(lsg, "get_chat_model", lambda **kwargs: FakeLLM())

    candidates = [
        {
            "id": "ml-hub" if i == 0 else f"cand-{i}",
            "name": "Machine Learning" if i == 0 else f"Concept {i}",
            "definition": "X" * 200,
            "domain": "Machine Learning",
        }
        for i in range(40)
    ]
    res = await lsg.generate_links_node({
        "node": {
            "id": "sl-1",
            "name": "Supervised learning",
            "definition": "Training models using labeled datasets.",
            "domain": "Machine Learning",
        },
        "candidates": candidates,
    })

    assert len(captured_prompts) == 1
    payload_str = captured_prompts[0].split("Data:\n", 1)[1]
    parsed = json.loads(payload_str)
    assert len(parsed["candidates"]) == 40
    assert res["links"][0]["target_id"] == "ml-hub"
    assert res["links"][0]["target_name"] == "Machine Learning"
    assert res["links"][0]["relationship_type"] == "SUBTOPIC_OF"
