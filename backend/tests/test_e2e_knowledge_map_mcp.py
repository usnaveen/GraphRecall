"""End-to-end deterministic integration tests across Knowledge Map, Resume PII
scrubbing, Universal MCP Agent Bridge, Digest-This Diagram Occlusion, and Feed
Creative/Sandbox Evidence Loops (zero external DB, zero live LLM calls, zero PII).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.agent_bridge.auth import authenticate_agent_key
from backend.agent_bridge.feed_integration import agent_feed_items
from backend.agent_bridge.keys import SCOPE_READ_KNOWLEDGE, SCOPE_WRITE_FEED
from backend.agent_bridge.knowledge import KnowledgeService
from backend.agent_bridge.repository import InMemoryBridgeRepository
from backend.agent_bridge.tools import BridgeServices, call_tool
from backend.auth.middleware import get_current_user
from backend.models.feed_schemas import (
    FeedFilterRequest,
    FeedItem,
    FeedItemType,
    FeedResponse,
)
from backend.routers import feed as feed_router
from backend.routers import knowledge_map as km_router
from backend.routers import later as later_router
from backend.services import creative_cards
from backend.services import knowledge_map as km
from backend.services import resume as resume_service
from backend.services.code_sandbox_cards import CodeSandboxSubmission, compute_sandbox_evidence

USER_ML = "aaaaaaaa-1111-4222-8333-bbbbbbbbbbbb"
USER_OTHER = "cccccccc-2222-4333-8444-dddddddddddd"

# Completely synthetic ML engineer resume (modeled on real ML/AI section formats, zero real PII).
SYNTHETIC_ML_RESUME = """Jordan Avery
Location: Seattle, WA 98101
Email: jordan.avery.synthetic@example.org | Phone: (206) 555-0147
https://linkedin.com/in/jordan-avery-synthetic | github.com/jordan-avery-ml | https://jordanavery.example.dev
742 Cedarview Avenue, Seattle, WA 98101

SUMMARY
Applied Machine Learning & Retrieval Systems Engineer building multi-tenant RAG pipelines,
low-rank fine-tuning workflows, and graph-indexed active recall engines.

EXPERIENCE
Senior ML Systems Engineer — Fictional AI Labs
- Scaled hybrid dense + lexical retrieval with Reciprocal Rank Fusion and HNSW vector indexing.
- Fine-tuned domain adapters with LoRA in PyTorch and benchmarked Scaled Dot-Product Attention kernels.

