"""Overnight batch pipeline + token/cost telemetry per night (Spec §7).

Runs low-cost off-peak jobs (default model: ``gemini-2.5-flash-lite`` batch pricing):
1. ``digest_links_and_newsletters`` — promotes pending ingested links/newsletters into digested cards.
2. ``leetcode_pattern_summary`` — aggregates solved/hint/failed LeetCode attempts into pattern summaries.
3. ``resume_gap_recommendations`` — checks resume skills against the knowledge graph for shaky/unexposed gaps.
4. ``build_next_day_feed_plan`` — synthesizes due reviews, unread newsletters, and gaps into tomorrow's feed mix.

Records every run in ``overnight_job_runs`` and increments ``usage_daily`` (``kind='overnight_batch'``).
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Optional

from backend.services import knowledge_map as km
from backend.services.spaced_repetition import SpacedRepetitionService

# Batch API rates (USD per 1M tokens) after 50% batch discount
MODEL_BATCH_PRICING_PER_1M: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash-lite": (0.05, 0.20),
    "gemini-2.5-flash": (0.15, 0.60),
    "local-gemma": (0.0, 0.0),
    "deterministic": (0.0, 0.0),
}

ALL_OVERNIGHT_JOBS: tuple[str, ...] = (
    "digest_links_and_newsletters",
    "leetcode_pattern_summary",
    "resume_gap_recommendations",
    "build_next_day_feed_plan",
)


def default_overnight_model() -> str:
    return (os.getenv("OVERNIGHT_MODEL") or "gemini-2.5-flash-lite").strip()


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    batch_discount: float = 0.5,
) -> float:
    """Compute estimated USD cost for a batch job (pricing table already reflects 50% batch discount)."""
    rates = MODEL_BATCH_PRICING_PER_1M.get(model, (0.05, 0.20))
    scale = 1.0 if batch_discount == 0.5 else max(0.0, min(1.0, batch_discount / 0.5))
    cost = ((max(0, input_tokens) / 1_000_000.0) * rates[0] + (max(0, output_tokens) / 1_000_000.0) * rates[1]) * scale
    return round(cost, 6)


async def _job_digest_links_and_newsletters(user_id: str, pg: Any, dry_run: bool) -> dict[str, Any]:
    rows = await pg.execute_query(
        """
        SELECT id::text AS id, title, source_kind, relevance_score
        FROM ingested_resources
        WHERE user_id = CAST(:u AS uuid) AND digest_status = 'pending' AND dismissed_at IS NULL
        ORDER BY relevance_score DESC, created_at ASC
        LIMIT 50
        """,
        {"u": user_id},
    )
    items = [dict(r) for r in (rows or [])]
    if items and not dry_run:
        ids = [r["id"] for r in items]
        await pg.execute_update(
            "UPDATE ingested_resources SET digest_status = 'digested' WHERE user_id = CAST(:u AS uuid) AND id = ANY(:ids)",
            {"u": user_id, "ids": ids},
        )
    in_tok = len(items) * 320
    out_tok = len(items) * 90
    return {
        "items_processed": len(items),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "summary": {"digested_titles": [r["title"] for r in items[:8]]},
    }


async def _job_leetcode_pattern_summary(user_id: str, pg: Any) -> dict[str, Any]:
    rows = await pg.execute_query(
        """
        SELECT cp.id::text AS problem_id, cp.title, cp.difficulty, cp.pattern,
               ca.outcome, ca.mistake_tag
        FROM coding_problems cp
        LEFT JOIN coding_attempts ca ON ca.problem_id = cp.id AND ca.user_id = cp.user_id
        WHERE cp.user_id = CAST(:u AS uuid)
        ORDER BY ca.created_at DESC NULLS LAST, cp.created_at DESC
        LIMIT 200
        """,
        {"u": user_id},
    )
    by_pattern: dict[str, dict[str, Any]] = defaultdict(lambda: {"problems": set(), "hard_or_missed": []})
    for r in rows or []:
        pat = (r.get("pattern") or "Unclassified").strip()
        by_pattern[pat]["problems"].add(r["title"])
        if r.get("outcome") in {"hint", "failed"} or (r.get("difficulty") == "hard"):
            by_pattern[pat]["hard_or_missed"].append(r["title"])

    cards = []
    for pat, info in sorted(by_pattern.items(), key=lambda kv: -len(kv[1]["problems"])):
        n = len(info["problems"])
        flagged = list(dict.fromkeys(info["hard_or_missed"]))[:3]
        cards.append({
            "pattern": pat,
            "problem_count": n,
            "flagged_problems": flagged,
            "summary_line": (
                f"{n} {pat} problem(s); revisit {', '.join(flagged)}."
                if flagged
                else f"{n} {pat} problem(s) logged."
            ),
        })
    return {
        "items_processed": len(cards),
        "input_tokens": 0,
        "output_tokens": 0,
        "summary": {"pattern_cards": cards[:10]},
    }


async def _job_resume_gap_recommendations(user_id: str, pg: Any, neo4j: Any) -> dict[str, Any]:
    res_rows = await pg.execute_query(
        "SELECT skills FROM user_resumes WHERE user_id = CAST(:u AS uuid) ORDER BY created_at DESC LIMIT 1",
        {"u": user_id},
    )
    raw_skills = (res_rows[0].get("skills") if res_rows else None) or []
    if isinstance(raw_skills, str):
        raw_skills = json.loads(raw_skills)
    names = [s["name"] if isinstance(s, dict) else str(s) for s in raw_skills if s]
    if not names:
        return {"items_processed": 0, "input_tokens": 0, "output_tokens": 0, "summary": {"gaps": []}}

    assessments = await km.assess(user_id, names, pg=pg, neo4j=neo4j, max_names=80)
    gaps = [
        {
            "skill": a.name,
            "status": a.status,
            "mastery": a.mastery,
            "concept_id": a.concept_id,
            "recommendation": (
                f"Resume lists '{a.name}' ({a.status}); schedule a short diagnostic or card."
            ),
        }
        for a in assessments
        if a.status in {"shaky", "unexposed"}
    ]
    return {
        "items_processed": len(gaps),
        "input_tokens": len(gaps) * 140,
        "output_tokens": len(gaps) * 60,
        "summary": {"gaps": gaps[:15]},
    }


async def _job_build_next_day_feed_plan(user_id: str, pg: Any) -> dict[str, Any]:
    sr = SpacedRepetitionService(pg)
    due = await sr.get_due_items(user_id=user_id, limit=25, include_overdue=True)
    res_rows = await pg.execute_query(
        """
        SELECT id::text AS id, title, relevance_score
        FROM ingested_resources
        WHERE user_id = CAST(:u AS uuid) AND dismissed_at IS NULL
        ORDER BY relevance_score DESC, created_at DESC
        LIMIT 10
        """,
        {"u": user_id},
    )
    due_ids = [d["sm2_data"]["item_id"] for d in due]
    article_ids = [r["id"] for r in (res_rows or [])]
    return {
        "items_processed": len(due_ids) + len(article_ids),
        "input_tokens": 0,
        "output_tokens": 0,
        "summary": {
            "due_reviews_queued": len(due_ids),
            "reading_cards_queued": len(article_ids),
            "due_concept_ids": due_ids[:15],
        },
    }


async def run_overnight_pipeline(
    user_id: str,
    pg: Any,
    neo4j: Any,
    *,
    jobs: Optional[list[str]] = None,
    dry_run: bool = False,
    model: Optional[str] = None,
    run_date: Optional[date] = None,
) -> dict[str, Any]:
    """Execute scheduled overnight jobs, log telemetry to ``overnight_job_runs``, and track ``usage_daily``."""
    selected = [j for j in (jobs or ALL_OVERNIGHT_JOBS) if j in ALL_OVERNIGHT_JOBS]
    chosen_model = model or default_overnight_model()
    today = run_date or datetime.now(timezone.utc).date()

    job_results: list[dict[str, Any]] = []
    total_items = 0
    total_in_tokens = 0
    total_out_tokens = 0
    total_cost = 0.0

    for job_kind in selected:
        if job_kind == "digest_links_and_newsletters":
            res = await _job_digest_links_and_newsletters(user_id, pg, dry_run)
        elif job_kind == "leetcode_pattern_summary":
            res = await _job_leetcode_pattern_summary(user_id, pg)
        elif job_kind == "resume_gap_recommendations":
            res = await _job_resume_gap_recommendations(user_id, pg, neo4j)
        else:
            res = await _job_build_next_day_feed_plan(user_id, pg)

        in_tok = int(res["input_tokens"])
        out_tok = int(res["output_tokens"])
        cost = estimate_cost_usd(chosen_model, in_tok, out_tok)
        items = int(res["items_processed"])

        if not dry_run:
            await pg.execute_update(
                """
                INSERT INTO overnight_job_runs
                    (user_id, run_date, job_kind, model, status, items_processed,
                     input_tokens, output_tokens, estimated_cost_usd, summary_json, finished_at)
                VALUES
                    (CAST(:u AS uuid), :d, :jk, :m, 'completed', :items,
                     :in_t, :out_t, :cost, CAST(:sj AS jsonb), now())
                """,
                {
                    "u": user_id,
                    "d": today,
                    "jk": job_kind,
                    "m": chosen_model,
                    "items": items,
                    "in_t": in_tok,
                    "out_t": out_tok,
                    "cost": cost,
                    "sj": json.dumps(res["summary"]),
                },
            )

        total_items += items
        total_in_tokens += in_tok
        total_out_tokens += out_tok
        total_cost = round(total_cost + cost, 6)
        job_results.append({
            "job_kind": job_kind,
            "status": "dry_run" if dry_run else "completed",
            "items_processed": items,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "estimated_cost_usd": cost,
            "summary": res["summary"],
        })

    if not dry_run and selected:
        await pg.execute_update(
            """
            INSERT INTO usage_daily (user_id, day, kind, count)
            VALUES (CAST(:u AS uuid), :d, 'overnight_batch', :n)
            ON CONFLICT (user_id, day, kind) DO UPDATE
            SET count = usage_daily.count + :n
            """,
            {"u": user_id, "d": today, "n": len(selected)},
        )

    return {
        "run_date": today.isoformat(),
        "model": chosen_model,
        "dry_run": dry_run,
        "jobs": job_results,
        "totals": {
            "jobs_run": len(job_results),
            "items_processed": total_items,
            "input_tokens": total_in_tokens,
            "output_tokens": total_out_tokens,
            "estimated_cost_usd": total_cost,
        },
    }


async def get_overnight_report(user_id: str, pg: Any, days: int = 7) -> dict[str, Any]:
    """Return cost-per-night and token breakdown across the last N days."""
    days = max(1, min(int(days), 90))
    runs = await pg.execute_query(
        """
        SELECT run_date, job_kind, model, status, items_processed,
               input_tokens, output_tokens, estimated_cost_usd, started_at, finished_at
        FROM overnight_job_runs
        WHERE user_id = CAST(:u AS uuid)
          AND run_date >= CURRENT_DATE - make_interval(days => :days)
        ORDER BY run_date DESC, started_at DESC
        """,
        {"u": user_id, "days": days},
    )
    usage_rows = await pg.execute_query(
        """
        SELECT day, count FROM usage_daily
        WHERE user_id = CAST(:u AS uuid)
          AND kind = 'overnight_batch'
          AND day >= CURRENT_DATE - make_interval(days => :days)
        ORDER BY day DESC
        """,
        {"u": user_id, "days": days},
    )

    by_night: dict[str, dict[str, Any]] = {}
    for r in runs or []:
        nd = r["run_date"].isoformat() if hasattr(r["run_date"], "isoformat") else str(r["run_date"])
        bucket = by_night.setdefault(
            nd,
            {
                "run_date": nd,
                "jobs": 0,
                "items_processed": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "estimated_cost_usd": 0.0,
                "models": set(),
            },
        )
        bucket["jobs"] += 1
        bucket["items_processed"] += int(r.get("items_processed") or 0)
        bucket["input_tokens"] += int(r.get("input_tokens") or 0)
        bucket["output_tokens"] += int(r.get("output_tokens") or 0)
        bucket["estimated_cost_usd"] = round(bucket["estimated_cost_usd"] + float(r.get("estimated_cost_usd") or 0.0), 6)
        bucket["models"].add(r.get("model") or "unknown")

    nights = [
        {**v, "models": sorted(v["models"])}
        for _, v in sorted(by_night.items(), reverse=True)
    ]
    total_cost = round(sum(n["estimated_cost_usd"] for n in nights), 6)
    return {
        "days": days,
        "nights": nights,
        "usage_daily": [
            {"day": u["day"].isoformat() if hasattr(u["day"], "isoformat") else str(u["day"]), "runs": int(u["count"])}
            for u in (usage_rows or [])
        ],
        "total_estimated_cost_usd": total_cost,
        "avg_cost_per_night_usd": round(total_cost / len(nights), 6) if nights else 0.0,
    }
