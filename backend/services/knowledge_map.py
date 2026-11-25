"""The knowledge map of a person: what they know, how well, and on what evidence.

One resolver, ``assess(user_id, names)``, serves the resume view, the "what's your exposure to X?"
questions, the MCP tools an outside agent calls, and (later) job-description matching.

Evidence (all in [0, 1], "how well does this suggest they know it"):
  review state   proficiency_scores: score after spaced-repetition reviews       weight 0.8 + 0.4/review (max 3)
  quiz/territory knowledge_evidence rows from answered cards                    weight 1.0
  leetcode       solved 0.8, needed a hint 0.5, couldn't solve 0.25              weight 1.0
  course         grade mapped to a signal (A ~ 0.85, C ~ 0.5)                     weight 0.8
  project        0.7 for each listed skill                                        weight 0.8
  self rating    never 0, heard of it 0.2, basics 0.45, used it 0.65, strong 0.85 weight 0.6
  resume claim   0.6                                                              weight 0.4
  note           the concept was ingested from your material: exposure, 0.35      weight 0.3

Each weight decays with age: weight * 0.5 ** (age_days / half_life[kind]); reviews fade in weeks,
courses over a year and a half. mastery = weighted mean of signals; confidence = 1 - exp(-total weight).

Status:
  unexposed  nothing in the graph and no evidence, or you said "never"
  strong     mastery >= 0.7 and (tested, or coursework/projects, or you rated yourself 3+)
  shaky      tested (or self-rated) and mastery < 0.7
  seen       studied or claimed, never tested (the honest "probably, but unverified")
A concept with no direct evidence borrows its subtopics' mean mastery at half weight.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Iterable, Optional

HALF_LIFE_DAYS = {"review": 45, "quiz": 45, "territory": 45, "leetcode": 60, "sandbox": 60, "agent": 90, "note": 120,
                  "self_rating": 180, "resume": 365, "project": 365, "course": 540}
DEFAULT_WEIGHT = {"quiz": 1.0, "territory": 1.0, "leetcode": 1.0, "sandbox": 1.0, "course": 0.8, "project": 0.8,
                  "self_rating": 0.6, "resume": 0.4, "note": 0.3, "agent": 0.5, "review": 1.0}
TESTED_KINDS = {"review", "quiz", "territory", "leetcode", "sandbox"}
NON_SELF_KINDS = {"course", "project"}
SELF_LEVEL_SIGNAL = [0.0, 0.2, 0.45, 0.65, 0.85]
SELF_LEVEL_LABEL = ["Never", "Heard of it", "Know the basics", "Used it", "Strong"]
STATUSES = ("strong", "shaky", "seen", "unexposed")


# --------------------------------------------------------------------------- names

def skill_key(name: str) -> str:
    text = re.sub(r"\(.*?\)", " ", (name or "").lower())
    text = re.sub(r"[^a-z0-9+#]+", " ", text)
    words = [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in text.split()]
    return " ".join(words)


def _acronym(name: str) -> str:
    words = [w for w in re.sub(r"\(.*?\)", " ", name).replace("-", " ").split() if w.lower() not in {"of", "and", "the"}]
    return "".join(w[0] for w in words if w and w[0].isalnum()).lower()


def match_concept(name: str, concepts: list[dict]) -> Optional[dict]:
    """Best concept for a free-text skill name. Conservative: a wrong match is worse than none."""
    key = skill_key(name)
    if not key:
        return None
    exact = [c for c in concepts if c["_key"] == key]
    if exact:
        return min(exact, key=lambda c: len(c["name"]))
    compact = key.replace(" ", "")
    if 2 <= len(compact) <= 6:
        acro = [c for c in concepts
                if _acronym(c["name"]) == compact
                or compact in {a.lower() for a in re.findall(r"\(([A-Za-z0-9-]{2,8})\)", c["name"])}]
        if acro:
            return min(acro, key=lambda c: len(c["name"]))
    words = set(key.split())
    slack = 0 if len(words) == 1 else 1  # "Python" must not become "Python Decorators"
    near = [c for c in concepts if words and words <= c["_words"] and len(c["_words"]) <= len(words) + slack]
    if near:
        return min(near, key=lambda c: len(c["name"]))
    best, best_r = None, 0.0
    digits = re.findall(r"\d+", key)
    for c in concepts:
        if re.findall(r"\d+", c["_key"]) != digits:  # "phase 1 trial" is not "phase 2 trial"
            continue
        r = SequenceMatcher(None, key, c["_key"]).ratio()
        if r > best_r:
            best, best_r = c, r
    return best if best_r >= 0.9 else None


async def _user_concepts(neo4j, user_id: str) -> list[dict]:
    rows = await neo4j.execute_query(
        "MATCH (c:Concept {user_id: $user_id}) RETURN c.id AS id, c.name AS name, c.domain AS domain, "
        "c.definition AS definition",
        {"user_id": user_id},
    )
    out = []
    for r in rows or []:
        if r.get("id") and r.get("name"):
            k = skill_key(r["name"])
            out.append({**dict(r), "_key": k, "_words": set(k.split())})
    return out


async def _children(neo4j, user_id: str, concept_ids: list[str]) -> dict[str, list[str]]:
    if not concept_ids:
        return {}
    rows = await neo4j.execute_query(
        "MATCH (ch:Concept)-[:SUBTOPIC_OF]->(p:Concept) WHERE p.user_id = $user_id AND ch.user_id = $user_id "
        "AND p.id IN $ids RETURN p.id AS parent, collect(DISTINCT ch.id) AS kids",
        {"user_id": user_id, "ids": concept_ids},
    )
    return {r["parent"]: list(r["kids"] or []) for r in rows or []}


# --------------------------------------------------------------------------- scoring

@dataclass
class Evidence:
    kind: str
    signal: float
    weight: float
    at: Optional[datetime] = None
    detail: dict = field(default_factory=dict)

    def effective_weight(self, now: datetime) -> float:
        if not self.at:
            return self.weight
        age = max(0.0, (now - self.at).total_seconds() / 86400)
        return self.weight * 0.5 ** (age / HALF_LIFE_DAYS.get(self.kind, 90))


@dataclass
class Assessment:
    name: str
    key: str
    status: str
    mastery: Optional[float]
    confidence: float
    basis: str                       # tested | coursework | self-reported | studied | claimed | none
    concept_id: Optional[str] = None
    concept_name: Optional[str] = None
    domain: Optional[str] = None
    self_rating: Optional[int] = None
    evidence: dict[str, int] = field(default_factory=dict)
    last_evidence_at: Optional[str] = None

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def score(evidence: list[Evidence], *, in_graph: bool, self_rating: Optional[int],
          now: Optional[datetime] = None, child_mastery: Optional[float] = None) -> tuple[str, Optional[float], float, str]:
    """(status, mastery, confidence, basis) from a list of evidence. Pure; unit-tested."""
    now = now or datetime.now(timezone.utc)
    ev = list(evidence)
    direct = [e for e in ev if e.kind != "note"]
    if child_mastery is not None and not direct:
        ev.append(Evidence("agent", child_mastery, 0.5))
    weights = [(e, e.effective_weight(now)) for e in ev]
    total = sum(w for _, w in weights)
    if total <= 0 or (not in_graph and not ev):
        return "unexposed", None, 0.0, "none"
    mastery = sum(e.signal * w for e, w in weights) / total
    confidence = 1 - math.exp(-total)
    kinds = {e.kind for e in ev}
    tested = bool(kinds & TESTED_KINDS)
    non_self = sum(w for e, w in weights if e.kind in NON_SELF_KINDS)
    if self_rating == 0 and not tested:
        return "unexposed", round(mastery, 3), round(confidence, 3), "self-reported"
    basis = ("tested" if tested else "coursework" if non_self else
             "self-reported" if "self_rating" in kinds else
             "studied" if "note" in kinds else "claimed")
    # A recent failed test outranks claims: no "strong" within 14 days of failing it (Neon's memo, sec. 3).
    recent_fail = any(e.kind in TESTED_KINDS and e.signal <= 0.3 and e.at and (now - e.at).days < 14 for e in ev)
    if mastery >= 0.7 and not recent_fail and (tested or non_self >= 0.6 or (self_rating or 0) >= 3):
        status = "strong"
    elif recent_fail:
        status = "shaky"
    elif tested or self_rating is not None:
        status = "shaky" if mastery < 0.7 else "seen"
    else:
        status = "seen"
    return status, round(mastery, 3), round(confidence, 3), basis


GRADE_SIGNAL = {"o": 0.9, "s": 0.88, "ex": 0.88, "a+": 0.88, "aa": 0.88, "a": 0.85, "a-": 0.8, "ab": 0.78,
                "b+": 0.74, "b": 0.68, "bb": 0.68, "b-": 0.62, "bc": 0.62, "c+": 0.58, "c": 0.52, "cc": 0.52,
                "c-": 0.48, "cd": 0.46, "d": 0.42, "dd": 0.42, "e": 0.3, "f": 0.15, "fail": 0.15, "u": 0.15,
                "pass": 0.6, "p": 0.6}


def grade_signal(grade: Optional[str]) -> float:
    g = (grade or "").strip().lower()
    if not g:
        return 0.6
    if g in GRADE_SIGNAL:
        return GRADE_SIGNAL[g]
    m = re.match(r"^(\d+(?:\.\d+)?)\s*(%|/\s*(\d+(?:\.\d+)?))?$", g)
    if m:
        value = float(m.group(1))
        scale = float(m.group(3)) if m.group(3) else (100.0 if m.group(2) == "%" or value > 10 else 10.0)
        return round(max(0.0, min(1.0, value / scale)) * 0.95, 3)
    return 0.6


# --------------------------------------------------------------------------- data access

def _aware(dt: Any) -> Optional[datetime]:
    if dt is None:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _load_state(pg, user_id: str, concept_ids: list[str], keys: list[str]) -> tuple[dict, dict, dict, dict]:
    """Evidence by concept, evidence by skill key, review state by concept, user_skills by key."""
    by_concept: dict[str, list[Evidence]] = {}
    by_key: dict[str, list[Evidence]] = {}
    rows = await pg.execute_query(
        "SELECT concept_id, skill_key, kind, signal, weight, created_at, detail FROM knowledge_evidence "
        "WHERE user_id = CAST(:u AS uuid) AND (concept_id = ANY(:cids) OR skill_key = ANY(:keys))",
        {"u": user_id, "cids": concept_ids or [""], "keys": keys or [""]},
    )
    for r in rows or []:
        e = Evidence(r["kind"], float(r["signal"]), float(r["weight"]), _aware(r["created_at"]),
                     r.get("detail") if isinstance(r.get("detail"), dict) else {})
        if r.get("concept_id") and r["concept_id"] in set(concept_ids):
            by_concept.setdefault(r["concept_id"], []).append(e)
        elif r.get("skill_key"):
            # Concept deleted or renamed, or a skill outside the graph: the name still carries it.
            by_key.setdefault(r["skill_key"], []).append(e)
    reviews: dict[str, dict] = {}
    if concept_ids:
        rows = await pg.execute_query(
            "SELECT concept_id, score, total_reviews, repetition_count, last_reviewed FROM proficiency_scores "
            "WHERE user_id = CAST(:u AS uuid) AND concept_id = ANY(:cids)",
            {"u": user_id, "cids": concept_ids},
        )
        reviews = {r["concept_id"]: dict(r) for r in rows or []}
    skills: dict[str, dict] = {}
    if keys:
        rows = await pg.execute_query(
            "SELECT skill_key, skill_name, concept_id, self_rating, sources, rated_at FROM user_skills "
            "WHERE user_id = CAST(:u AS uuid) AND skill_key = ANY(:keys)",
            {"u": user_id, "keys": keys},
        )
        skills = {r["skill_key"]: dict(r) for r in rows or []}
    return by_concept, by_key, reviews, skills


def _review_evidence(state: Optional[dict]) -> list[Evidence]:
    if not state:
        return []
    n = int(state.get("total_reviews") or state.get("repetition_count") or 0)
    if n <= 0:
        return []
    return [Evidence("review", float(state.get("score") or 0), min(3.0, 0.8 + 0.4 * n), _aware(state.get("last_reviewed")))]


# --------------------------------------------------------------------------- public API

async def assess(user_id: str, names: Iterable[str], *, pg=None, neo4j=None,
                 concepts: Optional[list[dict]] = None, max_names: Optional[int] = 200) -> list[Assessment]:
    from backend.db.neo4j_client import get_neo4j_client
    from backend.db.postgres_client import get_postgres_client

    pg = pg or await get_postgres_client()
    neo4j = neo4j or await get_neo4j_client()
    names = [n.strip() for n in names if n and skill_key(n)]
    names = list(dict.fromkeys(names))[:max_names] if max_names else list(dict.fromkeys(names))
    concepts = concepts if concepts is not None else await _user_concepts(neo4j, user_id)
    matched = {n: match_concept(n, concepts) for n in names}
    keys = list({skill_key(n) for n in names})
    cids = list({c["id"] for c in matched.values() if c})
    kids = await _children(neo4j, user_id, cids)
    all_kids = list({k for v in kids.values() for k in v})
    by_concept, by_key, reviews, skills = await _load_state(pg, user_id, cids + all_kids, keys)

    def child_mean(cid: str) -> Optional[float]:
        vals = []
        for k in kids.get(cid, []):
            ev = by_concept.get(k, []) + _review_evidence(reviews.get(k))
            if ev:
                _, m, _, _ = score(ev, in_graph=True, self_rating=None)
                if m is not None:
                    vals.append(m)
        return sum(vals) / len(vals) if vals else None

    out: list[Assessment] = []
    for n in names:
        key = skill_key(n)
        c = matched.get(n)
        skill = skills.get(key) or {}
        ev: list[Evidence] = list(by_key.get(key, []))
        if c:
            ev += by_concept.get(c["id"], [])
            if not any(e.kind == "review" for e in ev):  # per-review evidence supersedes the SR snapshot
                ev += _review_evidence(reviews.get(c["id"]))
            ev.append(Evidence("note", 0.35, DEFAULT_WEIGHT["note"]))  # it's in your graph: you studied it
        rating = skill.get("self_rating")
        status, mastery, conf, basis = score(ev, in_graph=bool(c), self_rating=rating,
                                             child_mastery=child_mean(c["id"]) if c else None)
        counts: dict[str, int] = {}
        for e in ev:
            if e.kind != "note" or not c:
                counts[e.kind] = counts.get(e.kind, 0) + 1
        if c:
            counts["in_graph"] = 1
        dates = [e.at for e in ev if e.at]
        out.append(Assessment(
            name=n, key=key, status=status, mastery=mastery, confidence=conf, basis=basis,
            concept_id=c["id"] if c else None, concept_name=c["name"] if c else None,
            domain=c.get("domain") if c else None, self_rating=rating, evidence=counts,
            last_evidence_at=max(dates).isoformat() if dates else None,
        ))
    return out


async def add_evidence(pg, user_id: str, *, kind: str, signal: float, concept_id: Optional[str] = None,
                       skill_name: Optional[str] = None, weight: Optional[float] = None,
                       source_id: Optional[str] = None, detail: Optional[dict] = None) -> None:
    key = skill_key(skill_name) if skill_name else None
    if not concept_id and not key:
        return
    if key == "":
        return
    await pg.execute_update(
        "INSERT INTO knowledge_evidence (user_id, concept_id, skill_key, skill_name, kind, signal, weight, "
        "source_id, detail) VALUES (CAST(:u AS uuid), CAST(:c AS varchar), CAST(:k AS text), CAST(:n AS text), :kind, "
        "CAST(:s AS real), CAST(:w AS real), CAST(:src AS text), CAST(:d AS jsonb))",
        {"u": user_id, "c": concept_id, "k": key, "n": skill_name, "kind": kind,
         "s": max(0.0, min(1.0, float(signal))), "w": weight or DEFAULT_WEIGHT.get(kind, 1.0),
         "src": source_id, "d": json.dumps(detail or {})},
    )


async def upsert_skill(pg, user_id: str, name: str, *, source: str, concept_id: Optional[str] = None,
                       self_rating: Optional[int] = None, asked: bool = False) -> None:
    await pg.execute_update(
        """
        INSERT INTO user_skills (user_id, skill_key, skill_name, concept_id, self_rating, sources, asked_at, rated_at)
        VALUES (CAST(:u AS uuid), :k, :n, CAST(:c AS varchar), CAST(:r AS smallint), ARRAY[CAST(:src AS text)],
                CASE WHEN CAST(:asked AS boolean) THEN now() END,
                CASE WHEN CAST(:r AS smallint) IS NOT NULL THEN now() END)
        ON CONFLICT (user_id, skill_key) DO UPDATE SET
            concept_id = COALESCE(EXCLUDED.concept_id, user_skills.concept_id),
            self_rating = COALESCE(EXCLUDED.self_rating, user_skills.self_rating),
            rated_at = COALESCE(EXCLUDED.rated_at, user_skills.rated_at),
            asked_at = COALESCE(EXCLUDED.asked_at, user_skills.asked_at),
            sources = (SELECT ARRAY(SELECT DISTINCT unnest(user_skills.sources || EXCLUDED.sources)))
        """,
        {"u": user_id, "k": skill_key(name), "n": name.strip(), "c": concept_id, "r": self_rating,
         "src": source, "asked": asked},
    )


async def rate_skill(user_id: str, name: str, level: int, *, pg=None, neo4j=None) -> Assessment:
    """The user's own answer to "what's your exposure to X?" (0 never .. 4 strong)."""
    from backend.db.neo4j_client import get_neo4j_client
    from backend.db.postgres_client import get_postgres_client

    pg = pg or await get_postgres_client()
    neo4j = neo4j or await get_neo4j_client()
    level = max(0, min(4, int(level)))
    concept = match_concept(name, await _user_concepts(neo4j, user_id))
    cid = concept["id"] if concept else None
    await upsert_skill(pg, user_id, name, source="user", concept_id=cid, self_rating=level)
    # A new answer replaces the old one rather than averaging with it.
    await pg.execute_update(
        "DELETE FROM knowledge_evidence WHERE user_id = CAST(:u AS uuid) AND kind = 'self_rating' "
        "AND (skill_key = :k OR (CAST(:c AS varchar) IS NOT NULL AND concept_id = CAST(:c AS varchar)))",
        {"u": user_id, "k": skill_key(name), "c": cid},
    )
    await add_evidence(pg, user_id, kind="self_rating", signal=SELF_LEVEL_SIGNAL[level], concept_id=cid,
                       skill_name=name, detail={"level": level})
    return (await assess(user_id, [name], pg=pg, neo4j=neo4j))[0]