TECHNICAL SKILLS
Technical Skills: PyTorch, Scaled Dot-Product Attention, Reciprocal Rank Fusion, LoRA, HNSW, Linear Algebra
Frameworks: FastAPI, PostgreSQL, Neo4j
"""

SYNTHETIC_PII_TOKENS = (
    "Jordan Avery",
    "jordan.avery.synthetic@example.org",
    "206",
    "555-0147",
    "linkedin.com/in/jordan-avery-synthetic",
    "github.com/jordan-avery-ml",
    "jordanavery.example.dev",
    "742 Cedarview Avenue",
    "98101",
)


# ---------------------------------------------------------------------------
# Stateful in-memory Neo4j & Postgres fakes with strict user_id isolation
# ---------------------------------------------------------------------------


class StatefulNeo4jFake:
    """In-memory Neo4j fake enforcing user_id scoping on every Cypher query."""

    def __init__(self, concepts: list[dict[str, Any]], subtopics: list[tuple[str, str]] | None = None):
        self.concepts = [dict(c) for c in concepts]
        self.subtopics = list(subtopics or [])  # (child_id, parent_id)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute_query(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        p = dict(params or {})
        self.calls.append((query, p))
        uid = p["user_id"]  # KeyError fails immediately if any query omits user_id
        mine = [c for c in self.concepts if c["user_id"] == uid]
        by_id = {c["id"]: c for c in mine}

        if "SUBTOPIC_OF" in query and "collect(DISTINCT ch.id)" in query:
            ids = set(p.get("ids") or [])
            grouped: dict[str, list[str]] = {}
            for child_id, parent_id in self.subtopics:
                if parent_id in ids and parent_id in by_id and child_id in by_id:
                    grouped.setdefault(parent_id, []).append(child_id)
            return [{"parent": pid, "kids": kids} for pid, kids in grouped.items()]

        if "SUBTOPIC_OF" in query:
            # territory.territories lookup
            return []

        if "c.id IN $ids" in query and "RETURN c" in query:
            return [{"c": by_id[cid]} for cid in (p.get("ids") or []) if cid in by_id]

        if "CONTAINS" in query:
            q = str(p.get("q") or "").lower()
            limit = int(p.get("limit") or 10)
            hits = [
                {"c": c}
                for c in mine
                if q in c["name"].lower() or q in c.get("definition", "").lower()
            ]
            return hits[:limit]

        if "RETURN c.id AS id" in query:
            return [
                {
                    "id": c["id"],
                    "name": c["name"],
                    "domain": c.get("domain", "Machine Learning"),
                    "definition": c.get("definition", ""),
                }
                for c in mine
            ]

        raise AssertionError(f"Unexpected Cypher query in StatefulNeo4jFake: {query}")


class StatefulPostgresFake:
    """In-memory Postgres fake supporting knowledge_map, resume, profile, feed, and MCP queries."""

    def __init__(self) -> None:
        self.now = datetime.now(timezone.utc)
        self.evidence: list[dict[str, Any]] = []
        self.proficiency_scores: dict[tuple[str, str], dict[str, Any]] = {}
        self.user_skills: dict[tuple[str, str], dict[str, Any]] = {}
        self.user_resumes: list[dict[str, Any]] = []
        self.user_profile: dict[str, dict[str, Any]] = {}
        self.user_courses: list[dict[str, Any]] = []
        self.user_projects: list[dict[str, Any]] = []
        self.coding_attempts: list[dict[str, Any]] = []
        self.notes: list[dict[str, Any]] = []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def seed_proficiency(
        self,
        user_id: str,
        concept_id: str,
        *,
        score: float,
        total_reviews: int = 4,
        due_in_days: int = -1,
    ) -> None:
        self.proficiency_scores[(user_id, concept_id)] = {
            "user_id": user_id,
            "concept_id": concept_id,
            "score": score,
            "easiness_factor": 2.5,
            "interval_days": 6,
            "repetition_count": total_reviews,
            "total_reviews": total_reviews,
            "correct_streak": total_reviews,
            "last_reviewed": self.now - timedelta(days=2),
            "next_review_due": self.now + timedelta(days=due_in_days),
        }

    def _uid(self, params: dict[str, Any]) -> str:
        for key in ("u", "user_id", "uid"):
            if key in params and params[key]:
                return str(params[key])
        raise AssertionError(f"Query missing user_id parameter: {params}")

    async def execute_query(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        p = dict(params or {})
        self.calls.append((query, p))
        q = " ".join(query.split())
        uid = self._uid(p)

        if "FROM knowledge_evidence" in q and q.startswith("SELECT"):
            cids = set(p.get("cids") or [])
            keys = set(p.get("keys") or [])
            return [
                dict(row)
                for row in self.evidence
                if row["user_id"] == uid
                and (
                    (row.get("concept_id") and row["concept_id"] in cids)
                    or (row.get("skill_key") and row["skill_key"] in keys)
                )
            ]

        if "ps.concept_id as item_id" in q:
            limit = int(p.get("limit") or 50)
            rows = []
            for (u, cid), ps in self.proficiency_scores.items():
                if u == uid and ps["next_review_due"] <= self.now:
                    rows.append(
                        {
                            "item_id": cid,
                            "item_type": "concept",
                            "easiness_factor": ps["easiness_factor"],
                            "interval": ps["interval_days"],
                            "repetition": ps["repetition_count"],
                            "last_review": ps["last_reviewed"],
                            "next_review": ps["next_review_due"],
                            "total_reviews": ps["total_reviews"],
                            "correct_streak": ps["correct_streak"],
                            "mastery_score": ps["score"],
                        }
                    )
            return rows[:limit]

        if "FROM proficiency_scores" in q and q.startswith("SELECT"):
            cids = p.get("cids")
            cid_set = set(cids) if cids is not None else None
            out = []
            for (u, cid), ps in self.proficiency_scores.items():
                if u != uid:
                    continue
                if cid_set is not None and cid not in cid_set:
                    continue
                out.append(dict(ps))
            return out

        if "SELECT count(*) AS n FROM user_skills" in q:
            n = sum(
                1
                for (u, _), sk in self.user_skills.items()
                if u == uid and sk.get("self_rating") is None and "agent" in (sk.get("sources") or [])
            )
            return [{"n": n}]

        if "SELECT skill_name, sources FROM user_skills" in q:
            rows = [
                {"skill_name": sk["skill_name"], "sources": list(sk.get("sources") or [])}
                for (u, _), sk in self.user_skills.items()
                if u == uid and sk.get("self_rating") is None
            ]
            return rows[:60]

        if "SELECT skill_name FROM user_skills" in q:
            return [
                {"skill_name": sk["skill_name"]}
                for (u, _), sk in self.user_skills.items()
                if u == uid
            ]

        if "FROM user_skills" in q and q.startswith("SELECT"):
            keys = set(p.get("keys") or [])
            return [
                dict(sk)
                for (u, k), sk in self.user_skills.items()
                if u == uid and k in keys
            ]

        if "INSERT INTO user_resumes" in q:
            skills_val = p["s"]
            if isinstance(skills_val, str):
                skills_val = json.loads(skills_val)
            row = {
                "id": str(uuid4()),
                "user_id": uid,
                "file_name": p.get("f"),
                "text": p["t"],
                "skills": skills_val,
                "created_at": self.now,
            }
            self.user_resumes.append(row)
            return [dict(row)]

        if "FROM user_resumes" in q and q.startswith("SELECT"):
            mine = [r for r in self.user_resumes if r["user_id"] == uid]
            return [dict(mine[-1])] if mine else []

        if "FROM user_profile" in q and q.startswith("SELECT"):
            prof = self.user_profile.get(uid)
            return [dict(prof)] if prof else []

        if "FROM user_courses" in q and q.startswith("SELECT"):
            return [dict(c) for c in self.user_courses if c["user_id"] == uid]

        if "FROM user_projects" in q and q.startswith("SELECT"):
            return [dict(pr) for pr in self.user_projects if pr["user_id"] == uid]

        if "FROM coding_attempts" in q or "FROM coding_problems" in q:
            return [dict(a) for a in self.coding_attempts if a.get("user_id") == uid]

        if "FROM notes" in q:
            return [dict(n) for n in self.notes if n.get("user_id") == uid]

        raise AssertionError(f"Unexpected SQL SELECT in StatefulPostgresFake: {query}")

    async def execute_update(self, query: str, params: dict[str, Any] | None = None) -> int:
        p = dict(params or {})
        self.calls.append((query, p))
        q = " ".join(query.split())
        uid = self._uid(p)

        if "INSERT INTO knowledge_evidence" in q:
            detail = p.get("d")
            if isinstance(detail, str):
                detail = json.loads(detail)
            self.evidence.append(
                {
                    "user_id": uid,
                    "concept_id": p.get("c"),
                    "skill_key": p.get("k"),
                    "skill_name": p.get("n"),
                    "kind": p["kind"],
                    "signal": float(p["s"]),
                    "weight": float(p["w"]),
                    "source_id": p.get("src"),
                    "detail": detail or {},
                    "created_at": self.now,
                }
            )
            return 1

        if "DELETE FROM knowledge_evidence" in q and "kind = 'resume'" in q:
            before = len(self.evidence)
            self.evidence = [
                e for e in self.evidence if not (e["user_id"] == uid and e["kind"] == "resume")
            ]
            return before - len(self.evidence)

        if "DELETE FROM knowledge_evidence" in q and "kind = 'self_rating'" in q:
            target_key = p.get("k")
            target_cid = p.get("c")
            before = len(self.evidence)
            self.evidence = [
                e
                for e in self.evidence
                if not (
                    e["user_id"] == uid
                    and e["kind"] == "self_rating"
                    and (
                        e.get("skill_key") == target_key
                        or (target_cid is not None and e.get("concept_id") == target_cid)
                    )
                )
            ]
            return before - len(self.evidence)

        if "INSERT INTO user_skills" in q:
            key = p["k"]
            existing = self.user_skills.get((uid, key))
            src = p["src"]
            rating = p.get("r")
            asked = bool(p.get("asked"))
            if existing is None:
                self.user_skills[(uid, key)] = {
                    "user_id": uid,
                    "skill_key": key,
                    "skill_name": p["n"],
                    "concept_id": p.get("c"),
                    "self_rating": rating,
                    "sources": [src],
                    "asked_at": self.now if asked else None,
                    "rated_at": self.now if rating is not None else None,
                    "created_at": self.now,
                }
            else:
                if p.get("c") is not None:
                    existing["concept_id"] = p["c"]
                if rating is not None:
                    existing["self_rating"] = rating
                    existing["rated_at"] = self.now
                if asked:
                    existing["asked_at"] = self.now
                if src not in existing["sources"]:
                    existing["sources"].append(src)
            return 1

        raise AssertionError(f"Unexpected SQL UPDATE in StatefulPostgresFake: {query}")


def _build_seeded_environment() -> tuple[StatefulPostgresFake, StatefulNeo4jFake]:
    """Create a realistic ML user's graph + evidence ledger across strong, seen, shaky, and unexposed."""
    concepts = [
        {
            "id": "c-pytorch",
            "user_id": USER_ML,
            "name": "PyTorch",
            "domain": "Deep Learning",
            "definition": "Tensor computation and automatic differentiation framework.",
            "complexity_score": 5,
        },
        {
            "id": "c-sdpa",
            "user_id": USER_ML,
            "name": "Scaled Dot-Product Attention",
            "domain": "Transformers",
            "definition": "Attention mechanism scaling QK^T by 1/sqrt(d_k) prior to softmax.",
            "complexity_score": 7,
        },
        {
            "id": "c-rrf",
            "user_id": USER_ML,
            "name": "Reciprocal Rank Fusion",
            "domain": "RAG",
            "definition": "Rank-based score fusion over heterogeneous retrieval lists.",
            "complexity_score": 6,
        },
        {
            "id": "c-lora",
            "user_id": USER_ML,
            "name": "LoRA",
            "domain": "LLMs",
            "definition": "Low-Rank Adaptation freezing pretrained weights and training rank-r matrices.",
            "complexity_score": 6,
        },
        {
            "id": "c-hnsw",
            "user_id": USER_ML,
            "name": "HNSW",
            "domain": "Database Systems",
            "definition": "Hierarchical Navigable Small World graph index for ANN vector search.",
            "complexity_score": 7,
        },
        # Tenant-isolation canary owned by another user
        {
            "id": "c-other-private",
            "user_id": USER_OTHER,
            "name": "Confidential Biotech Pipeline",
            "domain": "Bioinformatics",
            "definition": "Private tenant concept that must never leak.",
            "complexity_score": 8,
        },
    ]
    neo = StatefulNeo4jFake(concepts)
    pg = StatefulPostgresFake()

    # Active-recall tested skills -> strong (green)
    pg.seed_proficiency(USER_ML, "c-pytorch", score=0.92, total_reviews=5, due_in_days=4)
    pg.seed_proficiency(USER_ML, "c-sdpa", score=0.88, total_reviews=4, due_in_days=-1)
    pg.seed_proficiency(USER_ML, "c-rrf", score=0.90, total_reviews=4, due_in_days=3)
    pg.evidence.extend(
        [
            {
                "user_id": USER_ML,
                "concept_id": "c-pytorch",
                "skill_key": km.skill_key("PyTorch"),
                "skill_name": "PyTorch",
                "kind": "quiz",
                "signal": 0.90,
                "weight": 1.0,
                "source_id": "quiz:pytorch-autograd",
                "detail": {},
                "created_at": pg.now - timedelta(days=1),
            },
            {
                "user_id": USER_ML,
                "concept_id": "c-sdpa",
                "skill_key": km.skill_key("Scaled Dot-Product Attention"),
                "skill_name": "Scaled Dot-Product Attention",
                "kind": "sandbox",
                "signal": 0.90,
                "weight": 1.0,
                "source_id": "sandbox:attention-masking",
                "detail": {"passed_tests": 3, "total_tests": 3},
                "created_at": pg.now - timedelta(days=1),
            },
            {
                "user_id": USER_ML,
                "concept_id": "c-rrf",
                "skill_key": km.skill_key("Reciprocal Rank Fusion"),
                "skill_name": "Reciprocal Rank Fusion",
                "kind": "sandbox",
                "signal": 0.90,
                "weight": 1.0,
                "source_id": "sandbox:reciprocal-rank-fusion",
                "detail": {"passed_tests": 3, "total_tests": 3},
                "created_at": pg.now - timedelta(days=2),
            },
            # HNSW failed a recent spot-the-bug quiz -> shaky (amber)
            {
                "user_id": USER_ML,
                "concept_id": "c-hnsw",
                "skill_key": km.skill_key("HNSW"),
                "skill_name": "HNSW",
                "kind": "quiz",
                "signal": 0.15,
                "weight": 1.0,
                "source_id": "spot_the_bug:bug-post-ann-filter",
                "detail": {},
                "created_at": pg.now - timedelta(days=1),
            },
        ]
    )
    pg.seed_proficiency(USER_ML, "c-hnsw", score=0.32, total_reviews=2, due_in_days=-1)

    pg.user_profile[USER_ML] = {
        "user_id": USER_ML,
        "headline": "ML & Retrieval Engineer",
        "education_status": "graduated",
        "institution": "State Tech University",
        "program": "M.S. Computer Science",
        "graduation_year": 2025,
        "goals": "Master LLM inference & retrieval systems",
    }
    return pg, neo


