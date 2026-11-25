"""Trained intent router: numpy runtime parity, mention matching, and the chat-graph decision paths."""
import asyncio
import importlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from langchain_core.messages import HumanMessage

cg = importlib.import_module("backend.graphs.chat_graph")  # the package re-exports a compiled graph under this name
from backend.services.intent_router import model as im
from backend.services.intent_router import router as ir
from backend.services.intent_router.routing import ROUTE_GROUP

ART = Path(im.__file__).parent / "artifacts"


def test_artifact_reproduces_recorded_probabilities():
    """Regression check against probabilities recorded at training time. train.py itself asserts the
    numpy runtime matches sklearn (< 1e-6) before writing the artifact and this fixture."""
    clf = im.IntentClassifier.load(ART / "intent_tfidf_lr.json")
    fixture = json.loads((ART / "parity_fixture.json").read_text())
    assert fixture
    for row in fixture:
        got = clf.predict_proba(row["text"])
        assert np.abs(got - np.asarray(row["probs"])).max() < 1e-6, row["text"]


def test_classifier_basic_predictions():
    clf = im.get_classifier()
    assert clf is not None and set(clf.classes) == set(ROUTE_GROUP)
    assert clf.predict("quiz me on binary search").intent == "quiz"
    assert clf.predict("BFS vs DFS").intent == "compare"
    p = clf.predict("what should I learn before transformers")
    assert p.intent == "path" and abs(sum(p.probs.values()) - 1) < 1e-9


def test_char_ngrams_match_sklearn_short_word_rule():
    # A word shorter than n is emitted once (sklearn's char_wb behaviour), then longer n are skipped.
    assert im._char_wb_ngrams("a", 2, 5) == [" a", "a ", " a "]


def test_filter_mentions_word_boundaries_and_nesting():
    names = ["art", "Self-Attention", "attention", "LoRA", "BFS"]
    got = ir.filter_mentions("how does self-attention differ from LoRA? starting out", names)
    assert got == ["Self-Attention", "LoRA"]  # "art" only inside "starting"; "attention" nested


def test_router_mode_env(monkeypatch):
    monkeypatch.setenv("CHAT_INTENT_ROUTER", "shadow")
    assert ir.router_mode() == "shadow"
    monkeypatch.setenv("CHAT_INTENT_ROUTER", "bogus")
    assert ir.router_mode() == "model"


class _Embedder:
    async def aembed_query(self, text, **kw):
        return [0.1] * 8


def _patches(fake_llm):
    return (
        patch.object(cg, "get_embeddings", return_value=_Embedder()),
        patch.object(cg, "get_embedding_dims", return_value=8),
        patch.object(cg, "get_fast_model", return_value=fake_llm),
    )


def _llm(intent="explain", entities=None, fail=False):
    llm = MagicMock()
    if fail:
        llm.with_structured_output.return_value.ainvoke = AsyncMock(side_effect=asyncio.TimeoutError())
    else:
        llm.with_structured_output.return_value.ainvoke = AsyncMock(
            return_value=cg.QueryAnalysis(intent=intent, entities=entities or []))
    return llm


async def test_model_mode_skips_llm_when_confident(monkeypatch):
    monkeypatch.setenv("CHAT_INTENT_ROUTER", "model")
    monkeypatch.setenv("CHAT_INTENT_THRESHOLD", "0.3")
    cg._QUERY_EMBED_CACHE.clear()
    assert im.get_classifier().predict("quiz me on binary search").confidence >= 0.8  # quiz bar
    llm = _llm()
    logged = []
    a, b, c = _patches(llm)
    with a, b, c, patch.object(ir, "mentioned_concepts", AsyncMock(return_value=["binary search"])), \
         patch.object(ir, "log_decision", side_effect=lambda **kw: logged.append(kw)):
        out = await cg.analyze_query_node({"messages": [HumanMessage(content="quiz me on binary search")],
                                           "user_id": "u1"})
    assert out == {"intent": "quiz", "entities": ["binary search"], "router_source": "model"}
    llm.with_structured_output.return_value.ainvoke.assert_not_called()
    assert logged[0]["source"] == "model" and logged[0]["model_intent"] == "quiz"


async def test_model_mode_falls_back_when_unsure(monkeypatch):
    monkeypatch.setenv("CHAT_INTENT_ROUTER", "model")
    monkeypatch.setenv("CHAT_INTENT_THRESHOLD", "1.01")  # nothing is this confident
    cg._QUERY_EMBED_CACHE.clear()
    llm = _llm("compare", ["BFS", "DFS"])
    logged = []
    a, b, c = _patches(llm)
    with a, b, c, patch.object(ir, "mentioned_concepts", AsyncMock(return_value=[])), \
         patch.object(ir, "log_decision", side_effect=lambda **kw: logged.append(kw)):
        out = await cg.analyze_query_node({"messages": [HumanMessage(content="BFS vs DFS")], "user_id": "u1"})
    assert out == {"intent": "compare", "entities": ["BFS", "DFS"], "router_source": "fallback"}
    assert logged[0]["llm_intent"] == "compare" and logged[0]["model_intent"] is not None


