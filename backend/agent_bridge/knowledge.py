"""Read-only knowledge views for the agent (``read:knowledge`` scope).

Uses the same stores as the app: Neo4j ``Concept`` nodes (``user_id`` property) and
Postgres ``proficiency_scores`` / ``notes``. Every query is filtered by ``user_id``.
Output is deliberately compact (truncated definitions, no raw note bodies) because it
leaves GraphRecall and goes to an external agent.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import uuid
from typing import Any, Optional

import structlog

from backend.services.spaced_repetition import SpacedRepetitionService

logger = structlog.get_logger()

MAX_DEFINITION_CHARS = 280
MAX_NEIGHBORS = 25
WEAK_THRESHOLD = 0.5


def _clip(text: Optional[str], n: int = MAX_DEFINITION_CHARS) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "\u2026"


def _concept_view(c: dict, mastery: Optional[float] = None) -> dict:
    return {
        "id": c.get("id"),
        "name": c.get("name"),
        "domain": c.get("domain") or "General",
        "definition": _clip(c.get("definition")),
        "complexity": c.get("complexity_score"),
        "mastery": None if mastery is None else round(float(mastery), 2),
    }


class KnowledgeService:
    def __init__(self, pg_client: Any, neo4j_client: Any):
        self.pg = pg_client
        self.neo4j = neo4j_client
        self.sr = SpacedRepetitionService(pg_client)

    async def _mastery_map(self, user_id: str, concept_ids: Optional[list[str]] = None) -> dict:
        if concept_ids is not None and not concept_ids:
            return {}
        if concept_ids is None:
            rows = await self.pg.execute_query(
                "SELECT concept_id, score FROM proficiency_scores WHERE user_id = :user_id "
                "AND COALESCE(total_reviews, 0) > 0",  # placeholder rows for new concepts aren't reviews
                {"user_id": user_id},
            )
        else:
            rows = await self.pg.execute_query(
                "SELECT concept_id, score FROM proficiency_scores "
                "WHERE user_id = :user_id AND concept_id = ANY(:cids) AND COALESCE(total_reviews, 0) > 0",
                {"user_id": user_id, "cids": concept_ids},
            )
        return {r["concept_id"]: float(r["score"] or 0) for r in rows}

    async def _concepts_by_ids(self, user_id: str, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        rows = await self.neo4j.execute_query(
            "MATCH (c:Concept) WHERE c.id IN $ids AND c.user_id = $user_id RETURN c",
            {"ids": ids, "user_id": user_id},
        )
        return {r["c"]["id"]: r["c"] for r in rows if r.get("c")}

    async def get_knowledge_profile(self, user_id: str, limit: int = 10) -> dict:
        concepts = await self.neo4j.execute_query(
            """
            MATCH (c:Concept {user_id: $user_id})
            RETURN c.id AS id, c.name AS name, c.domain AS domain
            """,
            {"user_id": user_id},
        )
        mastery = await self._mastery_map(user_id)
        # Only reviewed concepts have a mastery. Counting the never-reviewed ones as 0 made
        # "weak_concepts" a list of untested concepts, and dragged every domain average down.
        domains: dict[str, dict] = {}
        scored = []
        for c in concepts:
            d = domains.setdefault(c.get("domain") or "General", {"concepts": 0, "scores": []})
            d["concepts"] += 1
            score = mastery.get(c["id"])
            if score is None:
                continue
            d["scores"].append(score)
            scored.append({"id": c["id"], "name": c.get("name"),
                           "domain": c.get("domain") or "General", "mastery": round(score, 2)})
        scored.sort(key=lambda x: x["mastery"])
        due = await self.sr.get_due_items(user_id=user_id, limit=200, include_overdue=True)
        return {
            "total_concepts": len(concepts),
            "reviewed_concepts": len(scored),
            "domains": [
                {"domain": name, "concepts": d["concepts"], "untested": d["concepts"] - len(d["scores"]),
                 "avg_mastery": round(sum(d["scores"]) / len(d["scores"]), 2) if d["scores"] else None}
                for name, d in sorted(domains.items(), key=lambda kv: -kv[1]["concepts"])
            ],
            "weak_concepts": [c for c in scored if c["mastery"] < WEAK_THRESHOLD][:limit],
            "strong_concepts": [c for c in reversed(scored) if c["mastery"] >= WEAK_THRESHOLD][:limit],
            "due_review_count": len(due),
            # TODO(agent-bridge): add exam/goal context once GraphRecall stores goals
            # (e.g. users.settings_json["goals"]) so the agent can prioritise exam topics.
        }

    async def search_concepts(self, user_id: str, query: str, limit: int = 10) -> list[dict]:
        # TODO(agent-bridge): switch to the hybrid/vector retrieval in
        # backend/services/retrieval_service.py for semantic matches.
        rows = await self.neo4j.execute_query(
            """
            MATCH (c:Concept {user_id: $user_id})
            WHERE toLower(c.name) CONTAINS toLower($q)
               OR toLower(coalesce(c.definition, '')) CONTAINS toLower($q)
            RETURN c
            ORDER BY CASE WHEN toLower(c.name) CONTAINS toLower($q) THEN 0 ELSE 1 END, c.name
            LIMIT $limit
            """,
            {"user_id": user_id, "q": query, "limit": limit},
        )
        cs = [r["c"] for r in rows if r.get("c")]
        mastery = await self._mastery_map(user_id, [c["id"] for c in cs])
        return [_concept_view(c, mastery.get(c["id"], 0.0)) for c in cs]

    async def get_concept_neighborhood(
        self, user_id: str, concept_id: str, limit: int = 15
    ) -> Optional[dict]:
        limit = max(1, min(limit, MAX_NEIGHBORS))
        # Bounded 1-hop. Both endpoints must belong to the user.
        rows = await self.neo4j.execute_query(
            """
            MATCH (c:Concept {id: $id, user_id: $user_id})
            OPTIONAL MATCH (c)-[r]-(n:Concept {user_id: $user_id})
            WITH c, r, n LIMIT $limit
            RETURN c, type(r) AS rel, n,
                   CASE WHEN r IS NULL THEN null WHEN startNode(r) = c THEN 'out' ELSE 'in' END AS dir
            """,
            {"id": concept_id, "user_id": user_id, "limit": limit},
        )
        if not rows:
            return None
        center = rows[0]["c"]
        neighbors = [r for r in rows if r.get("n")]
        ids = [center["id"]] + [r["n"]["id"] for r in neighbors]
        mastery = await self._mastery_map(user_id, ids)
        return {
            "concept": _concept_view(center, mastery.get(center["id"], 0.0)),
            "neighbors": [
                {
                    "relationship": r.get("rel"),
                    "direction": r.get("dir"),
                    **_concept_view(r["n"], mastery.get(r["n"]["id"], 0.0)),
                }
                for r in neighbors
            ],
        }

    async def list_due_reviews(self, user_id: str, limit: int = 20) -> list[dict]:
        due = await self.sr.get_due_items(user_id=user_id, limit=limit, include_overdue=True)
        ids = [d["sm2_data"]["item_id"] for d in due]
        concepts = await self._concepts_by_ids(user_id, ids)
        out = []
        for d in due:
            cid = d["sm2_data"]["item_id"]
            c = concepts.get(cid)
            if not c:
                continue  # stale proficiency row; never leak ids without an owned concept
            nr = d["sm2_data"].get("next_review")
            out.append({
                **_concept_view(c, d.get("mastery_score")),
                "next_review": nr.isoformat() if hasattr(nr, "isoformat") else nr,
                "priority": round(float(d.get("priority_score") or 0), 3),
            })
        return out

    async def get_recent_activity(self, user_id: str, days: int = 7, limit: int = 20) -> dict:
        days = max(1, min(days, 90))
        reviews = await self.pg.execute_query(
            """
            SELECT concept_id, score, last_reviewed FROM proficiency_scores
            WHERE user_id = :user_id AND last_reviewed >= NOW() - make_interval(days => :days)
            ORDER BY last_reviewed DESC LIMIT :limit
            """,
            {"user_id": user_id, "days": days, "limit": limit},
        )
        notes = await self.pg.execute_query(
            """
            SELECT id, title, resource_type, source_url, created_at FROM notes
            WHERE user_id = :user_id AND created_at >= NOW() - make_interval(days => :days)
            ORDER BY created_at DESC LIMIT :limit
            """,
            {"user_id": user_id, "days": days, "limit": limit},
        )
        concepts = await self._concepts_by_ids(user_id, [r["concept_id"] for r in reviews])

        def _iso(v: Any) -> Any:
            return v.isoformat() if hasattr(v, "isoformat") else v

        return {
            "days": days,
            "reviews": [
                {
                    "concept_id": r["concept_id"],
                    "name": concepts.get(r["concept_id"], {}).get("name"),
                    "mastery": round(float(r["score"] or 0), 2),
                    "last_reviewed": _iso(r["last_reviewed"]),
                }
                for r in reviews
                if r["concept_id"] in concepts
            ],
            # Titles/links only - note bodies never leave GraphRecall through the bridge.
            "notes_added": [
                {
                    "id": str(n["id"]),
                    "title": n.get("title"),
                    "resource_type": n.get("resource_type"),
                    "source_url": n.get("source_url"),
                    "created_at": _iso(n.get("created_at")),
                }
                for n in notes
            ],
        }

    async def owned_concept_ids(self, user_id: str, concept_ids: list[str]) -> set[str]:
        return set((await self._concepts_by_ids(user_id, concept_ids)).keys())

    async def get_knowledge_frontier(
        self,
        user_id: str,
        query: str,
        concept_names: Optional[list[str]] = None,
        max_hops: int = 2,
    ) -> dict[str, Any]:
        """Return a prompt-cache-friendly profile prefix hash + per-query knowledge frontier."""
        from backend.services import knowledge_map as km
        from backend.services.graph_hierarchy import load_concept_provenance

        max_hops = max(1, min(int(max_hops), 3))
        all_concepts = await km._user_concepts(self.neo4j, user_id)

        # Stable cacheable prefix hash over compact domain summary
        profile = await self.get_knowledge_profile(user_id, limit=12)
        stable_prefix = {
            "total_concepts": profile.get("total_concepts", 0),
            "reviewed_concepts": profile.get("reviewed_concepts", 0),
            "domains": profile.get("domains", []),
        }
        profile_prefix_hash = hashlib.sha256(
            json.dumps(stable_prefix, sort_keys=True).encode("utf-8")
        ).hexdigest()

        # Resolve candidate names from explicit list + query tokens/substrings
        requested_names = [n.strip() for n in (concept_names or []) if n and n.strip()]
        query_lower = (query or "").strip().lower()
        seed_concepts: dict[str, dict] = {}
        unmatched_names: list[str] = []

        for name in requested_names:
            hit = km.match_concept(name, all_concepts)
            if hit:
                seed_concepts[hit["id"]] = hit
            else:
                unmatched_names.append(name)

        query_terms = [t for t in re.findall(r"[a-z0-9+#-]{3,}", query_lower)]
        for c in all_concepts:
            cname = (c.get("name") or "").lower()
            if cname and (cname in query_lower or any(t in cname for t in query_terms)):
                seed_concepts[c["id"]] = c

        seed_ids = list(seed_concepts.keys())[:15]
        neighbor_concepts: dict[str, dict] = dict(seed_concepts)
        if seed_ids:
            rel_rows = await self.neo4j.execute_query(
                f"""
                MATCH (s:Concept {{user_id: $user_id}})-[r*1..{max_hops}]-(n:Concept {{user_id: $user_id}})
                WHERE s.id IN $seed_ids AND n.id <> s.id
                RETURN DISTINCT n.id AS id, n.name AS name, n.domain AS domain, n.definition AS definition
                LIMIT 40
                """,
                {"user_id": user_id, "seed_ids": seed_ids},
            )
            for r in rel_rows or []:
                cid = r.get("id")
                if cid and cid not in neighbor_concepts:
                    k = km.skill_key(r.get("name") or "")
                    neighbor_concepts[cid] = {**dict(r), "_key": k, "_words": set(k.split())}

        assess_names = [c["name"] for c in neighbor_concepts.values() if c.get("name")] + unmatched_names
        assess_names = list(dict.fromkeys(assess_names))[:60]
        assessments = (
            await km.assess(
                user_id,
                assess_names,
                pg=self.pg,
                neo4j=self.neo4j,
                concepts=all_concepts,
                max_names=60,
            )
            if assess_names
            else []
        )

        anchors, frontier, gaps, seen_untested = [], [], [], []
        assessed_ids: list[str] = []
        shaky_or_gap_keys: set[str] = set()
        for a in assessments:
            entry = {
                "name": a.name,
                "concept_id": a.concept_id,
                "concept_name": a.concept_name,
                "domain": a.domain,
                "status": a.status,
                "mastery": a.mastery,
                "confidence": a.confidence,
                "basis": a.basis,
            }
            if a.concept_id:
                assessed_ids.append(a.concept_id)
            if a.status == "strong":
                anchors.append(entry)
            elif a.status == "shaky":
                frontier.append(entry)
                shaky_or_gap_keys.add(a.key)
            elif a.status == "seen":
                seen_untested.append(entry)
            else:
                gaps.append(entry)
                shaky_or_gap_keys.add(a.key)

        # Misconceptions (low-signal test evidence or low review scores)
        misconceptions: list[dict[str, Any]] = []
        if assessed_ids:
            try:
                ev_rows = await self.pg.execute_query(
                    """
                    SELECT concept_id, kind, signal, detail, created_at
                    FROM knowledge_evidence
                    WHERE user_id = CAST(:u AS uuid)
                      AND concept_id = ANY(:cids)
                      AND kind IN ('quiz', 'review', 'territory', 'leetcode')
                      AND signal < 0.45
                    ORDER BY created_at DESC
                    LIMIT 10
                    """,
                    {"u": user_id, "cids": assessed_ids},
                )
                id_to_name = {c["id"]: c.get("name") for c in neighbor_concepts.values()}
                for r in ev_rows or []:
                    ca = r.get("created_at")
                    misconceptions.append({
                        "concept_id": r["concept_id"],
                        "concept_name": id_to_name.get(r["concept_id"]),
                        "kind": r["kind"],
                        "signal": round(float(r["signal"]), 2),
                        "detail": r.get("detail") if isinstance(r.get("detail"), dict) else {},
                        "at": ca.isoformat() if hasattr(ca, "isoformat") else ca,
                    })
            except Exception:
                pass

        # Provenance across top seed concepts
        provenance: list[dict[str, Any]] = []
        for cid in seed_ids[:5]:
            cname = seed_concepts[cid].get("name")
            items = await load_concept_provenance(
                user_id, cid, concept_name=cname, neo4j=self.neo4j, pg=self.pg, limit=4
            )
            for it in items:
                provenance.append({"concept_id": cid, "concept_name": cname, **it})

        # Resume claims overlapping query/frontier whose mastery is shaky or unexposed
        resume_claims_at_risk: list[dict[str, Any]] = []
        try:
            res_rows = await self.pg.execute_query(
                "SELECT skills FROM user_resumes WHERE user_id = CAST(:u AS uuid) ORDER BY created_at DESC LIMIT 1",
                {"u": user_id},
            )
            raw_skills = (res_rows[0].get("skills") if res_rows else None) or []
            if isinstance(raw_skills, str):
                raw_skills = json.loads(raw_skills)
            for sk in raw_skills:
                sname = (sk.get("name") if isinstance(sk, dict) else str(sk)) or ""
                skey = km.skill_key(sname)
                if skey and (skey in shaky_or_gap_keys or any(t in sname.lower() for t in query_terms)):
                    resume_claims_at_risk.append({"skill": sname, "section": sk.get("section") if isinstance(sk, dict) else None})
        except Exception:
            pass

        return {
            "query": query,
            "profile_prefix_hash": profile_prefix_hash,
            "stable_profile_summary": stable_prefix,
            "anchors": anchors[:12],
            "frontier": frontier[:12],
            "gaps": gaps[:12],
            "seen_untested": seen_untested[:12],
            "misconceptions": misconceptions,
            "provenance": provenance[:12],
            "resume_claims_at_risk": resume_claims_at_risk[:10],
        }

    async def record_exposure(
        self,
        user_id: str,
        concept: str,
        context: str,
        *,
        source: str = "agent_session",
        confidence: float = 0.5,
        source_url: Optional[str] = None,
        create_if_missing: bool = False,
    ) -> dict[str, Any]:
        """Write back an exposure signal from an external agent session into knowledge_evidence & user_skills."""
        from backend.services import knowledge_map as km

        concepts = await km._user_concepts(self.neo4j, user_id)
        hit = km.match_concept(concept, concepts)
        concept_id = hit["id"] if hit else None
        created_node = False

        if concept_id is None and create_if_missing:
            concept_id = str(uuid.uuid4())
            created_node = True
            await self.neo4j.execute_query(
                """
                CREATE (c:Concept {
                    id: $id,
                    user_id: $user_id,
                    name: $name,
                    name_normalized: $norm,
                    domain: 'General',
                    complexity_score: 5,
                    created_at: datetime()
                })
                """,
                {"id": concept_id, "user_id": user_id, "name": concept.strip(), "norm": km.skill_key(concept)},
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        detail = {
            "context": context[:600],
            "source": source,
            "source_url": source_url,
            "recorded_at": now_iso,
        }
        await km.add_evidence(
            self.pg,
            user_id,
            kind="agent",
            signal=max(0.0, min(1.0, float(confidence))),
            weight=0.5,
            concept_id=concept_id,
            skill_name=concept.strip(),
            source_id=source,
            detail=detail,
        )
        await km.upsert_skill(
            self.pg,
            user_id,
            concept.strip(),
            source="agent",
            concept_id=concept_id,
        )
        return {
            "ok": True,
            "concept": hit["name"] if hit else concept.strip(),
            "concept_id": concept_id,
            "matched_existing": hit is not None,
            "created_node": created_node,
            "recorded_at": now_iso,
        }