async def record_territory_evidence(user_id: str, concept_id: str, grade) -> None:
    from backend.db.postgres_client import get_postgres_client

    pg = await get_postgres_client()
    await add_evidence(pg, user_id, kind="territory", signal=grade.score, concept_id=concept_id,
                       detail={"matched": len(grade.matched), "missed": len(grade.missed)})
    for m in grade.matched:
        if m.get("id"):
            await add_evidence(pg, user_id, kind="territory", signal=0.8, concept_id=m["id"], weight=0.7)
    for m in grade.missed:
        if m.get("id"):
            await add_evidence(pg, user_id, kind="territory", signal=0.25, concept_id=m["id"], weight=0.5)


LEETCODE_SIGNAL = {"solved": 0.8, "hint": 0.5, "failed": 0.25}
REVIEW_SIGNAL = {"again": 0.1, "hard": 0.5, "good": 0.8, "easy": 0.95}


async def record_leetcode_evidence(pg, user_id: str, *, concept_id: Optional[str], pattern_concept_id: Optional[str],
                                   outcome: str, attempt_id: Optional[str] = None) -> None:
    s = LEETCODE_SIGNAL.get(outcome, 0.5)
    if concept_id:
        await add_evidence(pg, user_id, kind="leetcode", signal=s, concept_id=concept_id, source_id=attempt_id)
    if pattern_concept_id:
        await add_evidence(pg, user_id, kind="leetcode", signal=s, concept_id=pattern_concept_id, weight=0.6,
                           source_id=attempt_id)


