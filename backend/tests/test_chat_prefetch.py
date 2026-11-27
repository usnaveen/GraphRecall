"""Prefetching the query embedding while the user types takes ~600 ms off the chat's critical path.
The prefetch must embed exactly what analyze_query_node will look up, follow-up anchoring included."""

import importlib
from unittest.mock import AsyncMock, patch

import pytest

cg = importlib.import_module("backend.graphs.chat_graph")


@pytest.mark.asyncio
async def test_prefetch_embeds_the_same_retrieval_query_the_turn_will_use():
    seen = []

    async def fake_embed(q):
        seen.append(q)
        return [0.1] * 8

    with patch.object(cg, "_embed_query_cached", side_effect=fake_embed):
        assert await cg.prefetch_query_embedding("How does multi-head attention work?") is True
        assert await cg.prefetch_query_embedding("what are its limitations?", previous_question="Explain LoRA") is True
    assert seen[0] == "How does multi-head attention work?"
    assert seen[1] != "what are its limitations?" and "LoRA" in seen[1]  # anchored like the real turn


@pytest.mark.asyncio
async def test_prefetch_skips_greetings_and_fragments():
    with patch.object(cg, "_embed_query_cached", AsyncMock()) as embed:
        assert await cg.prefetch_query_embedding("hi") is False
        assert await cg.prefetch_query_embedding("thanks!") is False
    embed.assert_not_called()
