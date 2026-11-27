"""Online quality signals: per-answer outcome taxonomy, thumbs up/down, and the summary endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from backend.routers import chat as chat_router


def test_outcomes_name_what_went_wrong():
    md = {"documents_retrieved": 0, "nodes_retrieved": 0, "cache_hit": True,
          "grounding": {"should_abstain": True, "invalid_refs": ["9"]}, "rerank_stats": {"method": "lexical"}}
    assert chat_router.answer_outcomes(md) == ["no_retrieval", "abstained", "citations_stripped",
                                               "reranker_fallback", "cache_hit"]
    healthy = {"documents_retrieved": 4, "nodes_retrieved": 9, "grounding": {"should_abstain": False, "invalid_refs": []},
               "rerank_stats": {"method": "onnx_cross_encoder"}}
    assert chat_router.answer_outcomes(healthy) == []


def test_message_meta_carries_outcomes():
    meta = chat_router.message_meta([], {"prompt_version": "p1", "grounding": {"should_abstain": True}})
    assert meta["generation"]["outcomes"] == ["abstained"]


def test_quality_summary_compares_prompt_versions():
    metas = [
        {"generation": {"prompt_version": "a", "outcomes": ["abstained"]}, "feedback": {"rating": "down"}},
        {"generation": {"prompt_version": "a", "outcomes": []}, "feedback": {"rating": "up"}},
        {"generation": {"prompt_version": "b", "outcomes": ["citations_stripped"]}},
        '{"generation": {"prompt_version": "b"}, "feedback": {"rating": "up"}}',
        None,
    ]
    out = chat_router.summarize_quality(metas)
    assert out["overall"]["answers"] == 5 and out["overall"]["up"] == 2 and out["overall"]["down"] == 1
    assert out["by_prompt_version"]["a"]["thumbs_down_rate"] == 0.5
    assert out["by_prompt_version"]["b"]["outcome_rates"] == {"citations_stripped": 0.5}
    assert out["by_prompt_version"]["unversioned"]["answers"] == 1


@pytest.mark.asyncio
async def test_feedback_is_owner_scoped_and_404s_otherwise():
    pg = AsyncMock()
    pg.execute_query = AsyncMock(return_value=[])
    with patch.object(chat_router, "get_postgres_client", AsyncMock(return_value=pg)):
        with pytest.raises(HTTPException) as e:
            await chat_router.answer_feedback("m1", chat_router.AnswerFeedback(rating="down", reason="wrong"),
                                              current_user={"id": "u1"})
    assert e.value.status_code == 404
    sql, params = pg.execute_query.call_args.args
    assert "cc.user_id = :user_id" in sql and params["user_id"] == "u1"
    assert "cm.role = 'assistant'" in sql


def test_feedback_rejects_unknown_ratings():
    with pytest.raises(Exception):
        chat_router.AnswerFeedback(rating="meh")
