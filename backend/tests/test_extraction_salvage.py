"""Truncated extraction responses keep their complete concepts; LaTeX escapes don't break quiz JSON."""
from types import SimpleNamespace

from backend.agents.content_generator import _parse_llm_json
from backend.agents.extraction import salvage_concepts_json


def test_salvage_keeps_complete_objects_before_the_cut():
    text = '{\n  "concepts": [\n    {"name": "Attention", "definition": "weights"},\n    {"name": "RAG", "definition": "retrie'
    out = salvage_concepts_json(text)
    assert out["truncated"] and [c["name"] for c in out["concepts"]] == ["Attention"]
    assert salvage_concepts_json('{"concepts": [{"name": "x"') is None


def test_quiz_json_with_latex_backslashes_parses():
    raw = '{"question": "Why divide by \\\\sqrt{d_k}? Use \\frac{1}{2}", "answer": "scale"}'
    parsed = _parse_llm_json(SimpleNamespace(text=raw))
    assert "frac" in parsed["question"] and parsed["answer"] == "scale"
