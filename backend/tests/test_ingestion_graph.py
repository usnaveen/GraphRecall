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


@pytest.mark.asyncio
async def test_save_chunks_node_batches_in_one_session(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.execute_calls = 0
            self.batch_sizes = []

        async def execute(self, _query, params=None):
            self.execute_calls += 1
            if isinstance(params, list):
                self.batch_sizes.append(len(params))
            else:
                self.batch_sizes.append(1)

    class FakeSessionContext:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakePostgresClient:
        def __init__(self):
            self.session_instance = FakeSession()

        def session(self):
            return FakeSessionContext(self.session_instance)

    fake_pg = FakePostgresClient()

    async def fake_get_postgres_client():
        return fake_pg

    monkeypatch.setattr(ingestion_module, "get_postgres_client", fake_get_postgres_client)

    state = {
        "thread_id": "thread-save-1",
        "note_id": "note-1",
        "chunks": [
            {
                "parent_id": "parent-1",
                "parent_content": "Parent content",
                "parent_index": 0,
                "images": [],
                "child_contents": ["Child one", "Child two"],
                "child_embeddings": [[0.1, 0.2], None],
                "child_ids": ["child-1", "child-2"],
                "child_page_starts": [1, 1],
                "child_page_ends": [1, 1],
            }
        ],
        "propositions": [
            {
                "id": "prop-1",
                "note_id": "note-1",
                "chunk_id": "child-1",
                "content": "Atomic fact",
                "confidence": 0.9,
                "is_atomic": True,
            }
        ],
    }

    result = await ingestion_module.save_chunks_node(state)

    assert "error" not in result
    assert fake_pg.session_instance.execute_calls == 4
    assert result["processing_metadata"]["progress"]["chunk_save_done"] == 4
    assert result["processing_metadata"]["progress"]["chunk_save_total"] == 4


@pytest.mark.asyncio
async def test_get_ingestion_status_includes_live_save_chunks_progress(monkeypatch):
    class FakeState:
        values = {
            "user_id": "user-1",
            "processing_metadata": {
                "progress": {
                    "completed_nodes": ["parse", "chunk", "extract_concepts", "store_note", "embed_chunks"],
                    "failed_batches": 0,
                    "concepts_extracted": 42,
                }
            },
            "extracted_concepts": [],
        }
        next = ("save_chunks",)

    thread_id = "thread-live-progress-1"
    monkeypatch.setattr(ingestion_module.ingestion_graph, "get_state", lambda _config: FakeState())
    ingestion_module._live_node_progress[thread_id] = {
        "current_node": "save_chunks",
        "chunk_save_total": 1000,
        "chunk_save_done": 420,
        "chunk_save_stage": "children_with_embeddings",
    }

    result = await ingestion_module.get_ingestion_status(thread_id, user_id="user-1")

    assert result["status"] == "processing"
    assert result["progress"]["chunk_save_total"] == 1000
    assert result["progress"]["chunk_save_done"] == 420
    assert result["progress"]["chunk_save_stage"] == "children_with_embeddings"

    ingestion_module._clear_live_progress(thread_id)