# ---------------------------------------------------------------------------
# 1. Resume Upload -> PII Scrub -> Coloring -> Exposure Calibration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_resume_upload_pii_scrub_coloring_and_exposure_calibration(monkeypatch):
    pg, neo = _build_seeded_environment()

    monkeypatch.setattr("backend.db.postgres_client.get_postgres_client", AsyncMock(return_value=pg))
    monkeypatch.setattr("backend.db.neo4j_client.get_neo4j_client", AsyncMock(return_value=neo))
    monkeypatch.setattr(km_router, "get_postgres_client", AsyncMock(return_value=pg))

    # Force deterministic zero-LLM fallback skill extraction.
    def _offline_llm(*_args, **_kwargs):
        raise RuntimeError("LLM disabled in deterministic E2E suite")

    monkeypatch.setattr("backend.config.llm.get_fast_model", _offline_llm)

    # Step 1a: Verify strip_contacts scrubs all PII while keeping technical content intact.
    scrubbed = resume_service.strip_contacts(SYNTHETIC_ML_RESUME)
    for pii_token in SYNTHETIC_PII_TOKENS:
        assert pii_token not in scrubbed, f"PII token leaked after strip_contacts: {pii_token}"
    for expected_skill in ("PyTorch", "Scaled Dot-Product Attention", "Reciprocal Rank Fusion", "LoRA", "HNSW", "Linear Algebra"):
        assert expected_skill in scrubbed

    # Step 1b: Before resume claim evidence is recorded, assess extracted skills directly:
    # Linear Algebra is completely unstudied -> "unexposed", LoRA (note-only) -> "seen",
    # HNSW (failed quiz) -> "shaky", PyTorch / SDPA / RRF (quiz/sandbox) -> "strong".
    extracted_skills, method = await resume_service.extract_skills(scrubbed)
    assert method == "fallback"
    extracted_names = [s["name"] for s in extracted_skills]
    assert {"PyTorch", "LoRA", "HNSW", "Linear Algebra"} <= set(extracted_names)

    pre_claim = {a.name: a for a in await km.assess(USER_ML, extracted_names, pg=pg, neo4j=neo)}
    assert pre_claim["PyTorch"].status == "strong" and pre_claim["PyTorch"].basis == "tested"
    assert pre_claim["Scaled Dot-Product Attention"].status == "strong"
    assert pre_claim["Reciprocal Rank Fusion"].status == "strong"
    assert pre_claim["LoRA"].status == "seen" and pre_claim["LoRA"].basis == "studied"
    assert pre_claim["HNSW"].status == "shaky" and pre_claim["HNSW"].basis == "tested"
    assert pre_claim["Linear Algebra"].status == "unexposed" and pre_claim["Linear Algebra"].mastery is None

    # Snapshot proficiency_scores before resume upload + self-rating calibration.
    due_snapshot_before = dict(pg.proficiency_scores)

    # Step 1c: Upload resume through FastAPI router -> verify stored text is scrubbed,
    # spans highlight skills, and unverified skill ("Linear Algebra") triggers exposure prompt.
    app = FastAPI()
    app.include_router(km_router.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": USER_ML, "email": "u@example.org"}
    client = TestClient(app)

    upload_resp = client.post(
        "/api/profile/resume",
        json={"text": SYNTHETIC_ML_RESUME, "file_name": "synthetic_ml_2026.pdf"},
    )
    assert upload_resp.status_code == 200, upload_resp.text
    resume_view = upload_resp.json()
    assert resume_view["extraction"] == "fallback"
    for pii_token in SYNTHETIC_PII_TOKENS:
        assert pii_token not in resume_view["text"]

    colored = {s["name"]: s for s in resume_view["skills"]}
    assert colored["PyTorch"]["status"] == "strong"
    assert colored["Scaled Dot-Product Attention"]["status"] == "strong"
    assert colored["Reciprocal Rank Fusion"]["status"] == "strong"
    assert colored["LoRA"]["status"] == "seen"
    assert colored["HNSW"]["status"] == "shaky"
    assert colored["PyTorch"]["spans"], "Expected character highlight spans for PyTorch"

    # Exposure calibration prompt surfaces Linear Algebra (unverified claim) and any unexposed skill.
    await km.upsert_skill(pg, USER_ML, "Convex Optimization", source="agent")
    q_resp = client.get("/api/knowledge-map/questions?limit=10")
    assert q_resp.status_code == 200
    questions_by_name = {q["name"]: q for q in q_resp.json()["questions"]}
    assert "Linear Algebra" in questions_by_name
    assert questions_by_name["Linear Algebra"]["prompt"] == "What's your exposure to Linear Algebra?"
    assert questions_by_name["Convex Optimization"]["status"] == "unexposed"
    used_it_level = next(
        lv["level"] for lv in questions_by_name["Linear Algebra"]["levels"] if lv["label"] == "Used it"
    )
    assert used_it_level == 3

    # Step 1d: User answers "Used it" (level=3) -> status updates immediately WITHOUT polluting proficiency_scores!
    rate_resp = client.post(
        "/api/knowledge-map/self-rating",
        json={"name": "Linear Algebra", "level": used_it_level},
    )
    assert rate_resp.status_code == 200
    rated = rate_resp.json()
    assert rated["self_rating"] == 3
    assert rated["basis"] == "self-reported"
    assert rated["status"] in {"shaky", "strong"}
    assert rated["mastery"] is not None and rated["mastery"] >= 0.6

    rated_unexposed = await km.rate_skill(USER_ML, "Convex Optimization", used_it_level, pg=pg, neo4j=neo)
    assert rated_unexposed.status == "shaky"  # 0.65 self-rating -> calibrated <0.7 without overclaiming strong
    assert rated_unexposed.self_rating == 3
    assert rated_unexposed.basis == "self-reported"

    # Neither Linear Algebra nor Convex Optimization remains in uncalibrated questions,
    # and proficiency_scores (SR due queue) is 100% untouched!
    q_after = {q["name"] for q in client.get("/api/knowledge-map/questions?limit=10").json()["questions"]}
    assert "Linear Algebra" not in q_after
    assert "Convex Optimization" not in q_after
    assert pg.proficiency_scores == due_snapshot_before


# ---------------------------------------------------------------------------
# 2. Universal MCP Paper Prerequisite Walkthrough + "Digest This"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_mcp_paper_prerequisite_walkthrough_and_article_digest(monkeypatch):
    pg, neo = _build_seeded_environment()
    monkeypatch.setattr("backend.db.postgres_client.get_postgres_client", AsyncMock(return_value=pg))
    monkeypatch.setattr("backend.db.neo4j_client.get_neo4j_client", AsyncMock(return_value=neo))

    # Store scrubbed resume in user_resumes to prove MCP tools NEVER leak resume text.
    pg.user_resumes.append(
        {
            "id": str(uuid4()),
            "user_id": USER_ML,
            "file_name": "resume.pdf",
            "text": "UNIQUE_RESUME_SENTINEL_DO_NOT_LEAK\n" + resume_service.strip_contacts(SYNTHETIC_ML_RESUME),
            "skills": [{"name": "PyTorch", "key": "pytorch", "section": "skills"}],
            "created_at": pg.now,
        }
    )

    repo = InMemoryBridgeRepository()
    services = BridgeServices(repo=repo, knowledge=KnowledgeService(pg, neo))

    _, raw_agent_key = await repo.create_key(
        USER_ML,
        "Paper Reading Copilot",
        [SCOPE_READ_KNOWLEDGE, SCOPE_WRITE_FEED],
    )
    principal = await authenticate_agent_key(repo, raw_agent_key)
    assert principal is not None
    assert principal.user_id == USER_ML
    assert principal.scopes == frozenset({SCOPE_READ_KNOWLEDGE, SCOPE_WRITE_FEED})

    # 10 research-paper prerequisites spanning known (strong), studied (seen), shaky, and unexposed.
    prereqs = [
        "Scaled Dot-Product Attention",
        "PyTorch",
        "Reciprocal Rank Fusion",
        "LoRA",
        "HNSW",
        "Linear Algebra",
        "Maximum Mean Discrepancy",
        "Sinkhorn Optimal Transport",
        "Rotary Position Embeddings",
        "Speculative Decoding",
    ]
    assess_res = await call_tool(
        "assess_concepts",
        principal,
        services,
        {"names": prereqs, "track_unknown": True},
    )
    assert assess_res["ok"] is True, assess_res
    by_name = {r["name"]: r for r in assess_res["data"]["results"]}
    assert len(by_name) == 10

    strong_names = {k for k, v in by_name.items() if v["status"] == "strong"}
    shaky_names = {k for k, v in by_name.items() if v["status"] == "shaky"}
    seen_names = {k for k, v in by_name.items() if v["status"] == "seen"}
    unexposed_names = {k for k, v in by_name.items() if v["status"] == "unexposed"}

    assert strong_names == {"Scaled Dot-Product Attention", "PyTorch", "Reciprocal Rank Fusion"}
    assert shaky_names == {"HNSW"}
    assert seen_names == {"LoRA"}
    assert unexposed_names == {
        "Linear Algebra",
        "Maximum Mean Discrepancy",
        "Sinkhorn Optimal Transport",
        "Rotary Position Embeddings",
        "Speculative Decoding",
    }

    # Unexposed prerequisites were queued in user_skills with source='agent' so the app can calibrate later.
    queued_agent_skills = {
        sk["skill_name"]
        for (u, _), sk in pg.user_skills.items()
        if u == USER_ML and "agent" in sk["sources"]
    }
    assert queued_agent_skills == unexposed_names

    # Call get_knowledge_profile and get_capability_blueprint; verify zero raw resume text or cross-tenant leaks.
    profile_res = await call_tool("get_knowledge_profile", principal, services, {"limit": 10})
    assert profile_res["ok"] is True
    profile_data = profile_res["data"]
    assert profile_data["total_concepts"] == 5
    assert profile_data["due_review_count"] == 2  # c-sdpa and c-hnsw are overdue
    weak_ids = {c["id"] for c in profile_data["weak_concepts"]}
    assert "c-hnsw" in weak_ids
    assert "c-other-private" not in json.dumps(profile_data)

    blueprint_res = await call_tool("get_capability_blueprint", principal, services, {})
    assert blueprint_res["ok"] is True
    serialized_mcp = json.dumps({"assess": assess_res, "profile": profile_res, "blueprint": blueprint_res})
    assert "UNIQUE_RESUME_SENTINEL_DO_NOT_LEAK" not in serialized_mcp
    for pii_token in SYNTHETIC_PII_TOKENS:
        assert pii_token not in serialized_mcp

    # Propose a curated Substack article bridging the user's paper prerequisites.
    substack_url = "https://mlsystems.substack.com/p/hybrid-rag-speculative-decoding"
    propose_res = await call_tool(
        "propose_feed_items",
        principal,
        services,
        {
            "items": [
                {
                    "title": "Hybrid RAG & Speculative Decoding in Production",
                    "summary": "Walks through HNSW pre-filtering, RRF + Cross-Encoder reranking, and draft-model verification.",
                    "reason": "Bridges your shaky HNSW retrieval concept and unexposed Speculative Decoding paper prereq.",
                    "source_url": substack_url,
                    "source_kind": "substack",
                    "item_kind": "article",
                    "concept_ids": ["c-hnsw", "c-rrf", "c-other-private"],
                    "target_date": date.today().isoformat(),
                    "idempotency_key": "mcp-e2e-substack-1",
                }
            ]
        },
    )
    assert propose_res["ok"] is True
    proposed_item = propose_res["data"]["items"][0]
    assert proposed_item["created"] is True
    assert proposed_item["status"] == "pending"
    # Foreign tenant concept ID is stripped automatically.
    assert proposed_item["dropped_concept_ids"] == ["c-other-private"]

    await repo.set_feed_item_status(USER_ML, proposed_item["id"], "approved")
    curated_feed = await agent_feed_items(repo, USER_ML, today=date.today())
    assert len(curated_feed) == 1
    assert curated_feed[0].item_type == FeedItemType.AGENT_CURATED

    # Run "Digest This" (plan_article_digest + /api/later/digest-url) on the Substack markdown!
    substack_markdown = """# Hybrid RAG & Speculative Decoding in Production

**Speculative Decoding**: Accelerates autoregressive generation using a fast draft model verified in parallel by the target LLM.

- Always push tenant predicates inside the HNSW index scan before applying LIMIT k to prevent zero-hit recall collapse.
- Combine Reciprocal Rank Fusion with a Cross-Encoder reranker when multi-hop precision matters more than 15ms latency.

```mermaid
flowchart LR
    Q["User Query"] --> H["HNSW Iterative Scan"]
    H --> R["Cross-Encoder Reranker"]
    R --> D["Speculative Draft Verifier"]
```
"""
    digest_plan = creative_cards.plan_article_digest(
        title="Hybrid RAG & Speculative Decoding in Production",
        markdown_text=substack_markdown,
        source_url=substack_url,
        max_cards=6,
    )
    assert digest_plan.source_url_valid is True
    assert len(digest_plan.diagram_cards) == 1
    mermaid_card = digest_plan.diagram_cards[0]
    assert mermaid_card.card_type == FeedItemType.DIAGRAM_OCCLUSION.value
    assert mermaid_card.kind == "mermaid"
    assert "[SLOT_1]" in (mermaid_card.occluded_mermaid or "")
    assert len(mermaid_card.answer_key) >= 1
    assert len(digest_plan.claims) >= 2
    assert "Speculative Decoding" in digest_plan.terms
    assert 3 <= digest_plan.total_cards <= 6

    # Also verify /api/later/digest-url endpoint enqueues durable job cleanly.
    monkeypatch.setattr(later_router, "get_postgres_client", AsyncMock(return_value=pg))
    monkeypatch.setattr(
        later_router,
        "enqueue_durable_job",
        AsyncMock(return_value=SimpleNamespace(id="job-digest-e2e")),
    )
    later_app = FastAPI()
    later_app.include_router(later_router.router)
    later_app.dependency_overrides[get_current_user] = lambda: {"id": USER_ML}
    later_resp = TestClient(later_app).post(
        "/api/later/digest-url",
        json={"url": substack_url, "title": digest_plan.title, "text": substack_markdown, "max_cards": 6},
    )
    assert later_resp.status_code == 200
    assert later_resp.json()["diagram_count"] == 1
    assert later_resp.json()["queued_job_id"] == "job-digest-e2e"


# ---------------------------------------------------------------------------
# 3. Feed Creative & Sandbox Cards Loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_feed_creative_injection_grading_and_sandbox_evidence_loop(monkeypatch):
    pg, neo = _build_seeded_environment()
    # Add Softmax Numerical Stability as a note-only ("seen") concept so sandbox evidence promotes it to "strong"!
    neo.concepts.append(
        {
            "id": "c-softmax",
            "user_id": USER_ML,
            "name": "Softmax Numerical Stability",
            "domain": "Deep Learning",
            "definition": "Subtracting max(logits) prior to exponentiation to prevent float overflow.",
            "complexity_score": 5,
        }
    )

    monkeypatch.setattr("backend.db.postgres_client.get_postgres_client", AsyncMock(return_value=pg))
    monkeypatch.setattr("backend.db.neo4j_client.get_neo4j_client", AsyncMock(return_value=neo))
    monkeypatch.setattr(feed_router, "get_postgres_client", AsyncMock(return_value=pg))
    monkeypatch.setattr(feed_router, "get_neo4j_client", AsyncMock(return_value=neo))
    monkeypatch.setattr(feed_router, "enqueue_durable_job", AsyncMock(return_value=None))

    # Verify FeedItemType enum members exist with exact wire values.
    assert FeedItemType.SPOT_THE_BUG.value == "spot_the_bug"
    assert FeedItemType.TRADEOFF_DUEL.value == "tradeoff_duel"
    assert FeedItemType.DIAGRAM_OCCLUSION.value == "diagram_occlusion"

    # Step 3a: Verify _add_creative_card injects at min(6, len(items)), respects item_types, domains, max_items.
    base_items = [
        FeedItem(
            id=f"fc-{idx}",
            item_type=FeedItemType.TERM_CARD,
            content={"front": f"Q{idx}", "back": f"A{idx}"},
            concept_id="c-hnsw" if idx == 0 else "c-softmax",
            concept_name="Multi-Tenant Vector Search" if idx == 0 else f"Topic {idx}",
            domain="Database Systems" if idx == 0 else "Deep Learning",
        )
        for idx in range(8)
    ]
    feed_resp = FeedResponse(
        items=list(base_items),
        total_due_today=8,
        completed_today=0,
        daily_goal=20,
        streak_days=5,
        domains=["Database Systems", "Deep Learning"],
    )
    req_all = FeedFilterRequest(user_id=USER_ML, max_items=20)
    await feed_router._add_creative_card(feed_resp, req_all)
    assert len(feed_resp.items) == 9
    injected = feed_resp.items[6]  # inserted at min(6, 8) == 6
    assert injected.item_type == FeedItemType.SPOT_THE_BUG
    assert injected.id == "spot_the_bug:bug-post-ann-filter"
    assert injected.content["card_type"] == "spot_the_bug"

    # Calling _add_creative_card when a spot_the_bug is already present or requesting tradeoff_duel picks tradeoff_duel!
    duel_resp = FeedResponse(
        items=[
            FeedItem(
                id="fc-rrf",
                item_type=FeedItemType.TERM_CARD,
                content={"front": "RRF", "back": "Rank fusion"},
                concept_id="c-rrf",
                concept_name="Hybrid Retrieval and Reranking",
                domain="RAG",
            )
        ],
        total_due_today=1,
        completed_today=0,
        daily_goal=20,
        streak_days=5,
        domains=["RAG"],
    )
    await feed_router._add_creative_card(
        duel_resp,
        FeedFilterRequest(user_id=USER_ML, item_types=[FeedItemType.TRADEOFF_DUEL], max_items=10),
    )
    assert len(duel_resp.items) == 2
    assert duel_resp.items[1].item_type == FeedItemType.TRADEOFF_DUEL
    assert duel_resp.items[1].id == "tradeoff_duel:duel-cross-encoder-vs-rrf"

    # Respects item_types exclusion (e.g. only flashcards requested -> no creative card).
    flashcard_only_resp = FeedResponse(
        items=list(base_items[:3]),
        total_due_today=3,
        completed_today=0,
        daily_goal=20,
        streak_days=5,
    )
    await feed_router._add_creative_card(
        flashcard_only_resp,
        FeedFilterRequest(user_id=USER_ML, item_types=[FeedItemType.TERM_CARD], max_items=10),
    )
    assert len(flashcard_only_resp.items) == 3

    # Respects unrelated domain filter (e.g. Quantum Biology -> skips injection) and max_items cap.
    unrelated_domain_resp = FeedResponse(
        items=[],
        total_due_today=0,
        completed_today=0,
        daily_goal=20,
        streak_days=5,
    )
    await feed_router._add_creative_card(
        unrelated_domain_resp,
        FeedFilterRequest(user_id=USER_ML, domains=["Quantum Biology"], max_items=10),
    )
    assert unrelated_domain_resp.items == []

    capped_resp = FeedResponse(
        items=list(base_items[:5]),
        total_due_today=5,
        completed_today=0,
        daily_goal=20,
        streak_days=5,
    )
    await feed_router._add_creative_card(
        capped_resp,
        FeedFilterRequest(user_id=USER_ML, max_items=5),
    )
    assert len(capped_resp.items) == 5
    assert any(i.item_type in {FeedItemType.SPOT_THE_BUG, FeedItemType.TRADEOFF_DUEL} for i in capped_resp.items)

    # Full GET /api/feed endpoint wires _add_sandbox_card + _add_creative_card and survives selector exceptions.
    async def _fake_service_get_feed(self, request: FeedFilterRequest) -> FeedResponse:
        return FeedResponse(
            items=list(base_items[:5]),
            total_due_today=5,
            completed_today=1,
            daily_goal=20,
            streak_days=7,
            domains=["Database Systems", "Deep Learning"],
        )

    monkeypatch.setattr(feed_router.FeedService, "get_feed", _fake_service_get_feed)
    monkeypatch.setattr(feed_router.FeedService, "get_daily_goal", AsyncMock(return_value=20))

    feed_app = FastAPI()
    feed_app.include_router(feed_router.router)
    feed_app.dependency_overrides[get_current_user] = lambda: {"id": USER_ML}
    feed_client = TestClient(feed_app)

    live_feed = feed_client.get("/api/feed?max_items=20")
    assert live_feed.status_code == 200, live_feed.text
    returned_types = [it["item_type"] for it in live_feed.json()["items"]]
    assert "code_sandbox" in returned_types
    assert any(t in {"spot_the_bug", "tradeoff_duel"} for t in returned_types)

    # Step 3b: Grade Spot-the-Bug card -> records `quiz` evidence in knowledge_evidence.
    before_softmax = (await km.assess(USER_ML, ["Softmax Numerical Stability"], pg=pg, neo4j=neo))[0]
    assert before_softmax.status == "seen"  # note-only before active recall

    grade_resp = feed_client.post(
        "/api/feed/spot-the-bug-grade",
        json={"card_id": "bug-softmax-overflow", "selected_line": 3},
    )
    assert grade_resp.status_code == 200
    graded = grade_resp.json()
    assert graded["correct"] is True
    assert graded["concept_id"] == "c-softmax"
    assert graded["evidence"]["score"] == 0.85

    quiz_ev = [
        e for e in pg.evidence if e["user_id"] == USER_ML and e["source_id"] == "spot_the_bug:bug-softmax-overflow"
    ]
    assert len(quiz_ev) == 1 and quiz_ev[0]["kind"] == "quiz" and quiz_ev[0]["signal"] == pytest.approx(0.85)

    # Step 3c: Submit Code Sandbox completion -> compute_sandbox_evidence + POST /api/feed/sandbox-result
    # records `sandbox` evidence and promotes Softmax Numerical Stability to `strong` (tested)!
    direct_ev = compute_sandbox_evidence(
        CodeSandboxSubmission(
            challenge_id="softmax-stable",
            concept_id="c-softmax",
            concept_name="Softmax Numerical Stability",
            passed_tests=4,
            total_tests=4,
            elapsed_ms=42,
        )
    )
    assert direct_ev["signal_type"] == "code_sandbox_pass"
    assert direct_ev["score"] == 0.90

    sb_resp = feed_client.post(
        "/api/feed/sandbox-result",
        json={
            "challenge_id": "softmax-stable",
            "concept_name": "Softmax Numerical Stability",
            "passed": 4,
            "total": 4,
            "elapsed_ms": 42,
        },
    )
    assert sb_resp.status_code == 200
    sb_body = sb_resp.json()
    assert sb_body["recorded"] is True
    assert sb_body["signal"] == 0.90
    assert sb_body["concept_id"] == "c-softmax"

    sandbox_ev = [
        e for e in pg.evidence if e["user_id"] == USER_ML and e["source_id"] == "sandbox:softmax-stable"
    ]
    assert len(sandbox_ev) == 1 and sandbox_ev[0]["kind"] == "sandbox" and sandbox_ev[0]["signal"] == pytest.approx(0.90)

    after_softmax = (await km.assess(USER_ML, ["Softmax Numerical Stability"], pg=pg, neo4j=neo))[0]
    assert after_softmax.status == "strong"
    assert after_softmax.basis == "tested"
    assert after_softmax.mastery is not None and after_softmax.mastery >= 0.75

    # Verify exception resilience in _add_creative_card: feed still succeeds 200 OK if selector raises.
    def _boom(*_args, **_kwargs):
        raise RuntimeError("synthetic creative card selector failure")

    monkeypatch.setattr(creative_cards, "select_spot_the_bug", _boom)
    resilient_resp = feed_client.get("/api/feed?max_items=20")
    assert resilient_resp.status_code == 200
