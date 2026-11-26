"""Tests for live dictation-to-graph SSE streaming."""

from __future__ import annotations

import pytest

from backend.services.dictation_graph import parse_dictated_concepts, stream_dictation_to_graph


class _DictationNeo4j:
    def __init__(self):
        self.created_nodes: list[dict] = []
        self.created_edges: list[dict] = []

    async def execute_query(self, query: str, params=None):
        params = params or {}
        if "RETURN c.id AS id, c.name AS name" in query:
            return [
                {"id": "c-att", "name": "Attention", "domain": "Machine Learning", "definition": ""},
                {"id": "c-kv", "name": "KV Cache", "domain": "Machine Learning", "definition": ""},
            ]
        if "WHERE c1.id IN $ids AND c2.id IN $ids" in query:
            return [{"source": "c-kv", "target": "c-att", "raw_type": "APPLIES_TO", "strength": 0.9}]
        if "CREATE (c:Concept" in query:
            self.created_nodes.append(params)
            return []
        if "MERGE (c1)-[r:" in query:
            self.created_edges.append(params)
            return []
        return []


def test_parse_dictated_concepts():
    terms = parse_dictated_concepts("add concepts: KV cache, attention, speculative decoding, and KV cache")
    assert terms == ["KV cache", "attention", "speculative decoding"]


@pytest.mark.asyncio
async def test_stream_dictation_emits_concepts_existing_then_inferred_then_done():
    neo = _DictationNeo4j()
    events = [
        ev
        async for ev in stream_dictation_to_graph(
            "user-1",
            "KV cache, attention, multi-head attention, speculative decoding",
            domain="Machine Learning",
            commit=True,
            use_llm=False,
            neo4j=neo,
            pg=None,
        )
    ]
    kinds = [e["event"] for e in events]
    assert kinds[:4] == ["concept", "concept", "concept", "concept"]
    assert kinds[-1] == "done"

    edge_events = [e["data"] for e in events if e["event"] == "edge"]
    origins = [e["origin"] for e in edge_events]
    assert origins[0] == "existing"
    assert "inferred" in origins
    assert any(e["raw_type"] == "SUBTOPIC_OF" and e["target"] == "c-att" for e in edge_events)

    done = events[-1]["data"]
    assert done["nodes_matched"] == 2
    assert done["nodes_created"] == 2
    assert done["existing_edges"] == 1
    assert done["inferred_edges"] >= 1
    assert len(neo.created_nodes) == 2
    assert len(neo.created_edges) >= 1
