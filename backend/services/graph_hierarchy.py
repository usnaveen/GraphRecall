"""Hierarchical knowledge-graph views (Universe -> Galaxy -> Concepts), recall outline & provenance.

Implements the GR-V3-GRAPH-API-01 contract:
- Edge normalization: ``prerequisite | subtopic | builds_on | applies_to | related`` (always keeping ``raw_type``).
- ``RELATED_TO`` stays ``type: "related", direction: "none"`` and is omitted from hierarchy levels
  unless ``include_related=True``; always included in focus neighborhoods.
- Status vocabulary matches ``knowledge_map``: ``strong | shaky | seen | unexposed``.
- ``color_key`` is normalized subject name for Universe domains and community id for Galaxies/concepts.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Literal, Optional

from backend.services import knowledge_map as km
from backend.services.community_service import CommunityService

_SUBJECT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Machine Learning",
        (
            "machine learning",
            "deep learning",
            "natural language processing",
            "nlp",
            "llm",
            "large language",
            "transformer",
            "attention",
            "neural network",
            "reinforcement learning",
            "computer vision",
            "generative ai",
            "ai",
            "ml",
            "rag",
        ),
    ),
    (
        "Mathematics",
        (
            "math",
            "geometry",
            "linear algebra",
            "calculus",
            "probability",
            "statistics",
            "optimization",
            "number theory",
            "discrete math",
        ),
    ),
    ("LeetCode Patterns", ("leetcode", "coding interview", "competitive programming", "sliding window", "two pointers")),
    ("Computer Science", ("computer science", "algorithm", "data structure", "compiler", "operating system", "theory")),
    ("Systems & Infrastructure", ("system design", "distributed", "networking", "architecture", "cloud", "kubernetes", "docker")),
    ("Databases", ("database", "sql", "postgres", "neo4j", "storage engine", "indexing")),
    ("Software Engineering", ("software", "programming", "python", "swift", "ios", "typescript", "backend", "frontend", "testing")),
    ("Product & Research", ("product", "research", "writing", "reading", "economics", "finance", "biology")),
)

_STATUS_COLOR_HINT = {
    "strong": "green",
    "shaky": "red",
    "seen": "amber",
    "unexposed": "grey",
}

_DIRECTED_RAW_MAP: dict[str, tuple[str, str]] = {
    "PREREQUISITE_OF": ("prerequisite", "forward"),
    "SUBTOPIC_OF": ("subtopic", "forward"),
    "PART_OF": ("subtopic", "forward"),
    "BUILDS_ON": ("builds_on", "forward"),
    "APPLIES_TO": ("applies_to", "forward"),
    "RELATED_TO": ("related", "none"),
}


def normalize_edge_type(raw_type: Optional[str]) -> tuple[str, str]:
    """Return ``(normalized_type, direction)`` preserving undirected ``RELATED_TO``."""
    key = (raw_type or "RELATED_TO").strip().upper()
    return _DIRECTED_RAW_MAP.get(key, ("related", "none"))


def normalize_subject(raw_domain: Optional[str]) -> str:
    """Map free-text Neo4j concept domains into a clean ~8-15 subject taxonomy."""
    text = re.sub(r"\s+", " ", (raw_domain or "").strip())
    if not text:
        return "General"
    lowered = text.lower()
    for subject, keywords in _SUBJECT_RULES:
        for kw in keywords:
            if len(kw) <= 3:
                if re.search(rf"\b{re.escape(kw)}\b", lowered):
                    return subject
            elif kw in lowered:
                return subject
    return text.title() if text.islower() else text


async def _load_concepts_and_edges(neo4j: Any, user_id: str) -> tuple[list[dict], list[dict]]:
    concepts = await neo4j.execute_query(
        """
        MATCH (c:Concept {user_id: $user_id})
        RETURN c.id AS id, c.name AS name, c.domain AS domain,
               c.definition AS definition,
               coalesce(c.complexity_score, 5) AS complexity_score
        """,
        {"user_id": user_id},
    )
    edges = await neo4j.execute_query(
        """
        MATCH (c1:Concept {user_id: $user_id})-[r]->(c2:Concept {user_id: $user_id})
        RETURN c1.id AS source, c2.id AS target, type(r) AS raw_type,
               coalesce(r.strength, 1.0) AS strength,
               elementId(r) AS edge_id
        """,
        {"user_id": user_id},
    )
    return [dict(c) for c in (concepts or []) if c.get("id")], [dict(e) for e in (edges or [])]


async def _status_map_for_concepts(
    pg: Any,
    user_id: str,
    concepts: list[dict],
) -> dict[str, dict[str, Any]]:
    """Compute knowledge_map-compatible ``{status, mastery, confidence, basis}`` per concept_id."""
    if not concepts:
        return {}
    cids = [c["id"] for c in concepts]
    names = [c.get("name") or "" for c in concepts]
    keys = [km.skill_key(n) for n in names if km.skill_key(n)]
    by_concept, by_key, reviews, skills = await km._load_state(pg, user_id, cids, keys)
    out: dict[str, dict[str, Any]] = {}
    for c in concepts:
        cid = c["id"]
        key = km.skill_key(c.get("name") or "")
        ev = list(by_key.get(key, [])) + list(by_concept.get(cid, []))
        if not any(e.kind == "review" for e in ev):
            ev += km._review_evidence(reviews.get(cid))
        ev.append(km.Evidence("note", 0.35, km.DEFAULT_WEIGHT["note"]))
        rating = (skills.get(key) or {}).get("self_rating")
        status, mastery, conf, basis = km.score(ev, in_graph=True, self_rating=rating)
        out[cid] = {
            "status": status if status in km.STATUSES else "seen",
            "mastery": mastery,
            "confidence": conf,
            "basis": basis,
        }
    return out


async def _community_assignments(
    user_id: str,
    concepts: list[dict],
    pg: Any,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Return ``(communities_by_id, concept_id -> community_id)`` falling back to domain buckets."""
    communities: list[dict[str, Any]] = []
    if pg is not None:
        try:
            service = CommunityService()
            # CommunityService.get_communities resolves get_postgres_client() unless overridden;
            # support injecting lightweight fake rows when testing without global DB pools.
            if hasattr(pg, "_fake_communities"):
                communities = list(pg._fake_communities)
            else:
                communities = await service.get_communities(user_id)
        except Exception:
            communities = []

    by_id: dict[str, dict[str, Any]] = {}
    concept_to_comm: dict[str, str] = {}
    # Prefer finest populated level (level 0 or 1)
    sorted_comms = sorted(communities, key=lambda item: (item.get("level", 1), -(item.get("size") or 0)))
    for comm in sorted_comms:
        cid = str(comm.get("id") or "")
        if not cid:
            continue
        by_id[cid] = dict(comm)
        for member_id in comm.get("entity_ids") or []:
            if member_id not in concept_to_comm:
                concept_to_comm[str(member_id)] = cid

    # Deterministic subject-backed community fallback for unclustered concepts
    for c in concepts:
        cid = c["id"]
        if cid not in concept_to_comm:
            subj = normalize_subject(c.get("domain"))
            fallback_id = f"subject:{subj.lower().replace(' ', '-')}"
            if fallback_id not in by_id:
                by_id[fallback_id] = {
                    "id": fallback_id,
                    "title": subj,
                    "level": 1,
                    "summary": "",
                    "entity_ids": [],
                }
            concept_to_comm[cid] = fallback_id
            by_id[fallback_id].setdefault("entity_ids", []).append(cid)

    return by_id, concept_to_comm


