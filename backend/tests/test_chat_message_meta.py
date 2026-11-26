"""What a chat answer keeps about its grounding: concept names and a short retrieval summary."""

from backend.routers.chat import message_meta


def test_keeps_names_and_summary_only():
    meta = message_meta(
        [{"id": "1", "name": "KV Cache", "score": 0.9}, {"name": "KV Cache"}, "Beam Search", {"name": " "}],
        {"intent": "explain", "documents_retrieved": 3, "nodes_retrieved": 15,
         "entities": ["kv cache", 7], "retrieval_stats": {"secret": 1}, "grounding": {"max_score": 0.8}},
    )
    assert meta["related_concepts"] == ["KV Cache", "Beam Search"]
    assert meta["retrieval"] == {"intent": "explain", "documents": 3, "concepts": 15, "entities": ["kv cache"]}


def test_empty_inputs():
    assert message_meta([], {}) == {"related_concepts": [], "retrieval": {"intent": None, "documents": None, "concepts": None, "entities": []}}
