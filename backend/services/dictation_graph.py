"""Live dictation-to-graph streaming service.

Parses spoken concept lists (e.g. ``"KV cache, attention, speculative decoding, Q/K/V vectors"``),
matches or creates Concept nodes, emits existing Neo4j edges first, and streams inferred typed
edges (``PREREQUISITE_OF``, ``SUBTOPIC_OF``, ``BUILDS_ON``, ``APPLIES_TO``) via SSE.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, AsyncIterator, Optional

import structlog

from backend.services import knowledge_map as km
from backend.services.graph_hierarchy import normalize_edge_type, normalize_subject

logger = structlog.get_logger()

MAX_DICTATED_CONCEPTS = 30
VALID_RAW_EDGE_TYPES = {"PREREQUISITE_OF", "SUBTOPIC_OF", "PART_OF", "BUILDS_ON", "APPLIES_TO"}

_FILLER_PREFIX_RE = re.compile(
    r"^(?:add concepts?|wire up|connect|concepts?|learn|review|um+|uh+|so|okay|alright)\s*[:,-]*\s+",
    re.I,
)
_SPLIT_RE = re.compile(r"[,;\n]+|\band\b|\bthen\b", re.I)


def parse_dictated_concepts(transcript: str) -> list[str]:
    """Deterministically extract clean, deduplicated concept names from a spoken transcript."""
    cleaned = _FILLER_PREFIX_RE.sub("", (transcript or "").strip())
    out: list[str] = []
    seen: set[str] = set()
    for part in _SPLIT_RE.split(cleaned):
        term = re.sub(r"\s+", " ", part).strip(" .:-!?\"'")
        term = _FILLER_PREFIX_RE.sub("", term).strip(" .:-!?\"'")
        if len(term) < 2:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
        if len(out) >= MAX_DICTATED_CONCEPTS:
            break
    return out


def infer_typed_edges_heuristic(
    concepts: list[dict[str, Any]],
    existing_pairs: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Fast deterministic fallback edge inference when LLM inference is unavailable."""
    edges: list[dict[str, Any]] = []
    added_pairs: set[tuple[str, str]] = set()

    def _emit(src: dict[str, Any], dst: dict[str, Any], raw_type: str, rationale: str) -> None:
        s_id, t_id = src["id"], dst["id"]
        if s_id == t_id or (s_id, t_id) in existing_pairs or (t_id, s_id) in existing_pairs:
            return
        if (s_id, t_id) in added_pairs or (t_id, s_id) in added_pairs:
            return
        added_pairs.add((s_id, t_id))
        norm_type, direction = normalize_edge_type(raw_type)
        edges.append({
            "source": s_id,
            "target": t_id,
            "type": norm_type,
            "raw_type": raw_type,
            "direction": direction,
            "strength": 0.72,
            "rationale": rationale,
        })

    # 1. Compound name -> broader base concept => SUBTOPIC_OF
    for i, a in enumerate(concepts):
        a_low = a["name"].lower()
        for j, b in enumerate(concepts):
            if i == j:
                continue
            b_low = b["name"].lower()
            if len(b_low) >= 4 and len(a_low) > len(b_low) and re.search(rf"\b{re.escape(b_low)}\b", a_low):
                _emit(a, b, "SUBTOPIC_OF", f"{a['name']} specializes {b['name']}")

    # 2. Adjacent terms in sequence that aren't already wired => BUILDS_ON
    for i in range(len(concepts) - 1):
        _emit(
            concepts[i],
            concepts[i + 1],
            "BUILDS_ON",
            f"Mentioned alongside {concepts[i]['name']} -> {concepts[i + 1]['name']}",
        )
    return edges