def _status_bucket(items: list[dict[str, Any]], status_map: dict[str, dict[str, Any]]) -> tuple[dict[str, int], Optional[float]]:
    counts = {s: 0 for s in km.STATUSES}
    masteries: list[float] = []
    for item in items:
        st = status_map.get(item["id"], {"status": "seen", "mastery": None})
        status = st["status"]
        counts[status] = counts.get(status, 0) + 1
        if st.get("mastery") is not None:
            masteries.append(float(st["mastery"]))
    avg = round(sum(masteries) / len(masteries), 3) if masteries else None
    return counts, avg


async def get_hierarchy(
    user_id: str,
    level: Literal["universe", "galaxy", "concepts"] = "universe",
    *,
    domain: Optional[str] = None,
    community_id: Optional[str] = None,
    include_related: bool = False,
    neo4j: Any,
    pg: Any,
) -> dict[str, Any]:
    """Return one hierarchical level (``universe | galaxy | concepts``) with normalized directed edges."""
    concepts, raw_edges = await _load_concepts_and_edges(neo4j, user_id)
    status_map = await _status_map_for_concepts(pg, user_id, concepts)
    comms_by_id, concept_to_comm = await _community_assignments(user_id, concepts, pg)

    concept_by_id = {c["id"]: c for c in concepts}
    subject_of = {c["id"]: normalize_subject(c.get("domain")) for c in concepts}
    target_subject = normalize_subject(domain) if domain else None

    if level == "universe":
        by_subj: dict[str, list[dict]] = defaultdict(list)
        comms_per_subj: dict[str, set[str]] = defaultdict(set)
        for c in concepts:
            subj = subject_of[c["id"]]
            by_subj[subj].append(c)
            comms_per_subj[subj].add(concept_to_comm[c["id"]])

        nodes = []
        for subj, members in sorted(by_subj.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            counts, avg = _status_bucket(members, status_map)
            nodes.append({
                "id": subj,
                "label": subj,
                "level": "universe",
                "color_key": subj,
                "concept_count": len(members),
                "community_count": len(comms_per_subj[subj]),
                "status_counts": counts,
                "avg_mastery": avg,
            })

        agg: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for e in raw_edges:
            norm_type, direction = normalize_edge_type(e.get("raw_type"))
            if norm_type == "related" and not include_related:
                continue
            s_subj = subject_of.get(e["source"])
            t_subj = subject_of.get(e["target"])
            if not s_subj or not t_subj or s_subj == t_subj:
                continue
            key = (s_subj, t_subj, norm_type, e.get("raw_type") or "RELATED_TO")
            entry = agg.setdefault(
                key,
                {
                    "id": f"{s_subj}->{t_subj}:{norm_type}",
                    "source": s_subj,
                    "target": t_subj,
                    "type": norm_type,
                    "raw_type": e.get("raw_type") or "RELATED_TO",
                    "direction": direction,
                    "weight": 0,
                },
            )
            entry["weight"] += 1

        return {"level": "universe", "nodes": nodes, "edges": list(agg.values()), "include_related": include_related}

    if level == "galaxy":
        by_comm: dict[str, list[dict]] = defaultdict(list)
        for c in concepts:
            subj = subject_of[c["id"]]
            if target_subject and subj != target_subject:
                continue
            by_comm[concept_to_comm[c["id"]]].append(c)

        nodes = []
        for cid, members in sorted(by_comm.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            meta = comms_by_id.get(cid, {})
            counts, avg = _status_bucket(members, status_map)
            dom_counts: dict[str, int] = defaultdict(int)
            for m in members:
                dom_counts[subject_of[m["id"]]] += 1
            dom = max(dom_counts, key=dom_counts.get)
            nodes.append({
                "id": cid,
                "label": meta.get("title") or dom,
                "summary": meta.get("summary") or "",
                "domain": dom,
                "level": "galaxy",
                "color_key": cid,
                "concept_count": len(members),
                "status_counts": counts,
                "avg_mastery": avg,
            })

        visible_comms = set(by_comm.keys())
        agg_g: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for e in raw_edges:
            norm_type, direction = normalize_edge_type(e.get("raw_type"))
            if norm_type == "related" and not include_related:
                continue
            sc = concept_to_comm.get(e["source"])
            tc = concept_to_comm.get(e["target"])
            if not sc or not tc or sc == tc:
                continue
            if sc not in visible_comms or tc not in visible_comms:
                continue
            key = (sc, tc, norm_type, e.get("raw_type") or "RELATED_TO")
            entry = agg_g.setdefault(
                key,
                {
                    "id": f"{sc}->{tc}:{norm_type}",
                    "source": sc,
                    "target": tc,
                    "type": norm_type,
                    "raw_type": e.get("raw_type") or "RELATED_TO",
                    "direction": direction,
                    "weight": 0,
                },
            )
            entry["weight"] += 1

        return {
            "level": "galaxy",
            "domain": target_subject,
            "nodes": nodes,
            "edges": list(agg_g.values()),
            "include_related": include_related,
        }

    # level == "concepts"
    filtered = []
    for c in concepts:
        cid = c["id"]
        if community_id and concept_to_comm.get(cid) != community_id:
            continue
        if target_subject and subject_of[cid] != target_subject:
            continue
        filtered.append(c)

    visible_ids = {c["id"] for c in filtered}
    nodes = []
    for c in filtered:
        cid = c["id"]
        st = status_map.get(cid, {"status": "seen", "mastery": None})
        comm_id = concept_to_comm[cid]
        nodes.append({
            "id": cid,
            "name": c.get("name") or cid,
            "definition": c.get("definition") or "",
            "domain": subject_of[cid],
            "raw_domain": c.get("domain") or "General",
            "community_id": comm_id,
            "color_key": comm_id,
            "status": st["status"],
            "mastery": st["mastery"],
            "complexity_score": c.get("complexity_score", 5),
            "level": "concepts",
        })

    edges = []
    for e in raw_edges:
        if e["source"] not in visible_ids or e["target"] not in visible_ids:
            continue
        norm_type, direction = normalize_edge_type(e.get("raw_type"))
        if norm_type == "related" and not include_related:
            continue
        if e["source"] not in concept_by_id or e["target"] not in concept_by_id:
            continue
        edges.append({
            "id": str(e.get("edge_id") or f"{e['source']}->{e['target']}"),
            "source": e["source"],
            "target": e["target"],
            "type": norm_type,
            "raw_type": e.get("raw_type") or "RELATED_TO",
            "direction": direction,
            "strength": float(e.get("strength") or 1.0),
        })

    return {
        "level": "concepts",
        "domain": target_subject,
        "community_id": community_id,
        "nodes": nodes,
        "edges": edges,
        "include_related": include_related,
    }


async def build_recall_outline(
    user_id: str,
    *,
    domain: Optional[str] = None,
    root_concept_id: Optional[str] = None,
    max_depth: int = 4,
    neo4j: Any,
    pg: Any,
) -> dict[str, Any]:
    """Build a cycle-safe hierarchical subject outline annotated with recall colors."""
    concepts, raw_edges = await _load_concepts_and_edges(neo4j, user_id)
    status_map = await _status_map_for_concepts(pg, user_id, concepts)
    subject_of = {c["id"]: normalize_subject(c.get("domain")) for c in concepts}
    target_subject = normalize_subject(domain) if domain else None

    scoped = [
        c for c in concepts
        if not target_subject or subject_of[c["id"]] == target_subject
    ]
    scoped_ids = {c["id"] for c in scoped}
    by_id = {c["id"]: c for c in scoped}

    # Parent -> children from (child)-[:SUBTOPIC_OF|PART_OF]->(parent) and (parent)-[:PREREQUISITE_OF]->(child)
    children_map: dict[str, list[dict[str, str]]] = defaultdict(list)
    has_parent: set[str] = set()
    for e in raw_edges:
        s, t = e["source"], e["target"]
        if s not in scoped_ids or t not in scoped_ids or s == t:
            continue
        norm_type, _ = normalize_edge_type(e.get("raw_type"))
        if norm_type == "subtopic":
            children_map[t].append({"id": s, "relation": "subtopic"})
            has_parent.add(s)
        elif norm_type in {"prerequisite", "builds_on"}:
            children_map[s].append({"id": t, "relation": norm_type})
            has_parent.add(t)

    def render_node(cid: str, depth: int, path: set[str], relation: Optional[str] = None) -> dict[str, Any]:
        c = by_id[cid]
        st = status_map.get(cid, {"status": "seen", "mastery": None})
        status = st["status"]
        node: dict[str, Any] = {
            "id": cid,
            "name": c.get("name") or cid,
            "domain": subject_of[cid],
            "status": status,
            "mastery": st["mastery"],
            "color_hint": _STATUS_COLOR_HINT.get(status, "grey"),
            "relation": relation,
            "children": [],
        }
        if depth >= max_depth:
            return node
        seen_child: set[str] = set()
        for link in sorted(children_map.get(cid, []), key=lambda x: (x["relation"], by_id[x["id"]].get("name", ""))):
            child_id = link["id"]
            if child_id in path or child_id in seen_child:
                continue
            seen_child.add(child_id)
            node["children"].append(render_node(child_id, depth + 1, path | {child_id}, link["relation"]))
        return node

    if root_concept_id and root_concept_id in by_id:
        roots = [render_node(root_concept_id, 1, {root_concept_id})]
    else:
        root_ids = [c["id"] for c in scoped if c["id"] not in has_parent]
        if not root_ids and scoped:
            # All scoped concepts belong to a cycle: pick nodes with highest out-degree first
            root_ids = sorted(scoped_ids, key=lambda cid: -len(children_map.get(cid, [])))[: min(10, len(scoped_ids))]
        roots = [render_node(rid, 1, {rid}) for rid in sorted(root_ids, key=lambda cid: by_id[cid].get("name", ""))]

    return {
        "domain": target_subject,
        "max_depth": max_depth,
        "total_concepts": len(scoped),
        "roots": roots,
    }


async def load_concept_provenance(
    user_id: str,
    concept_id: str,
    *,
    concept_name: Optional[str] = None,
    neo4j: Any,
    pg: Any,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Aggregate chronological 'Where I learned this' provenance for a concept."""
    timeline: list[dict[str, Any]] = []

    if neo4j is not None:
        note_rows = await neo4j.execute_query(
            """
            MATCH (n:NoteSource {user_id: $user_id})-[r:EXPLAINS]->(c:Concept {id: $cid, user_id: $user_id})
            RETURN n.id AS note_id, r.evidence_span AS evidence_span
            LIMIT 20
            """,
            {"user_id": user_id, "cid": concept_id},
        )
        note_ids = [str(r["note_id"]) for r in (note_rows or []) if r.get("note_id")]
        spans = {str(r["note_id"]): r.get("evidence_span") for r in (note_rows or []) if r.get("note_id")}
        if note_ids and pg is not None:
            pg_notes = await pg.execute_query(
                "SELECT id::text AS id, title, source_url, resource_type, created_at FROM notes "
                "WHERE user_id = CAST(:u AS uuid) AND id = ANY(:ids)",
                {"u": user_id, "ids": note_ids},
            )
            for row in pg_notes or []:
                nid = str(row["id"])
                timeline.append({
                    "kind": row.get("resource_type") or "note",
                    "title": row.get("title") or "Untitled note",
                    "source_url": row.get("source_url"),
                    "context": spans.get(nid) or "",
                    "recorded_at": row["created_at"].isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at"),
                })

    if pg is not None:
        try:
            res_rows = await pg.execute_query(
                """
                SELECT source_kind, publication_name, title, source_url, summary, matched_concepts,
                       COALESCE(published_at, created_at) AS recorded_at
                FROM ingested_resources
                WHERE user_id = CAST(:u AS uuid) AND dismissed_at IS NULL
                ORDER BY COALESCE(published_at, created_at) DESC
                LIMIT 50
                """,
                {"u": user_id},
            )
            cname_lower = (concept_name or "").strip().lower()
            for r in res_rows or []:
                mc = r.get("matched_concepts") or []
                if isinstance(mc, str):
                    try:
                        mc = json.loads(mc)
                    except Exception:
                        mc = []
                hit = any(
                    isinstance(m, dict)
                    and (str(m.get("id") or "") == concept_id or (cname_lower and str(m.get("name") or "").lower() == cname_lower))
                    for m in mc
                )
                if hit:
                    pub = r.get("publication_name")
                    timeline.append({
                        "kind": r.get("source_kind") or "link",
                        "title": f"{pub}: {r['title']}" if pub else r.get("title") or "Link",
                        "source_url": r.get("source_url"),
                        "context": r.get("summary") or "",
                        "recorded_at": r["recorded_at"].isoformat() if hasattr(r.get("recorded_at"), "isoformat") else r.get("recorded_at"),
                    })
        except Exception:
            pass

        try:
            ev_rows = await pg.execute_query(
                """
                SELECT kind, signal, source_id, detail, created_at
                FROM knowledge_evidence
                WHERE user_id = CAST(:u AS uuid) AND concept_id = :cid
                ORDER BY created_at DESC
                LIMIT 20
                """,
                {"u": user_id, "cid": concept_id},
            )
            for r in ev_rows or []:
                detail = r.get("detail") or {}
                if isinstance(detail, str):
                    try:
                        detail = json.loads(detail)
                    except Exception:
                        detail = {}
                kind = r.get("kind") or "evidence"
                timeline.append({
                    "kind": kind,
                    "title": detail.get("source") or f"{kind.title()} signal ({round(float(r.get('signal') or 0) * 100)}%)",
                    "source_url": detail.get("source_url"),
                    "context": detail.get("context") or "",
                    "recorded_at": r["created_at"].isoformat() if hasattr(r.get("created_at"), "isoformat") else r.get("created_at"),
                })
        except Exception:
            pass

    timeline.sort(key=lambda item: str(item.get("recorded_at") or ""), reverse=True)
    return timeline[:limit]
