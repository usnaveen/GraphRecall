"""Figures from the user's own sources on concept cards: cropped by caption, matched only when the
caption is about the concept, served to their owner only."""

from __future__ import annotations

import asyncio

import pymupdf
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth.middleware import get_current_user
from backend.models.feed_schemas import FeedItem, FeedItemType
from backend.routers import figures as figures_router
from backend.services import account_deletion
from backend.services.concept_figures import attach_concept_figures, best_figure
from backend.services.figure_extractor import extract_page_figures, parse_caption

OWNER = "00000000-0000-0000-0000-0000000000aa"
OTHER = "00000000-0000-0000-0000-0000000000bb"
FIG_ID = "11111111-2222-3333-4444-555555555555"


# --- extraction ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Figure 1: The Transformer - model architecture.", ("Figure 1", "The Transformer - model architecture.")),
        ("Figure 3.1. A two-layer Elman RNN.", ("Figure 3.1", "A two-layer Elman RNN.")),
        ("Fig. 2 — Attention heads", ("Figure 2", "Attention heads")),
        ("Figure 4.2 Three-head self-attention", ("Figure 4.2", "Three-head self-attention")),
        ("Figure 3 shows that accuracy improves with size.", None),  # a reference in body text
        ("The figure below shows the model.", None),
    ],
)
def test_parse_caption(text, expected) -> None:
    assert parse_caption(text) == expected


def _page_with_figures(*, overlap_caption: bool = False) -> pymupdf.Document:
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 80), "Body text about sorting that sits above the figure.", fontsize=10)
    # Figure 1: two boxes and an arrow, with a small panel title above the drawing.
    page.insert_text((150, 128), "Pointers", fontsize=9)
    page.draw_rect(pymupdf.Rect(100, 140, 250, 220), color=(0, 0, 0), width=1)
    page.draw_rect(pymupdf.Rect(320, 140, 470, 220), color=(0, 0, 0), width=1)
    page.draw_line((250, 180), (320, 180), color=(0, 0, 0), width=1)
    bottom = 258 if overlap_caption else 230
    page.draw_line((100, bottom), (470, bottom), color=(0.5, 0.5, 0.5), width=0.5)
    page.insert_text((100, 262), "Figure 1: Two pointers on a sorted array.", fontsize=9)
    # Body text that mentions a figure without being a caption.
    page.insert_text((72, 320), "Figure 1 shows how the pointers move towards each other.", fontsize=10)
    # Figure 2 further down, separate from the first.
    page.draw_circle((285, 450), 50, color=(0, 0, 0), width=1)
    page.insert_text((200, 530), "Figure 2: A heap drawn as a tree.", fontsize=9)
    return doc


def test_extracts_each_captioned_figure_and_keeps_them_apart() -> None:
    doc = _page_with_figures()
    figures = extract_page_figures(doc[0])
    assert [(f.label, f.caption) for f in figures] == [
        ("Figure 1", "Two pointers on a sorted array."),
        ("Figure 2", "A heap drawn as a tree."),
    ]
    first = figures[0]
    assert first.page == 1 and first.mime == "image/png" and first.image.startswith(b"\x89PNG")
    # Wider than tall like the drawing (two boxes side by side), not a full-page grab.
    assert first.width > first.height


def test_drawing_that_grazes_its_caption_still_counts() -> None:
    figures = extract_page_figures(_page_with_figures(overlap_caption=True)[0])
    assert "Figure 1" in [f.label for f in figures]


def test_page_without_captions_gives_nothing() -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(100, 100, 300, 300), color=(0, 0, 0))
    assert extract_page_figures(page) == []


# --- matching ------------------------------------------------------------------------------------


def _fig(i, caption, page=1, title="Source"):
    return {"id": f"fig-{i}", "caption": caption, "page": page, "label": f"Figure {i}", "source_title": title,
            "width": 800, "height": 600}


ATTENTION_FIGS = [
    _fig(1, "The Transformer - model architecture."),
    _fig(2, "(left) Scaled Dot-Product Attention. (right) Multi-Head Attention consists of several attention "
            "layers running in parallel."),
]
WORD2VEC = _fig(3, "New model architectures. The CBOW architecture predicts the current word based on the context, "
                   "and the Skip-gram predicts surrounding words given the current word.")
GLOVE_TIMING = _fig(4, "Overall accuracy on the word analogy task as a function of training time, which is governed "
                       "by the number of iterations for GloVe and by the number of negative samples for CBOW (a) and "
                       "skip-gram (b). In all cases we use a symmetric context window of size 10.")
SEQ2SEQ_PCA = _fig(5, "The figure shows a 2-dimensional PCA projection of the LSTM hidden states. The phrases are "
                      "clustered by meaning, which would be difficult to capture with a bag-of-words model.")
GLOVE_ACCURACY = _fig(6, "Accuracy on the analogy task as function of vector size and window size/type.")


def test_short_title_names_a_one_word_concept() -> None:
    assert best_figure("Transformer", ATTENTION_FIGS)["id"] == "fig-1"