async def infer_typed_edges_llm(
    concepts: list[dict[str, Any]],
    existing_pairs: set[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Infer typed directed edges via Gemini Flash-Lite, falling back to heuristics if unset/invalid."""
    api_key = (os.getenv("GOOGLE_API_KEY") or "").strip()
    if len(concepts) < 2 or not api_key or api_key.startswith("test") or api_key == "dummy":
        return infer_typed_edges_heuristic(concepts, existing_pairs)

    try:
        from backend.config.llm import get_fast_model

        names = [c["name"] for c in concepts]
        by_name = {c["name"].lower(): c for c in concepts}
        llm = get_fast_model(temperature=0.1, json_mode=True)
        prompt = (
            "Given these concepts spoken by a learner, return ONLY a JSON array of directed edges "
            'with keys "source", "target", "raw_type" (one of PREREQUISITE_OF, SUBTOPIC_OF, BUILDS_ON, APPLIES_TO), '
            'and "rationale" (<= 10 words).\n'
            f"Concepts: {json.dumps(names)}"
        )
        resp = await llm.ainvoke(prompt)
        raw_text = (getattr(resp, "text", None) or getattr(resp, "content", "") or "").strip()
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text, flags=re.S)
        parsed = json.loads(raw_text)
        if not isinstance(parsed, list):
            return infer_typed_edges_heuristic(concepts, existing_pairs)

        out: list[dict[str, Any]] = []
        seen_pairs = set(existing_pairs)
        for item in parsed:
            if not isinstance(item, dict):
                continue
            src = by_name.get(str(item.get("source") or "").strip().lower())
            dst = by_name.get(str(item.get("target") or "").strip().lower())
            raw_type = str(item.get("raw_type") or "BUILDS_ON").strip().upper()
            if not src or not dst or src["id"] == dst["id"] or raw_type not in VALID_RAW_EDGE_TYPES:
                continue
            pair = (src["id"], dst["id"])
            if pair in seen_pairs or (dst["id"], src["id"]) in seen_pairs:
                continue
            seen_pairs.add(pair)
            norm_type, direction = normalize_edge_type(raw_type)
            out.append({
                "source": src["id"],
                "target": dst["id"],
                "type": norm_type,
                "raw_type": raw_type,
                "direction": direction,
                "strength": 0.8,
                "rationale": str(item.get("rationale") or "")[:120],
            })
        return out or infer_typed_edges_heuristic(concepts, existing_pairs)
    except Exception as exc:
        logger.info("dictation_graph: falling back to heuristic edges", error=str(exc))
        return infer_typed_edges_heuristic(concepts, existing_pairs)


async def stream_dictation_to_graph(
    user_id: str,
    transcript: str,
    *,
    domain: Optional[str] = None,
    commit: bool = True,
    use_llm: bool = True,
    neo4j: Any,
    pg: Any,
) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE event dicts: ``concept`` -> existing ``edge`` -> inferred ``edge`` -> ``done``."""
    names = parse_dictated_concepts(transcript)
    subject = normalize_subject(domain) if domain else "General"
    existing_concepts = await km._user_concepts(neo4j, user_id)

    resolved: list[dict[str, Any]] = []
    nodes_created = 0
    nodes_matched = 0

    for name in names:
        hit = km.match_concept(name, existing_concepts)
        if hit:
            nodes_matched += 1
            node = {
                "id": hit["id"],
                "name": hit["name"],
                "domain": normalize_subject(hit.get("domain") or subject),
                "is_new": False,
                "color_key": normalize_subject(hit.get("domain") or subject),
            }
        else:
            nodes_created += 1
            cid = str(uuid.uuid4())
            if commit and neo4j is not None:
                await neo4j.execute_query(
                    """
                    CREATE (c:Concept {
                        id: $id,
                        user_id: $user_id,
                        name: $name,
                        name_normalized: $norm,
                        domain: $domain,
                        complexity_score: 5,
                        created_at: datetime()
                    })
                    """,
                    {"id": cid, "user_id": user_id, "name": name, "norm": km.skill_key(name), "domain": subject},
                )
            node = {
                "id": cid,
                "name": name,
                "domain": subject,
                "is_new": True,
                "color_key": subject,
            }
        resolved.append(node)
        yield {"event": "concept", "data": node}

    resolved_ids = [n["id"] for n in resolved]
    existing_pairs: set[tuple[str, str]] = set()
    existing_edge_count = 0
    if len(resolved_ids) >= 2 and neo4j is not None:
        rows = await neo4j.execute_query(
            """
            MATCH (c1:Concept {user_id: $user_id})-[r]->(c2:Concept {user_id: $user_id})
            WHERE c1.id IN $ids AND c2.id IN $ids
            RETURN c1.id AS source, c2.id AS target, type(r) AS raw_type,
                   coalesce(r.strength, 1.0) AS strength
            """,
            {"user_id": user_id, "ids": resolved_ids},
        )
        for row in rows or []:
            src, dst = str(row["source"]), str(row["target"])
            existing_pairs.add((src, dst))
            raw_type = row.get("raw_type") or "RELATED_TO"
            norm_type, direction = normalize_edge_type(raw_type)
            existing_edge_count += 1
            yield {
                "event": "edge",
                "data": {
                    "source": src,
                    "target": dst,
                    "type": norm_type,
                    "raw_type": raw_type,
                    "direction": direction,
                    "origin": "existing",
                    "strength": float(row.get("strength") or 1.0),
                },
            }

    inferred = (
        await infer_typed_edges_llm(resolved, existing_pairs)
        if use_llm
        else infer_typed_edges_heuristic(resolved, existing_pairs)
    )
    inferred_edge_count = 0
    for edge in inferred:
        raw_type = edge["raw_type"]
        if commit and neo4j is not None and raw_type in VALID_RAW_EDGE_TYPES:
            await neo4j.execute_query(
                f"""
                MATCH (c1:Concept {{id: $src, user_id: $user_id}}),
                      (c2:Concept {{id: $dst, user_id: $user_id}})
                MERGE (c1)-[r:{raw_type}]->(c2)
                ON CREATE SET r.strength = $strength, r.source = 'dictation', r.created_at = datetime()
                """,
                {"src": edge["source"], "dst": edge["target"], "user_id": user_id, "strength": edge["strength"]},
            )
        inferred_edge_count += 1
        yield {
            "event": "edge",
            "data": {**edge, "origin": "inferred"},
        }

    yield {
        "event": "done",
        "data": {
            "nodes_created": nodes_created,
            "nodes_matched": nodes_matched,
            "existing_edges": existing_edge_count,
            "inferred_edges": inferred_edge_count,
        },
    }
