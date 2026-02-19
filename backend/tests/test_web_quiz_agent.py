"""Tests for WebQuizAgent result normalization."""

from backend.agents.web_quiz_agent import WebQuizAgent


def _agent_without_init() -> WebQuizAgent:
    return WebQuizAgent.__new__(WebQuizAgent)


def test_normalize_search_results_handles_json_string_envelope():
    agent = _agent_without_init()
    raw = '[{"url":"https://example.com","content":"Question bank content"}]'
    normalized = agent._normalize_search_results(raw)
    assert normalized == [{"url": "https://example.com", "content": "Question bank content"}]


def test_normalize_search_results_filters_non_dict_entries():
    agent = _agent_without_init()
    raw = ["bad", 123, {"snippet": "Useful content", "source": "https://example.org"}]
    normalized = agent._normalize_search_results(raw)
    assert normalized == [{"url": "https://example.org", "content": "Useful content"}]
