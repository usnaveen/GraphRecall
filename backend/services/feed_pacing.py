"""ADHD-friendly daily concept pacing & working-memory anti-overwhelm budget.

Cognitive Load Theory (Cowan's 4±1 / Miller's 7±2) shows that exposing a learner to
20–40 unrelated concepts in a single session induces context-switching fatigue and
choice paralysis. This module:
1. Tracks which concepts have been *shown* (impressions) and *graded* per user today
   (backed by `daily_concept_exposures` + `study_sessions` in Postgres, with a safe
   in-memory mirror when running offline or prior to migration `032`).
2. Bounds each day's active focus window to `daily_concept_cap` distinct concepts
   (default 7), continuing unmastered concepts started earlier today before opening
   new ones, and preferring graph-connected neighbors so the day's slate coheres.
3. Caps per-concept repetition within a single feed pull (`max_cards_per_concept = 3`)
   so MMR can space multiple modalities (Showcase -> Term Card -> MCQ) without
   back-to-back monotony.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Optional, Sequence

import structlog

logger = structlog.get_logger()

DEFAULT_DAILY_CONCEPT_CAP = 7
MIN_DAILY_CONCEPT_CAP = 3
MAX_DAILY_CONCEPT_CAP = 25
DEFAULT_MAX_CARDS_PER_CONCEPT = 3
STRETCH_UNLOCK_BATCH = 2


@dataclass
class DailyConceptEntry:
    """State of a single concept shown or reviewed by a user on a given day."""

    concept_id: str
    concept_name: Optional[str] = None
    domain: Optional[str] = None
    shown_count: int = 0
    graded_count: int = 0
    last_difficulty: Optional[str] = None

    @property
    def is_consolidated_today(self) -> bool:
        """True once the user rated it Easy today, or Good/Easy at least twice today."""
        if self.last_difficulty == "easy":
            return True
        if self.last_difficulty == "good" and self.graded_count >= 2:
            return True
        return False


@dataclass
class DailyConceptLedger:
    """Snapshot of all concepts shown or reviewed for `(user_id, exposure_date)`."""

    user_id: str
    exposure_date: date
    daily_concept_cap: int = DEFAULT_DAILY_CONCEPT_CAP
    entries: OrderedDict[str, DailyConceptEntry] = field(default_factory=OrderedDict)

    @property
    def shown_concept_ids(self) -> list[str]:
        return list(self.entries.keys())

    @property
    def active_unconsolidated_ids(self) -> list[str]:
        return [
            cid for cid, entry in self.entries.items() if not entry.is_consolidated_today
        ]

    @property
    def consolidated_ids(self) -> list[str]:
        return [
            cid for cid, entry in self.entries.items() if entry.is_consolidated_today
        ]

    @property
    def effective_cap(self) -> int:
        """If the user has consolidated every concept in today's cap, unlock a small +2 stretch
        window so the feed never dead-ends for hyperfocus sessions while still pacing intake."""
        base = max(MIN_DAILY_CONCEPT_CAP, min(MAX_DAILY_CONCEPT_CAP, int(self.daily_concept_cap)))
        if len(self.entries) >= base and not self.active_unconsolidated_ids:
            return min(MAX_DAILY_CONCEPT_CAP, len(self.entries) + STRETCH_UNLOCK_BATCH)
        return base


class InMemoryDailyExposureStore:
    """Bounded process-local fallback mirror keyed by `(user_id, YYYY-MM-DD)`."""

    def __init__(self, max_Buckets: int = 512) -> None:
        self._max_buckets = max_Buckets
        self._buckets: OrderedDict[tuple[str, str], OrderedDict[str, DailyConceptEntry]] = OrderedDict()

    def clear(self) -> None:
        self._buckets.clear()

    def get_bucket(self, user_id: str, day: date) -> OrderedDict[str, DailyConceptEntry]:
        key = (str(user_id), day.isoformat())
        bucket = self._buckets.get(key)
        if bucket is None:
            return OrderedDict()
        self._buckets.move_to_end(key)
        return OrderedDict(
            (
                cid,
                DailyConceptEntry(
                    concept_id=e.concept_id,
                    concept_name=e.concept_name,
                    domain=e.domain,
                    shown_count=e.shown_count,
                    graded_count=e.graded_count,
                    last_difficulty=e.last_difficulty,
                ),
            )
            for cid, e in bucket.items()
        )

    def record_impressions(
        self,
        user_id: str,
        day: date,
        concepts: Sequence[tuple[str, Optional[str], Optional[str]]],
    ) -> None:
        if not concepts:
            return
        key = (str(user_id), day.isoformat())
        bucket = self._buckets.setdefault(key, OrderedDict())
        self._buckets.move_to_end(key)
        while len(self._buckets) > self._max_buckets:
            self._buckets.popitem(last=False)

        seen_in_pull: set[str] = set()
        for cid, cname, domain in concepts:
            if not cid or cid.startswith("cold_start_") or cid.startswith("demo-"):
                continue
            if cid in seen_in_pull:
                continue
            seen_in_pull.add(cid)
            entry = bucket.get(cid)
            if entry is None:
                bucket[cid] = DailyConceptEntry(
                    concept_id=cid,
                    concept_name=cname,
                    domain=domain,
                    shown_count=1,
                )
            else:
                entry.shown_count += 1
                if cname and not entry.concept_name:
                    entry.concept_name = cname
                if domain and not entry.domain:
                    entry.domain = domain

    def record_review(
        self,
        user_id: str,
        day: date,
        concept_id: str,
        difficulty: str,
        concept_name: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> None:
        if not concept_id or concept_id.startswith("cold_start_") or concept_id.startswith("demo-"):
            return
        key = (str(user_id), day.isoformat())
        bucket = self._buckets.setdefault(key, OrderedDict())
        self._buckets.move_to_end(key)
        while len(self._buckets) > self._max_buckets:
            self._buckets.popitem(last=False)

        norm_diff = (difficulty or "good").strip().lower()
        entry = bucket.get(concept_id)
        if entry is None:
            bucket[concept_id] = DailyConceptEntry(
                concept_id=concept_id,
                concept_name=concept_name,
                domain=domain,
                shown_count=1,
                graded_count=1,
                last_difficulty=norm_diff,
            )
        else:
            entry.graded_count += 1
            entry.last_difficulty = norm_diff
            if concept_name and not entry.concept_name:
                entry.concept_name = concept_name
            if domain and not entry.domain:
                entry.domain = domain


_MEMORY_STORE = InMemoryDailyExposureStore()


def get_memory_exposure_store() -> InMemoryDailyExposureStore:
    return _MEMORY_STORE


def resolve_daily_concept_cap(user_settings: Optional[dict[str, Any]] = None) -> int:
    """Resolve user or environment daily active-concept cap, clamped to [3, 25]."""
    raw: Any = None
    if isinstance(user_settings, dict):
        raw = user_settings.get("daily_concept_cap")
    if raw is None:
        raw = os.getenv("FEED_DAILY_CONCEPT_CAP", str(DEFAULT_DAILY_CONCEPT_CAP))
    try:
        val = int(raw)
    except (TypeError, ValueError):
        val = DEFAULT_DAILY_CONCEPT_CAP
    return max(MIN_DAILY_CONCEPT_CAP, min(MAX_DAILY_CONCEPT_CAP, val))


def _utc_today(now: Optional[datetime] = None) -> date:
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    else:
        ref = ref.astimezone(timezone.utc)
    return ref.date()


async def load_daily_concept_ledger(
    pg_client: Any,
    user_id: str,
    daily_concept_cap: Optional[int] = None,
    now: Optional[datetime] = None,
    memory_store: Optional[InMemoryDailyExposureStore] = None,
) -> DailyConceptLedger:
    """Load today's concept exposure + review ledger for `user_id`."""
    day = _utc_today(now)
    cap = (
        resolve_daily_concept_cap()
        if daily_concept_cap is None
        else max(MIN_DAILY_CONCEPT_CAP, min(MAX_DAILY_CONCEPT_CAP, int(daily_concept_cap)))
    )
    store = memory_store or _MEMORY_STORE
    entries = store.get_bucket(user_id, day)

    if pg_client is not None:
        # 1. Read explicit impression + review rows from `daily_concept_exposures` (migration 032)
        try:
            rows = await pg_client.execute_query(
                """
                SELECT concept_id, concept_name, domain, shown_count, graded_count, last_difficulty
                FROM daily_concept_exposures
                WHERE user_id = CAST(:uid AS uuid)
                  AND exposure_date = :day
                ORDER BY first_shown_at ASC
                """,
                {"uid": user_id, "day": day},
            )
            for row in rows or []:
                cid = str(row.get("concept_id") or "").strip()
                if not cid:
                    continue
                existing = entries.get(cid)
                shown = max(int(row.get("shown_count") or 0), existing.shown_count if existing else 0)
                graded = max(int(row.get("graded_count") or 0), existing.graded_count if existing else 0)
                last_diff = row.get("last_difficulty") or (existing.last_difficulty if existing else None)
                entries[cid] = DailyConceptEntry(
                    concept_id=cid,
                    concept_name=row.get("concept_name") or (existing.concept_name if existing else None),
                    domain=row.get("domain") or (existing.domain if existing else None),
                    shown_count=max(1, shown),
                    graded_count=graded,
                    last_difficulty=last_diff,
                )
        except Exception:
            # Table may not exist yet or pg_client is a test mock; fall back cleanly.
            pass

        # 2. Also fold in any graded `study_sessions` rows from today so reviews recorded
        # through legacy paths still count toward today's working-memory ledger.
        try:
            day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            session_rows = await pg_client.execute_query(
                """
                SELECT concept_id,
                       COUNT(*) AS cnt,
                       (ARRAY_AGG(interaction_type ORDER BY reviewed_at DESC))[1] AS latest_interaction,
                       (ARRAY_AGG(is_correct ORDER BY reviewed_at DESC))[1] AS latest_correct
                FROM study_sessions
                WHERE user_id = :uid
                  AND concept_id IS NOT NULL
                  AND reviewed_at >= :day_start
                GROUP BY concept_id
                """,
                {"uid": user_id, "day_start": day_start},
            )
            for row in session_rows or []:
                cid = str(row.get("concept_id") or "").strip()
                if not cid:
                    continue
                cnt = int(row.get("cnt") or 0)
                itype = str(row.get("latest_interaction") or "")
                inferred_diff: Optional[str] = None
                if itype.startswith("review:"):
                    inferred_diff = itype.split(":", 1)[1].strip().lower()
                elif row.get("latest_correct") is True:
                    inferred_diff = "good"
                elif row.get("latest_correct") is False:
                    inferred_diff = "again"

                existing = entries.get(cid)
                if existing is None:
                    entries[cid] = DailyConceptEntry(
                        concept_id=cid,
                        shown_count=max(1, cnt),
                        graded_count=cnt,
                        last_difficulty=inferred_diff,
                    )
                else:
                    existing.graded_count = max(existing.graded_count, cnt)
                    existing.shown_count = max(existing.shown_count, existing.graded_count)
                    if inferred_diff and not existing.last_difficulty:
                        existing.last_difficulty = inferred_diff
        except Exception:
            pass

    return DailyConceptLedger(
        user_id=user_id,
        exposure_date=day,
        daily_concept_cap=cap,
        entries=entries,
    )