async def test_quiz_without_known_topic_asks_llm_for_topic(monkeypatch):
    monkeypatch.setenv("CHAT_INTENT_ROUTER", "model")
    monkeypatch.setenv("CHAT_INTENT_THRESHOLD", "0.0")
    cg._QUERY_EMBED_CACHE.clear()
    llm = _llm("quiz", ["Krebs cycle"])
    a, b, c = _patches(llm)
    with a, b, c, patch.object(ir, "mentioned_concepts", AsyncMock(return_value=[])), \
         patch.object(ir, "log_decision"):
        out = await cg.analyze_query_node({"messages": [HumanMessage(content="quiz me on the Krebs cycle please")],
                                           "user_id": "u1"})
    assert out["entities"] == ["Krebs cycle"] and out["router_source"] == "fallback"


async def test_llm_failure_uses_model_guess(monkeypatch):
    monkeypatch.setenv("CHAT_INTENT_ROUTER", "model")
    monkeypatch.setenv("CHAT_INTENT_THRESHOLD", "1.01")
    cg._QUERY_EMBED_CACHE.clear()
    a, b, c = _patches(_llm(fail=True))
    with a, b, c, patch.object(ir, "mentioned_concepts", AsyncMock(return_value=[])), \
         patch.object(ir, "log_decision"):
        out = await cg.analyze_query_node({"messages": [HumanMessage(content="show me a diagram of the heart")],
                                           "user_id": "u1"})
    assert out["intent"] == "show_images" and out["router_source"] == "model"


async def test_shadow_mode_lets_llm_decide(monkeypatch):
    monkeypatch.setenv("CHAT_INTENT_ROUTER", "shadow")
    cg._QUERY_EMBED_CACHE.clear()
    logged = []
    a, b, c = _patches(_llm("find", ["Raft"]))
    with a, b, c, patch.object(ir, "log_decision", side_effect=lambda **kw: logged.append(kw)):
        out = await cg.analyze_query_node({"messages": [HumanMessage(content="what did I write about Raft")],
                                           "user_id": "u1"})
    assert out == {"intent": "find", "entities": ["Raft"], "router_source": "llm"}
    assert logged[0]["source"] == "llm" and logged[0]["model_intent"] is not None


async def test_log_decision_never_raises_without_db(monkeypatch):
    monkeypatch.setenv("CHAT_INTENT_LOG", "1")
    with patch("backend.db.postgres_client.get_postgres_client", AsyncMock(side_effect=RuntimeError("no db"))):
        ir.log_decision(user_id="u1", query="q", intent="general", source="model")
        await asyncio.sleep(0)
        await asyncio.gather(*list(ir._PENDING), return_exceptions=True)


def test_quiz_needs_higher_confidence():
    assert ir.threshold_for("quiz", 0.6) == 0.8
    assert ir.threshold_for("explain", 0.6) == 0.6


@pytest.mark.parametrize("router_source,intent,expect_vector_seeds", [
    ("model", "explain", True),     # no LLM entities, so seed from the query embedding
    ("model", "general", False),    # chit-chat stays off the graph, as it did with the LLM router
    ("llm", "explain", False),      # LLM path unchanged (substring seeds only unless GRAPH_SEED_MODE=hybrid)
])
async def test_context_vector_seeds_follow_router_source(monkeypatch, router_source, intent, expect_vector_seeds):
    monkeypatch.delenv("GRAPH_SEED_MODE", raising=False)
    cg._QUERY_EMBED_CACHE.clear()
    embedder = MagicMock()
    embedder.aembed_query = AsyncMock(return_value=[0.1] * 8)
    pg = AsyncMock()
    pg.execute_query = AsyncMock(return_value=[])
    neo = AsyncMock()
    neo.find_seed_concepts = AsyncMock(return_value=[])
    neo.execute_query = AsyncMock(return_value=[])
    sim = AsyncMock(return_value=[])
    with patch.object(cg, "get_embeddings", return_value=embedder), \
         patch.object(cg, "get_embedding_dims", return_value=8), \
         patch.object(cg, "get_postgres_client", new=AsyncMock(return_value=pg)), \
         patch.object(cg, "get_neo4j_client", new=AsyncMock(return_value=neo)), \
         patch("backend.services.concept_similarity.similar_to_embedding", sim):
        await cg.get_context_node({
            "user_id": "u1", "intent": intent, "entities": [], "router_source": router_source,
            "messages": [HumanMessage(content="how does self-attention work")],
        })
    assert sim.await_count == (1 if expect_vector_seeds else 0)
