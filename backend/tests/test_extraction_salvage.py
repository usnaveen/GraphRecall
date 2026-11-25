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


def test_salvage_ignores_null_concepts_and_other_arrays():
    assert salvage_concepts_json('{"concepts": null, "other": [{"a": 1}') is None


def test_odd_backslash_runs_and_more_latex_commands():
    raw = '{"q": "\\\\\\frac{a}{b} and \\bullet and \\textit{x} and \\sqrt{2}", "a": "ok"}'
    parsed = _parse_llm_json(SimpleNamespace(text=raw))
    assert "\x0c" not in parsed["q"] and "\x08" not in parsed["q"] and "\t" not in parsed["q"]
    assert "frac" in parsed["q"] and "bullet" in parsed["q"] and "textit" in parsed["q"]