async def record_feed_impressions(
    pg_client: Any,
    user_id: str,
    items: Sequence[Any],
    now: Optional[datetime] = None,
    memory_store: Optional[InMemoryDailyExposureStore] = None,
) -> list[str]:
    """Record distinct concepts shown in a `/api/feed` response for today."""
    day = _utc_today(now)
    store = memory_store or _MEMORY_STORE

    seen: OrderedDict[str, tuple[str, Optional[str], Optional[str]]] = OrderedDict()
    for item in items:
        cid = getattr(item, "concept_id", None)
        if not cid or cid.startswith("cold_start_") or cid.startswith("demo-"):
            continue
        if cid not in seen:
            seen[cid] = (
                cid,
                getattr(item, "concept_name", None),
                getattr(item, "domain", None),
            )

    concept_tuples = list(seen.values())
    if not concept_tuples:
        return []

    store.record_impressions(user_id, day, concept_tuples)

    if pg_client is not None:
        for cid, cname, domain in concept_tuples:
            try:
                await pg_client.execute_update(
                    """
                    INSERT INTO daily_concept_exposures
                        (user_id, exposure_date, concept_id, concept_name, domain, shown_count, first_shown_at, last_shown_at)
                    VALUES
                        (CAST(:uid AS uuid), :day, :cid, :cname, :domain, 1, NOW(), NOW())
                    ON CONFLICT (user_id, exposure_date, concept_id)
                    DO UPDATE SET
                        shown_count = daily_concept_exposures.shown_count + 1,
                        concept_name = COALESCE(EXCLUDED.concept_name, daily_concept_exposures.concept_name),
                        domain = COALESCE(EXCLUDED.domain, daily_concept_exposures.domain),
                        last_shown_at = NOW()
                    """,
                    {
                        "uid": user_id,
                        "day": day,
                        "cid": cid,
                        "cname": cname,
                        "domain": domain,
                    },
                )
            except Exception:
                # Non-fatal if migration 032 isn't applied or pg_client is a mock
                break

    return list(seen.keys())


