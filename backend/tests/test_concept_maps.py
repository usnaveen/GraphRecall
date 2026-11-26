"""Every concept card gets a picture of where the concept sits in the user's graph."""

from __future__ import annotations

import asyncio

from backend.models.feed_schemas import FeedItem, FeedItemType
from backend.services.concept_maps import attach_concept_maps, build_concept_map, neighbour_role


def test_roles_read_from_the_card_concept() -> None:
    assert neighbour_role("PREREQUISITE_OF", True) == "unlocks"
    assert neighbour_role("PREREQUISITE_OF", False) == "needs"
    assert neighbour_role("SUBTOPIC_OF", True) == "part_of"
    assert neighbour_role("SUBTOPIC_OF", False) == "includes"
    assert neighbour_role("RELATED_TO", True) == "related"
    assert neighbour_role(None, False) == "related"


def test_typed_links_first_capped_and_deduplicated() -> None:
    links = [{"name": f"R{i}", "rel": "RELATED_TO", "out": True} for i in range(5)]
    links += [
        {"name": "Linear Algebra", "rel": "PREREQUISITE_OF", "out": False},
        {"name": "Calculus", "rel": "PREREQUISITE_OF", "out": False},
        {"name": "Probability", "rel": "PREREQUISITE_OF", "out": False},   # third "needs": capped
        {"name": "Deep Learning", "rel": "SUBTOPIC_OF", "out": True},
        {"name": "deep learning", "rel": "RELATED_TO", "out": True},       # duplicate name
        {"name": "Backpropagation", "rel": "SUBTOPIC_OF", "out": False},
        {"name": "Neural Network", "rel": "RELATED_TO", "out": True},      # the centre itself
    ]
    m = build_concept_map("Neural Network", links)
    assert m["center"] == "Neural Network"
    roles = [(n["name"], n["role"]) for n in m["nodes"]]
    assert roles[0] == ("Deep Learning", "part_of")
    assert ("Linear Algebra", "needs") in roles and ("Calculus", "needs") in roles
    assert ("Probability", "needs") not in roles
    assert ("Backpropagation", "includes") in roles
    assert len(m["nodes"]) <= 7
    assert sum(1 for _, r in roles if r == "related") == 7 - 4


def test_no_links_no_map() -> None:
    assert build_concept_map("Lonely", []) is None


class _Neo:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail, self.calls = rows or [], fail, 0

    async def execute_query(self, query, params=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("neo4j down")
        return [r for r in self.rows if r["id"] in params["ids"]]


def _item(t, cid, name):
    return FeedItem(id=f"i-{cid}-{t.value}", item_type=t, content={}, concept_id=cid,
                    concept_name=name, domain="AI", priority_score=0.5)


def test_attach_sets_maps_on_concept_cards_with_one_query() -> None:
    neo = _Neo([{"id": "c1", "name": "Softmax",
                 "links": [{"name": "Logits", "rel": "PREREQUISITE_OF", "out": False}]}])
    items = [_item(FeedItemType.CONCEPT_SHOWCASE, "c1", "Softmax"), _item(FeedItemType.TERM_CARD, "c1", "Softmax"),
             _item(FeedItemType.CODE_CHALLENGE, "c1", "Softmax"), _item(FeedItemType.CONCEPT_SHOWCASE, "c2", "X")]
    assert asyncio.run(attach_concept_maps(items, "u", neo)) == 2
    assert neo.calls == 1
    assert items[0].content["concept_map"] == {"center": "Softmax", "nodes": [{"name": "Logits", "role": "needs"}]}
    assert "concept_map" not in items[2].content and "concept_map" not in items[3].content


def test_attach_never_breaks_the_feed() -> None:
    items = [_item(FeedItemType.CONCEPT_SHOWCASE, "c1", "Softmax")]
    assert asyncio.run(attach_concept_maps(items, "u", _Neo(fail=True))) == 0
    assert items[0].content == {}
