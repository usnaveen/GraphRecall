"""Integration-style tests for the LangGraph ingestion workflow nodes."""

from unittest.mock import AsyncMock, MagicMock
import importlib

import pytest

ingestion_module = importlib.import_module("backend.graphs.ingestion_graph")


@pytest.mark.asyncio
async def test_extract_concepts_node_success(monkeypatch):
    mock_concept = MagicMock()
    mock_concept.model_dump.return_value = {
        "name": "Neural Network",
        "definition": "Computing system",
        "domain": "Machine Learning",
        "complexity_score": 6,
        "confidence": 0.9,
        "related_concepts": [],
        "prerequisites": [],
    }
    mock_result = MagicMock(concepts=[mock_concept])

    async def fake_extract(_content):
        return mock_result

    monkeypatch.setattr(ingestion_module.extraction_agent, "extract", fake_extract)

    mock_neo4j = AsyncMock()
    mock_neo4j.execute_query.return_value = []

    async def fake_get_neo4j_client():
        return mock_neo4j

    monkeypatch.setattr(ingestion_module, "get_neo4j_client", fake_get_neo4j_client)

    result = await ingestion_module.extract_concepts_node(
        {"raw_content": "Test content", "user_id": "user-1"}
    )

    assert len(result["extracted_concepts"]) == 1
    assert result["extracted_concepts"][0]["name"] == "Neural Network"


@pytest.mark.asyncio
async def test_find_related_node_detects_overlap(monkeypatch):
    mock_neo4j = AsyncMock()
    mock_neo4j.execute_query.return_value = [
        {
            "id": "existing-1",
            "name": "Neural Network",
            "definition": "Computing systems",
            "domain": "Machine Learning",
            "complexity_score": 6,
        }
    ]

    async def fake_get_neo4j_client():
        return mock_neo4j

    monkeypatch.setattr(ingestion_module, "get_neo4j_client", fake_get_neo4j_client)

    state = {
        "user_id": "user-1",
        "extracted_concepts": [
            {"name": "Neural Network", "definition": "Computing systems", "domain": "Machine Learning"}
        ],
    }

    result = await ingestion_module.find_related_node(state)

    assert result["needs_synthesis"] is True
    assert len(result["related_concepts"]) == 1


@pytest.mark.asyncio
async def test_store_note_node_inserts(monkeypatch):
    mock_pg = AsyncMock()
    mock_pg.execute_insert = AsyncMock(return_value="note-1")

    async def fake_get_postgres_client():
        return mock_pg

    monkeypatch.setattr(ingestion_module, "get_postgres_client", fake_get_postgres_client)

    result = await ingestion_module.store_note_node(
        {"note_id": "note-1", "user_id": "user-1", "raw_content": "Test", "title": "T"}
    )

    assert result["note_id"] == "note-1"


@pytest.mark.asyncio
async def test_create_concepts_node_creates(monkeypatch):
    mock_neo4j = AsyncMock()
    mock_neo4j.create_concept = AsyncMock(return_value={"c": {"id": "c1"}})
    mock_neo4j.create_relationship = AsyncMock(return_value={})
    mock_neo4j.execute_query = AsyncMock(return_value=[])

    async def fake_get_neo4j_client():
        return mock_neo4j

    monkeypatch.setattr(ingestion_module, "get_neo4j_client", fake_get_neo4j_client)

    state = {
        "user_id": "user-1",
        "note_id": "note-1",
        "extracted_concepts": [
            {
                "name": "Neural Network",
                "definition": "Computing systems",
                "domain": "Machine Learning",
                "complexity_score": 6,
                "related_concepts": [],
                "prerequisites": [],
            }
        ],
    }

    result = await ingestion_module.create_concepts_node(state)

    assert result["created_concept_ids"] == ["c1"]


def test_route_after_find_related_fast_path_without_overlap():
    state = {
        "needs_synthesis": False,
        "skip_review": False,
    }
    assert ingestion_module.route_after_find_related(state) == "create_concepts"


def test_route_after_find_related_synthesis_with_overlap_manual_review():
    state = {
        "needs_synthesis": True,
        "skip_review": False,
    }
    assert ingestion_module.route_after_find_related(state) == "synthesize"


def test_route_after_extract_concepts_end_on_error():
    state = {"error": "insufficient_concepts"}
    assert ingestion_module.route_after_extract_concepts(state) == "end"


@pytest.mark.asyncio
async def test_extract_concepts_node_flags_insufficient_for_large_content(monkeypatch):
    mock_concept = MagicMock()
    mock_concept.model_dump.return_value = {
        "name": "Single Concept",
        "definition": "Only one concept extracted",
        "domain": "General",
        "complexity_score": 3,
        "confidence": 0.6,
        "related_concepts": [],
        "prerequisites": [],
    }
    mock_result = MagicMock(concepts=[mock_concept])

    async def fake_extract(_content):
        return mock_result

    monkeypatch.setattr(ingestion_module.extraction_agent, "extract", fake_extract)

    mock_neo4j = AsyncMock()
    mock_neo4j.execute_query.return_value = []

    async def fake_get_neo4j_client():
        return mock_neo4j

    monkeypatch.setattr(ingestion_module, "get_neo4j_client", fake_get_neo4j_client)

    state = {
        "raw_content": "x" * (ingestion_module.LARGE_CONTENT_CHAR_THRESHOLD + 1000),
        "user_id": "user-1",
    }
    result = await ingestion_module.extract_concepts_node(state)

    assert result.get("error") == "insufficient_concepts"
    assert result.get("status_reason") == "insufficient_concepts"


def test_resolve_concept_uuid_prefers_mapping():
    resolved = ingestion_module._resolve_concept_uuid(
        candidate="Automatic Differentiation (Autograd)",
        concepts=[],
        concept_name_to_id={"automatic differentiation": "11111111-1111-1111-1111-111111111111"},
        created_ids={"11111111-1111-1111-1111-111111111111"},
    )
    assert resolved == "11111111-1111-1111-1111-111111111111"
