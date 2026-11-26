"""Read-only knowledge views for the agent (``read:knowledge`` scope).

Uses the same stores as the app: Neo4j ``Concept`` nodes (``user_id`` property) and
Postgres ``proficiency_scores`` / ``notes``. Every query is filtered by ``user_id``.
Output is deliberately compact (truncated definitions, no raw note bodies) because it
leaves GraphRecall and goes to an external agent.
"""

from __future__ import annotations

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
                "SELECT concept_id, score FROM proficiency_scores WHERE user_id = :user_id",
                {"user_id": user_id},
            )
        else:
            rows = await self.pg.execute_query(
                "SELECT concept_id, score FROM proficiency_scores "
                "WHERE user_id = :user_id AND concept_id = ANY(:cids)",
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