def test_panel_description_counts_for_a_multi_word_name() -> None:
    assert best_figure("Multi-Head Attention", ATTENTION_FIGS)["id"] == "fig-2"
    assert best_figure("Scaled Dot-Product Attention", ATTENTION_FIGS)["id"] == "fig-2"


def test_a_figure_about_the_concept_beats_one_that_mentions_it() -> None:
    """GloVe's timing plot names skip-gram as a run condition; word2vec's figure is its architecture."""
    assert best_figure("Skip-gram", [GLOVE_TIMING, WORD2VEC])["id"] == "fig-3"


def test_later_sentences_add_conditions_not_subjects() -> None:
    assert best_figure("Bag of Words", [SEQ2SEQ_PCA]) is None
    assert best_figure("Symmetric Context Window", [GLOVE_TIMING]) is None
    assert best_figure("Hidden State", [SEQ2SEQ_PCA])["id"] == "fig-5"


def test_one_word_in_a_long_title_is_not_enough() -> None:
    assert best_figure("Accuracy", [GLOVE_ACCURACY]) is None


def test_acronyms_match_case_sensitively_and_whole_words() -> None:
    figs = [_fig(7, "A GRU cell."), _fig(8, "The ingrus of agru.")]
    assert best_figure("GRU", figs)["id"] == "fig-7"
    assert best_figure("GRU", [figs[1]]) is None


def test_no_match_gives_no_figure() -> None:
    assert best_figure("Two Pointers", ATTENTION_FIGS) is None
    assert best_figure("", ATTENTION_FIGS) is None


# --- feed attach point ---------------------------------------------------------------------------


class _Pg:
    def __init__(self, rows=None, fail: bool = False):
        self.rows = rows or []
        self.fail = fail
        self.calls = 0

    async def execute_query(self, sql, params=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError('relation "source_figures" does not exist')
        return self.rows


def _item(item_type, name, i=0, content=None):
    return FeedItem(id=f"i{i}", item_type=item_type, content=content or {}, concept_id=f"c{i}",
                    concept_name=name, domain="AI", priority_score=0.5)


def test_attach_sets_figure_on_concept_cards_only() -> None:
    rows = [{**f, "source_title": "Attention Is All You Need"} for f in ATTENTION_FIGS]
    items = [
        _item(FeedItemType.CONCEPT_SHOWCASE, "Transformer", 0, {"definition": "x"}),
        _item(FeedItemType.MCQ, "Multi-Head Attention", 1),
        _item(FeedItemType.CODE_CHALLENGE, "Transformer", 2),
        _item(FeedItemType.TERM_CARD, "Two Pointers", 3),
    ]
    pg = _Pg(rows)
    assert asyncio.run(attach_concept_figures(items, OWNER, pg)) == 2
    assert pg.calls == 1
    showcase = items[0].content
    assert showcase["definition"] == "x"
    assert showcase["figure"] == {
        "id": "fig-1", "url": "/api/figures/fig-1", "label": "Figure 1",
        "caption": "The Transformer - model architecture.", "source_title": "Attention Is All You Need",
        "page": 1, "width": 800, "height": 600,
    }
    assert items[1].content["figure"]["id"] == "fig-2"
    assert "figure" not in items[2].content and "figure" not in items[3].content


def test_attach_never_breaks_the_feed() -> None:
    items = [_item(FeedItemType.CONCEPT_SHOWCASE, "Transformer")]
    assert asyncio.run(attach_concept_figures(items, OWNER, _Pg(fail=True))) == 0
    assert items[0].content == {}


# --- serving -------------------------------------------------------------------------------------


class _FigurePg:
    async def execute_query(self, sql, params=None):
        if params["id"] == FIG_ID and params["u"] == OWNER:
            return [{"image": b"\x89PNGfake", "mime": "image/png"}]
        return []


def _client(monkeypatch, user_id: str) -> TestClient:
    async def fake_pg():
        return _FigurePg()

    monkeypatch.setattr(figures_router, "get_postgres_client", fake_pg)
    app = FastAPI()
    app.include_router(figures_router.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": user_id}
    return TestClient(app)


def test_owner_gets_the_figure_privately_cached(monkeypatch) -> None:
    r = _client(monkeypatch, OWNER).get(f"/api/figures/{FIG_ID}")
    assert r.status_code == 200
    assert r.content == b"\x89PNGfake" and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"].startswith("private")


def test_other_users_cannot_fetch_it(monkeypatch) -> None:
    assert _client(monkeypatch, OTHER).get(f"/api/figures/{FIG_ID}").status_code == 404


def test_malformed_id_is_rejected(monkeypatch) -> None:
    assert _client(monkeypatch, OWNER).get("/api/figures/not-a-uuid").status_code == 422


def test_account_deletion_purges_figures_before_notes() -> None:
    tables = account_deletion.PURGE_TABLES
    assert tables.index("source_figures") < tables.index("notes")
