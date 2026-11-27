"""get_knowledge_frontier: what the request is matched to, which prerequisites are walked,
and the order of the teaching plan.

Regression for the 27 Nov 2026 finding: the query "Explain the paper 'Attention Is All You
Need'" seeded every concept whose name contained a 3+ letter word of the query ("all" ->
"Tensor Parallelism", "need" -> "Needle in a Haystack"), and the 1-2 hop walk ignored link
direction, so agents got nearby concepts instead of prerequisites.
"""

from __future__ import annotations

import pytest

from backend.agent_bridge.knowledge import KnowledgeService, _teaching_plan

USER = "33333333-3333-3333-3333-333333333333"

NAMES = {
    "c-softmax": "Softmax",
    "c-sdpa": "Scaled Dot-Product Attention",
    "c-mha": "Multi-Head Attention",
    "c-transformer": "Transformer",
    "c-beam": "Beam Search",
    "c-tp": "Tensor Parallelism",
    "c-needle": "Needle in a Haystack",
}
# (a, type, b): a PREREQUISITE_OF b means a is needed for b.
EDGES = [
    ("c-softmax", "PREREQUISITE_OF", "c-sdpa"),
    ("c-sdpa", "PREREQUISITE_OF", "c-mha"),
    ("c-mha", "PREREQUISITE_OF", "c-transformer"),   # downstream of MHA: not a prerequisite
    ("c-beam", "RELATED_TO", "c-mha"),               # nearby, but not needed
]


class _Neo:
    def __init__(self):
        self.calls: list[str] = []

    async def execute_query(self, query: str, params=None):
        params = params or {}
        self.calls.append(query)
        assert params.get("user_id") == USER
        if "PREREQUISITE_OF*1.." in query:
            max_hops = int(query.split("PREREQUISITE_OF*1..")[1].split("]")[0])
            seeds = set(params["seed_ids"])
            best: dict[str, tuple[int, set]] = {}
            frontier = [(s, 0, s) for s in seeds]
            while frontier:
                node, hops, seed = frontier.pop()
                for a, rel, b in EDGES:
                    if rel == "PREREQUISITE_OF" and b == node and hops + 1 <= max_hops and a not in seeds:
                        h, served = best.get(a, (99, set()))
                        best[a] = (min(h, hops + 1), served | {NAMES[seed]})
                        frontier.append((a, hops + 1, seed))
            rows = [{"id": cid, "name": NAMES[cid], "domain": "ML", "definition": "",
                     "hops": h, "needed_for": sorted(served)} for cid, (h, served) in best.items()]
            return sorted(rows, key=lambda r: r["hops"])
        if "RETURN c.id AS id" in query:
            return [{"id": cid, "name": n, "domain": "ML", "definition": ""} for cid, n in NAMES.items()]
        return []


class _PG:
    async def execute_query(self, query: str, params=None):
        return []

    async def execute_update(self, query: str, params=None):
        return []


def _service(similar=None) -> KnowledgeService:
    svc = KnowledgeService(_PG(), _Neo(), similar=similar)

    async def profile(user_id, limit=12):
        return {"total_concepts": len(NAMES), "reviewed_concepts": 0, "domains": []}

    svc.get_knowledge_profile = profile  # the stable prefix is covered elsewhere
    return svc


def _all_names(data: dict) -> set[str]:
    return {e["name"] for k in ("anchors", "frontier", "gaps", "seen_untested") for e in data[k]}


@pytest.mark.asyncio
async def test_words_inside_concept_names_do_not_seed_the_request():
    data = await _service().get_knowledge_frontier(USER, "Explain the paper 'Attention Is All You Need'")
    names = _all_names(data)
    assert "Tensor Parallelism" not in names      # "all" is inside "Parallelism"
    assert "Needle in a Haystack" not in names    # "need" is inside "Needle"


@pytest.mark.asyncio
async def test_a_whole_concept_name_in_the_query_still_seeds_it():
    data = await _service().get_knowledge_frontier(USER, "How does softmax turn scores into weights?")
    assert any(e["name"] == "Softmax" and e["matched_by"] == "in_query" for e in data["gaps"] + data["seen_untested"])


