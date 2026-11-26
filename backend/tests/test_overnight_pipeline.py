"""Tests for the Spec §7 overnight batch pipeline and cost/token reporting."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from backend.services.overnight_pipeline import (
    estimate_cost_usd,
    get_overnight_report,
    run_overnight_pipeline,
)


class _OvernightPG:
    def __init__(self):
        self.updates: list[tuple[str, dict]] = []
        self.runs: list[dict] = []
        self.usage: dict[tuple[str, str], int] = {}

    async def execute_query(self, query: str, params=None):
        params = params or {}
        if "FROM ingested_resources" in query:
            return [{"id": "ir-1", "title": "KV Cache Essay", "source_kind": "email_newsletter", "relevance_score": 1.4}]
        if "FROM coding_problems" in query:
            return [
                {"problem_id": "p1", "title": "146. LRU Cache", "difficulty": "medium", "pattern": "Hash Map", "outcome": "solved", "mistake_tag": None},
                {"problem_id": "p2", "title": "76. Minimum Window Substring", "difficulty": "hard", "pattern": "Sliding Window", "outcome": "failed", "mistake_tag": "edge_case"},
            ]
        if "FROM user_resumes" in query:
            return [{"skills": [{"name": "CUDA Kernels", "section": "Skills"}]}]
        if "ps.concept_id as item_id" in query:
            return [{
                "item_id": "c-kv",
                "item_type": "concept",
                "easiness_factor": 2.5,
                "interval": 1,
                "repetition": 1,
                "last_review": None,
                "next_review": datetime.now(timezone.utc),
                "total_reviews": 1,
                "correct_streak": 1,
                "mastery_score": 0.4,
            }]
        if "FROM overnight_job_runs" in query:
            return self.runs
        if "FROM usage_daily" in query:
            return [{"day": date(2026, 11, 27), "count": sum(self.usage.values())}]
        return []

    async def execute_update(self, query: str, params=None):
        params = params or {}
        self.updates.append((query, params))
        if "INSERT INTO overnight_job_runs" in query:
            self.runs.append({
                "run_date": params["d"],
                "job_kind": params["jk"],
                "model": params["m"],
                "status": "completed",
                "items_processed": params["items"],
                "input_tokens": params["in_t"],
                "output_tokens": params["out_t"],
                "estimated_cost_usd": params["cost"],
                "started_at": datetime.now(timezone.utc),
                "finished_at": datetime.now(timezone.utc),
            })
        elif "INSERT INTO usage_daily" in query:
            key = (str(params["d"]), params.get("k") or "overnight_batch")
            self.usage[key] = self.usage.get(key, 0) + int(params["n"])
        return []


class _OvernightNeo4j:
    async def execute_query(self, query: str, params=None):
        return []


def test_estimate_cost_usd_uses_flash_lite_batch_rates():
    cost = estimate_cost_usd("gemini-2.5-flash-lite", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.25, rel=1e-4)
    assert estimate_cost_usd("local-gemma", 100_000, 50_000) == 0.0


@pytest.mark.asyncio
async def test_run_overnight_pipeline_and_report():
    pg = _OvernightPG()
    neo = _OvernightNeo4j()
    res = await run_overnight_pipeline("user-1", pg, neo, run_date=date(2026, 11, 27))
    assert res["model"] == "gemini-2.5-flash-lite"
    assert res["totals"]["jobs_run"] == 4
    assert res["totals"]["items_processed"] >= 4
    assert len(pg.runs) == 4
    assert pg.usage[("2026-11-27", "overnight_batch")] == 4

    report = await get_overnight_report("user-1", pg, days=7)
    assert len(report["nights"]) == 1
    assert report["nights"][0]["jobs"] == 4
    assert report["total_estimated_cost_usd"] == res["totals"]["estimated_cost_usd"]