async def record_daily_concept_review(
    pg_client: Any,
    user_id: str,
    concept_id: str,
    difficulty: str,
    concept_name: Optional[str] = None,
    domain: Optional[str] = None,
    now: Optional[datetime] = None,
    memory_store: Optional[InMemoryDailyExposureStore] = None,
) -> None:
    """Record a concept grade in today's daily exposure ledger."""
    if not concept_id or concept_id.startswith("cold_start_") or concept_id.startswith("demo-"):
        return
    day = _utc_today(now)
    norm_diff = (difficulty or "good").strip().lower()
    store = memory_store or _MEMORY_STORE
    store.record_review(user_id, day, concept_id, norm_diff, concept_name=concept_name, domain=domain)

    if pg_client is not None:
        try:
            await pg_client.execute_update(
                """
                INSERT INTO daily_concept_exposures
                    (user_id, exposure_date, concept_id, concept_name, domain,
                     shown_count, graded_count, last_difficulty, first_shown_at, last_shown_at)
                VALUES
                    (CAST(:uid AS uuid), :day, :cid, :cname, :domain,
                     1, 1, :diff, NOW(), NOW())
                ON CONFLICT (user_id, exposure_date, concept_id)
                DO UPDATE SET
                    graded_count = daily_concept_exposures.graded_count + 1,
                    last_difficulty = EXCLUDED.last_difficulty,
                    concept_name = COALESCE(EXCLUDED.concept_name, daily_concept_exposures.concept_name),
                    domain = COALESCE(EXCLUDED.domain, daily_concept_exposures.domain),
                    last_shown_at = NOW()
                """,
                {
                    "uid": user_id,
                    "day": day,
                    "cid": concept_id,
                    "cname": concept_name,
                    "domain": domain,
                    "diff": norm_diff,
                },
            )
        except Exception:
            pass


