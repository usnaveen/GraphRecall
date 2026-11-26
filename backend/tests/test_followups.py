"""Graph-grounded follow-up suggestions: ranking is pure, so it's tested without databases."""
import asyncio

from backend.services.followups import pick, suggest_followups, suggestion_click_meta


def _row(seed_id="s1", seed="KV Cache", prereqs=(), subs=(), nexts=()):
    def mk(items):
        return [{"id": i, "name": n} for i, n in items]
    return {"seed_id": seed_id, "seed_name": seed, "prereqs": mk(prereqs), "subs": mk(subs), "nexts": mk(nexts)}


def test_one_per_kind_with_shaky_prerequisite_first():
    rows = [_row(
        prereqs=[("p1", "Attention Mechanism"), ("p2", "Matrix Multiplication")],
        subs=[("c1", "Paged Attention")],
        nexts=[("n1", "Speculative Decoding")],
    )]
    status = {"p1": "strong", "p2": "shaky", "c1": "unexposed", "n1": "seen"}
    out = pick(rows, status, "what is a kv cache?")
    assert [s["kind"] for s in out] == ["prerequisite", "subtopic", "next"]
    assert out[0]["concept_name"] == "Matrix Multiplication"  # shaky beats strong
    assert out[0]["text"] == "What role does Matrix Multiplication play in KV Cache?"
    assert out[0]["reason"] == "A prerequisite you're shaky on"


def test_strong_prerequisites_and_subtopics_are_not_suggested():
    rows = [_row(prereqs=[("p1", "Attention Mechanism")], subs=[("c1", "Paged Attention")])]
    out = pick(rows, {"p1": "strong", "c1": "strong"}, "kv cache")
    assert out == []


def test_skips_concepts_named_in_the_question_and_the_seeds_themselves():
    rows = [
        _row(seed_id="s1", seed="KV Cache", prereqs=[("s2", "Attention Mechanism"), ("p9", "Softmax")]),
        _row(seed_id="s2", seed="Attention Mechanism", subs=[("c1", "Multi-Head Attention")]),
    ]
    out = pick(rows, {}, "How does softmax work?")
    names = [s["concept_name"] for s in out]
    assert "Softmax" not in names            # already asked about
    assert "Attention Mechanism" not in names  # a seed, not a suggestion
    assert names == ["Multi-Head Attention"]


def test_earlier_seed_wins_ties_and_a_concept_is_suggested_once():
    rows = [
        _row(seed_id="s1", seed="A", nexts=[("x", "Shared")]),
        _row(seed_id="s2", seed="B", subs=[("x", "Shared"), ("z", "Third")], nexts=[("y", "Other")]),
    ]
    out = pick(rows, {}, "")
    # "Shared" goes to the first seed's slot; the subtopic slot falls to the next unused concept.
    assert [(s["kind"], s["concept_name"]) for s in out] == [("next", "Shared"), ("subtopic", "Third")]


def test_no_seeds_or_broken_backends_give_no_suggestions():
    class Boom:
        async def execute_query(self, *a, **k):
            raise RuntimeError("neo4j down")

    assert asyncio.run(suggest_followups("u", "q", [], neo4j=Boom(), pg=object())) == []
    assert asyncio.run(suggest_followups("u", "q", [{"id": "s1", "name": "X"}], neo4j=Boom(), pg=object())) == []


def test_click_meta_keeps_only_kind_and_concept():
    assert suggestion_click_meta({"kind": "subtopic", "concept_id": "c1", "text": "secret?"}) == {
        "kind": "subtopic", "concept_id": "c1"}
    assert suggestion_click_meta({"kind": "nope"}) is None
    assert suggestion_click_meta(None) is None


def test_seeds_start_with_the_concept_the_question_names(monkeypatch):
    """Asked about MQA, suggestions come from MQA's neighbours, not whatever retrieval listed first."""
    from backend.services import followups, knowledge_map

    seen = {}

    class FakeNeo:
        async def execute_query(self, query, params):
            if "CONTAINS toLower(c.name)" in query:
                assert params["q"] == "explain multi-query attention"
                return [{"id": "mqa", "name": "Multi-Query Attention"}]
            seen["ids"] = params["ids"]
            return [_row(seed_id="mqa", seed="Multi-Query Attention", subs=[("c1", "Shared KV Heads")])]

    async def fake_assess(user_id, names, **kw):
        return []

    monkeypatch.setattr(knowledge_map, "assess", fake_assess)
    related = [{"id": "kv", "name": "KV Cache"}, {"id": "mqa", "name": "Multi-Query Attention"}]
    out = asyncio.run(followups.suggest_followups("u", "Explain Multi-Query Attention", related,
                                                  neo4j=FakeNeo(), pg=object()))
    assert seen["ids"] == ["mqa", "kv"]
    assert out[0]["seed_name"] == "Multi-Query Attention"
