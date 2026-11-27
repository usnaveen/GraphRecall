"""The answer prompt carries the learner's standing on the concepts it uses (strong / shaky /
seen / unexposed), so explanations build on what the user knows instead of starting from zero."""

from __future__ import annotations

import pytest

import importlib

cg = importlib.import_module("backend.graphs.chat_graph")


def test_block_groups_concepts_by_status_in_teaching_order():
    rows = [
        {"name": "Residual Connection", "status": "strong", "mastery": 0.75},
        {"name": "Multi-Head Attention", "status": "shaky", "mastery": 0.57},
        {"name": "Softmax", "status": "seen", "mastery": 0.35},
        {"name": "Layer Normalization", "status": "unexposed", "mastery": None},
    ]
    block = cg._learner_state_block(rows)
    assert block.splitlines() == [
        "- Knows well: Residual Connection",
        "- Shaky when tested: Multi-Head Attention",
        "- Studied, never tested: Softmax",
        "- Not met yet: Layer Normalization",
    ]
    assert "0.57" not in block  # scores stay out of the prompt


def test_system_prompt_tells_the_model_how_to_use_it():
    assert "<learner_state>" in cg.ANSWER_SYSTEM_PROMPT
    assert "Do not re-teach what they know well" in cg.ANSWER_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_learner_state_is_best_effort(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("neo4j down")

    from backend.services import knowledge_map as km
    monkeypatch.setattr(km, "assess", boom)
    assert await cg._learner_state("u1", [{"name": "Softmax"}]) == []
    assert await cg._learner_state("u1", []) == []


def test_answer_cache_tag_changes_with_the_prompt(monkeypatch):
    before = cg._answer_cache_tag()
    monkeypatch.setattr(cg, "ANSWER_SYSTEM_PROMPT", cg.ANSWER_SYSTEM_PROMPT + " ")
    assert cg._answer_cache_tag() != before