@pytest.mark.asyncio
async def test_walks_prerequisites_backwards_not_neighbours():
    data = await _service().get_knowledge_frontier(
        USER, "Explain multi-head attention", concept_names=["Multi-Head Attention"], max_hops=2)
    names = _all_names(data)
    assert {"Scaled Dot-Product Attention", "Softmax"} <= names
    assert "Transformer" not in names   # builds on MHA; not needed to understand it
    assert "Beam Search" not in names   # merely related
    by_name = {e["name"]: e for k in ("frontier", "gaps", "seen_untested") for e in data[k]}
    assert by_name["Scaled Dot-Product Attention"]["role"] == "prerequisite"
    assert by_name["Scaled Dot-Product Attention"]["hops"] == 1
    assert by_name["Softmax"]["hops"] == 2
    assert by_name["Softmax"]["needed_for"] == ["Multi-Head Attention"]


@pytest.mark.asyncio
async def test_teaching_plan_teaches_foundations_before_what_was_asked():
    data = await _service().get_knowledge_frontier(
        USER, "Explain multi-head attention", concept_names=["Multi-Head Attention"], max_hops=2)
    order = [s["concept"] for s in data["teaching_plan"]["steps"]]
    assert order.index("Scaled Dot-Product Attention") < order.index("Multi-Head Attention")
    # Softmax is two steps away and only studied, never tested: weak evidence, so no step.
    assert "Softmax" not in order


@pytest.mark.asyncio
async def test_named_concepts_match_by_meaning_and_new_ones_become_gaps():
    async def similar(user_id, text, limit=5, min_score=0.7):
        return [{"id": "c-mha", "name": "Multi-Head Attention", "score": 0.93}] if "heads" in text else []

    data = await _service(similar).get_knowledge_frontier(
        USER, "Explain this paper", concept_names=["parallel attention heads", "Flow Matching Loss"])
    by_name = {e["name"]: e for k in ("anchors", "frontier", "gaps", "seen_untested") for e in data[k]}
    assert by_name["Multi-Head Attention"]["matched_by"] == "named_by_meaning"
    assert data["matched_by_meaning"] == [{"requested": "parallel attention heads", "matched": "Multi-Head Attention", "score": 0.93}]
    # A concept the paper introduces, which the user has never met, is a gap to teach.
    assert by_name["Flow Matching Loss"]["status"] == "unexposed"
    plan = {s["concept"]: s for s in data["teaching_plan"]["steps"]}
    assert plan["Flow Matching Loss"]["action"] == "teach"


@pytest.mark.asyncio
async def test_meaning_search_failure_falls_back_to_spelling():
    async def broken(user_id, text, limit=5, **kw):
        raise RuntimeError("embedding API down")

    data = await _service(broken).get_knowledge_frontier(USER, "Explain softmax", concept_names=["Softmax"])
    assert "Softmax" in _all_names(data)


def test_plan_assumes_strong_concepts_and_respects_the_budget():
    needs = [{"name": f"C{i}", "concept_name": f"C{i}", "status": "shaky", "mastery": 0.5, "role": "prerequisite",
              "hops": 1, "needed_for": ["X"], "priority": 0.5} for i in range(20)]
    anchors = [{"name": "Residual Connection", "concept_name": "Residual Connection"}]
    plan = _teaching_plan(needs, anchors, max_items=5)
    assert len(plan["steps"]) == 5
    assert plan["steps"][0]["action"] == "refresh" and "needed for X" in plan["steps"][0]["reason"]
    assert plan["assume"] == ["Residual Connection"]


@pytest.mark.asyncio
async def test_named_concepts_need_a_high_bar_to_match_by_meaning():
    seen_bars = []

    async def similar(user_id, text, limit=5, min_score=0.7):
        seen_bars.append((text, min_score))
        return []

    await _service(similar).get_knowledge_frontier(USER, "Explain this", concept_names=["Layer Normalization"])
    assert ("Layer Normalization", 0.87) in seen_bars


def test_plan_skips_distant_prerequisites_with_only_weak_evidence():
    def e(name, status, hops, role="prerequisite", priority=0.5):
        return {"name": name, "concept_name": name, "status": status, "mastery": 0.35, "role": role,
                "hops": hops, "needed_for": ["Self-Attention"], "priority": priority}

    plan = _teaching_plan([e("Machine Learning", "seen", 2), e("Softmax", "seen", 1),
                           e("Tensor", "shaky", 2), e("Self-Attention", "seen", 0, role="requested")], [], 12)
    names = [s["concept"] for s in plan["steps"]]
    assert "Machine Learning" not in names          # two steps away and never tested
    assert names == ["Tensor", "Softmax", "Self-Attention"]   # foundations first, then what was asked
