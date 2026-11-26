"""Tests verifying Tavily web search skips quietly when TAVILY_API_KEY is missing."""

import pytest


@pytest.mark.asyncio
async def test_web_quiz_agent_skips_when_tavily_key_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy")

    from backend.agents.web_quiz_agent import WebQuizAgent

    agent = WebQuizAgent()
    assert agent.search is None
    questions, url = await agent.find_quizzes("KV Cache", "ML Systems")
    assert questions == [] and url == ""


@pytest.mark.asyncio
async def test_research_agent_skips_quietly_without_tavily_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy")

    from backend.agents.research_agent import WebResearchAgent

    agent = WebResearchAgent(neo4j_client=None, pg_client=None)
    assert agent.search_tool is None
    results = await agent.search_web("Speculative Decoding")
    assert results == []


@pytest.mark.asyncio
async def test_graphs_skip_tavily_without_error_text(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy")

    import importlib

    quiz_graph = importlib.import_module("backend.graphs.quiz_graph")
    research_graph = importlib.import_module("backend.graphs.research_graph")

    assert await quiz_graph.web_search_for_topic.ainvoke("KV Cache") == ""
    res = await quiz_graph.research_node({"topic": "KV Cache"})
    assert res == {"research_results": []}
    assert await research_graph.search_web.ainvoke("KV Cache") == ""