def _concept_priority(concept: dict[str, Any]) -> float:
    raw = concept.get("priority_score")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    sm2 = concept.get("sm2_data") or {}
    if sm2.get("priority_score") is not None:
        try:
            return float(sm2["priority_score"])
        except (TypeError, ValueError):
            pass
    return 0.5


def _neighbor_names(concept: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("related_concepts", "prerequisites"):
        vals = concept.get(key) or []
        if isinstance(vals, (list, tuple, set)):
            for v in vals:
                if isinstance(v, str) and v.strip():
                    names.add(v.strip().lower())
    return names


def select_daily_focus_concepts(
    due_concepts: Sequence[dict[str, Any]],
    ledger: DailyConceptLedger,
) -> list[dict[str, Any]]:
    """Bound `due_concepts` to today's working-memory concept budget (`ledger.effective_cap`).

    Selection rules:
    1. Keep unmastered concepts already opened today (`ledger.active_unconsolidated_ids`)
       so the user finishes consolidating them before opening brand-new topics.
    2. Exclude concepts already consolidated today (`Easy`, or `Good` >= 2x) unless no
       other concepts remain in `due_concepts`.
    3. Fill remaining budget slots (`effective_cap - len(shown_today)`) by combining
       spaced-repetition urgency with a coherence bonus (+0.25 for direct graph neighbor,
       +0.10 for shared domain) so today's concepts form a connected cluster rather than
       7 disjoint context switches.
    """
    if not due_concepts:
        return []

    cap = ledger.effective_cap
    by_id: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for c in due_concepts:
        cid = str(c.get("id") or "").strip()
        if cid and cid not in by_id:
            by_id[cid] = c

    if not by_id:
        return list(due_concepts)[:cap]

    consolidated_set = set(ledger.consolidated_ids)
    active_today_ids = [cid for cid in ledger.active_unconsolidated_ids if cid in by_id]

    selected_ids: list[str] = list(active_today_ids[:cap])
    selected_set: set[str] = set(selected_ids)

    # How many *new* distinct concepts may still enter today's ledger?
    already_counted_today = set(ledger.shown_concept_ids)
    remaining_new_budget = max(0, cap - len(already_counted_today))
    # Also ensure the returned focus list can reach up to `cap` if today's earlier concepts
    # aren't in `due_concepts` anymore, without exceeding `remaining_new_budget` unseen ones
    # unless `selected_ids` would otherwise be empty!
    if not selected_ids and remaining_new_budget == 0:
        # User already touched `cap` concepts today, none of which are in `due_concepts`
        # (e.g. their intervals moved to tomorrow). Allow a gentle 2-concept continuation
        # rather than returning an empty feed.
        remaining_new_budget = min(STRETCH_UNLOCK_BATCH, cap)

    unseen_candidates = [
        c
        for cid, c in by_id.items()
        if cid not in selected_set and cid not in consolidated_set and cid not in already_counted_today
    ]

    if unseen_candidates and remaining_new_budget > 0:
        # Normalize base priority into [0, 1] so the coherence bonus has predictable scale
        priorities = {str(c["id"]): _concept_priority(c) for c in unseen_candidates}
        p_min = min(priorities.values())
        p_max = max(priorities.values())
        p_span = max(p_max - p_min, 1e-6)

        selected_names: set[str] = set()
        selected_neighbors: set[str] = set()
        selected_domains: set[str] = set()
        for cid in selected_ids:
            sc = by_id[cid]
            if sc.get("name"):
                selected_names.add(str(sc["name"]).strip().lower())
            selected_neighbors.update(_neighbor_names(sc))
            if sc.get("domain"):
                selected_domains.add(str(sc["domain"]).strip().lower())

        pool = list(unseen_candidates)
        added_new = 0
        while pool and added_new < remaining_new_budget and len(selected_ids) < cap:
            best_idx = 0
            best_score = -float("inf")
            for idx, cand in enumerate(pool):
                cid = str(cand["id"])
                norm_p = (priorities[cid] - p_min) / p_span if len(priorities) > 1 else 1.0
                cname = str(cand.get("name") or "").strip().lower()
                c_neighbors = _neighbor_names(cand)
                cdomain = str(cand.get("domain") or "").strip().lower()

                coherence = 0.0
                if selected_ids:
                    is_graph_neighbor = (
                        (cname and cname in selected_neighbors)
                        or bool(c_neighbors & selected_names)
                    )
                    if is_graph_neighbor:
                        coherence += 0.25
                    elif cdomain and cdomain in selected_domains:
                        coherence += 0.10

                total = norm_p + coherence
                if total > best_score + 1e-9:
                    best_score = total
                    best_idx = idx

            chosen = pool.pop(best_idx)
            cid = str(chosen["id"])
            selected_ids.append(cid)
            selected_set.add(cid)
            added_new += 1
            if chosen.get("name"):
                selected_names.add(str(chosen["name"]).strip().lower())
            selected_neighbors.update(_neighbor_names(chosen))
            if chosen.get("domain"):
                selected_domains.add(str(chosen["domain"]).strip().lower())

    # Fallback: if every candidate was already consolidated today, return up to `cap` of them
    # so an explicit review refresh still shows cards rather than an empty screen.
    if not selected_ids:
        selected_ids = list(by_id.keys())[:cap]

    return [by_id[cid] for cid in selected_ids if cid in by_id]


def cap_cards_per_concept(
    items: Sequence[Any],
    max_per_concept: int = DEFAULT_MAX_CARDS_PER_CONCEPT,
) -> list[Any]:
    """Keep at most `max_per_concept` cards per `concept_id`, preferring distinct `item_type`s."""
    if max_per_concept <= 0:
        return list(items)

    counts: dict[str, int] = {}
    seen_modalities: dict[str, set[str]] = {}
    first_pass: list[Any] = []
    deferred_same_modality: list[Any] = []

    for item in items:
        cid = getattr(item, "concept_id", None)
        if not cid:
            first_pass.append(item)
            continue
        itype = str(getattr(item, "item_type", "") or "")
        used_types = seen_modalities.setdefault(cid, set())
        if itype not in used_types and counts.get(cid, 0) < max_per_concept:
            used_types.add(itype)
            counts[cid] = counts.get(cid, 0) + 1
            first_pass.append(item)
        else:
            deferred_same_modality.append(item)

    for item in deferred_same_modality:
        cid = getattr(item, "concept_id", None)
        if cid and counts.get(cid, 0) < max_per_concept:
            counts[cid] = counts.get(cid, 0) + 1
            first_pass.append(item)

    return first_pass