async def summary(user_id: str, *, pg=None, neo4j=None, limit: int = 2000) -> dict:
    """Every concept in the graph plus every tracked skill, assessed, grouped by status and domain."""
    from backend.db.neo4j_client import get_neo4j_client
    from backend.db.postgres_client import get_postgres_client

    pg = pg or await get_postgres_client()
    neo4j = neo4j or await get_neo4j_client()
    concepts = await _user_concepts(neo4j, user_id)
    skill_rows = await pg.execute_query(
        "SELECT skill_name FROM user_skills WHERE user_id = CAST(:u AS uuid)", {"u": user_id})
    names = [c["name"] for c in concepts[:limit]] + [r["skill_name"] for r in skill_rows or []]
    names = list(dict.fromkeys(names))
    results = await assess(user_id, names, pg=pg, neo4j=neo4j, concepts=concepts, max_names=None)
    counts = {s: 0 for s in STATUSES}
    domains: dict[str, dict[str, int]] = {}
    for a in results:
        counts[a.status] += 1
        d = a.domain or "Other"
        domains.setdefault(d, {s: 0 for s in STATUSES})[a.status] += 1
    tested = [a for a in results if a.basis == "tested" and a.mastery is not None]
    return {
        "counts": counts,
        "domains": domains,
        "strongest": [a.as_dict() for a in sorted(tested, key=lambda a: -a.mastery)[:8]],
        "weakest": [a.as_dict() for a in sorted(tested, key=lambda a: a.mastery)[:8]],
        "items": [a.as_dict() for a in results],
    }
