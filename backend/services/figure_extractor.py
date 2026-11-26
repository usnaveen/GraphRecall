"""Crop captioned figures out of a PDF.

A figure is only taken when the page has a real caption ("Figure 3.1: ..." or "Fig. 2. ..."): the
caption is what later ties a figure to a concept, and an uncaptioned graphic could be anything (a
logo, a page ornament, a table rule). The figure's area is the run of images and vector drawings
directly above the caption (or, failing that, directly below it), stopping at the previous
caption so two figures on one page stay apart. The area is rendered from the page, so vector
figures come out as well as embedded bitmaps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pymupdf

# "Figure 1: ...", "Figure 3.1. ...", "Fig. 2 — ...", or "Figure 4.2 Capitalised title". The last
# form needs a capital so a paragraph that opens with "Figure 3 shows ..." is not read as a caption.
_CAPTION_RE = re.compile(
    r"^\s*(?:\*\*)?(?P<word>Figure|Fig\.)\s*(?P<num>\d+(?:[.\-]\d+)*[a-z]?)"
    r"(?:\s*[:.|—–]\s*(?P<rest>.+)|\s+(?P<titled>[A-Z(].+))$",
    re.S,
)
_MIN_GRAPHIC_PT = 24  # ignore specks, bullets and rules
_MAX_GAP_PT = 72  # a figure starts at most an inch from its caption
_JOIN_GAP_PT = 36  # pieces of one figure sit at most half an inch apart
_MIN_FIGURE_W, _MIN_FIGURE_H = 80, 50
_TARGET_WIDTH_PX = 1100
_MAX_PNG_BYTES = 700_000
_MAX_CAPTION_CHARS = 400


@dataclass(frozen=True)
class ExtractedFigure:
    page: int  # 1-based
    label: str  # "Figure 3.1"
    caption: str
    image: bytes
    mime: str
    width: int
    height: int


def parse_caption(text: str) -> tuple[str, str] | None:
    """("Figure 3.1", "A two-layer Elman RNN.") for a caption block, else None."""
    flat = " ".join(text.split())
    m = _CAPTION_RE.match(flat)
    if not m:
        return None
    rest = (m.group("rest") or m.group("titled") or "").strip().strip("*_ ")
    if len(rest) < 3:
        return None
    return f"Figure {m.group('num')}", rest[:_MAX_CAPTION_CHARS]


def _graphic_rects(page: pymupdf.Page) -> list[pymupdf.Rect]:
    rects: list[pymupdf.Rect] = []
    for info in page.get_image_info():
        rects.append(pymupdf.Rect(info["bbox"]))
    try:
        rects.extend(pymupdf.Rect(r) for r in page.cluster_drawings())
    except Exception:  # noqa: BLE001 — older PyMuPDF or a malformed drawing list: bitmaps only
        pass
    page_area = page.rect.get_area()
    out = []
    for r in rects:
        r = r & page.rect
        if r.is_empty or r.width < _MIN_GRAPHIC_PT or r.height < _MIN_GRAPHIC_PT:
            continue
        if r.get_area() >= 0.92 * page_area:  # a full-page background, not a figure
            continue
        out.append(r)
    return out


def _overlaps_horizontally(a: pymupdf.Rect, b: pymupdf.Rect, slack: float = 40) -> bool:
    return a.x0 < b.x1 + slack and b.x0 < a.x1 + slack


def _region_above(cap: pymupdf.Rect, graphics: list[pymupdf.Rect], ceiling: float) -> pymupdf.Rect | None:
    # A drawing may reach into the caption's box (a stray rule, a cluster that grazes it); it
    # still counts if it starts above the caption and ends before the caption does.
    cands = [
        g for g in graphics
        if g.y0 < cap.y0 - 10 and g.y1 <= cap.y1 + 4 and g.y0 >= ceiling - 2 and _overlaps_horizontally(g, cap)
    ]
    if not cands:
        return None
    cands.sort(key=lambda g: -g.y1)
    if cap.y0 - cands[0].y1 > _MAX_GAP_PT:
        return None
    region = pymupdf.Rect(cands[0])
    for g in cands[1:]:
        if g.y1 >= region.y0 - _JOIN_GAP_PT:
            region |= g
    region.y1 = min(region.y1, cap.y0 - 1)
    return region


def _region_below(cap: pymupdf.Rect, graphics: list[pymupdf.Rect], floor: float) -> pymupdf.Rect | None:
    cands = [
        g for g in graphics
        if g.y1 > cap.y1 + 10 and g.y0 >= cap.y0 - 4 and g.y1 <= floor + 2 and _overlaps_horizontally(g, cap)
    ]
    if not cands:
        return None
    cands.sort(key=lambda g: g.y0)
    if cands[0].y0 - cap.y1 > _MAX_GAP_PT:
        return None
    region = pymupdf.Rect(cands[0])
    for g in cands[1:]:
        if g.y0 <= region.y1 + _JOIN_GAP_PT:
            region |= g
    region.y0 = max(region.y0, cap.y1 + 1)
    return region


def _text_lines(page: pymupdf.Page) -> list[tuple[pymupdf.Rect, str, float]]:
    lines = []
    for block in page.get_text("dict")["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            text = "".join(s["text"] for s in line["spans"]).strip()
            if text:
                lines.append((pymupdf.Rect(line["bbox"]), text, max(s["size"] for s in line["spans"])))
    return lines


def _settle_edges(
    clip: pymupdf.Rect,
    region: pymupdf.Rect,
    cap: pymupdf.Rect,
    lines: list[tuple[pymupdf.Rect, str, float]],
    caption_size: float,
) -> pymupdf.Rect:
    """Never cut a line of text in half: take in short labels that belong to the figure (titles
    over sub-panels, axis names) and push the edge past anything else (a heading, body text)."""
    clip = pymupdf.Rect(clip)
    for _ in range(2):  # a label taken in can bring the edge up against another line
        for rect, text, size in lines:
            if not rect.intersects(clip) or clip.contains(rect) or rect.intersects(cap):
                continue
            label_like = len(text) <= 60 and size <= caption_size + 0.5 and _overlaps_horizontally(rect, region, 12)
            if label_like and rect.y0 >= region.y0 - 30 and rect.y1 <= region.y1 + 30:
                clip |= rect + (-3, -3, 3, 3)
            elif rect.y1 <= region.y0 + 2:  # above the figure: drop the line
                clip.y0 = max(clip.y0, rect.y1 + 1)
            elif rect.y0 >= region.y1 - 2:  # below the figure
                clip.y1 = min(clip.y1, rect.y0 - 1)
    if cap.y0 >= region.y1:  # caption under the figure: stop above it
        clip.y1 = min(clip.y1, cap.y0 - 1)
    elif cap.y1 <= region.y0:
        clip.y0 = max(clip.y0, cap.y1 + 1)
    return clip


def _render(page: pymupdf.Page, clip: pymupdf.Rect) -> tuple[bytes, str, int, int]:
    zoom = max(1.5, min(4.0, _TARGET_WIDTH_PX / max(clip.width, 1)))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
    data = pix.tobytes("png")
    mime = "image/png"
    if len(data) > _MAX_PNG_BYTES:  # photographic figure: JPEG is far smaller
        data = pix.tobytes("jpeg", jpg_quality=82)
        mime = "image/jpeg"
    return data, mime, pix.width, pix.height


def extract_page_figures(page: pymupdf.Page) -> list[ExtractedFigure]:
    captions: list[tuple[pymupdf.Rect, str, str]] = []
    for block in page.get_text("blocks"):
        if block[6] != 0:  # image block
            continue
        parsed = parse_caption(block[4])
        if parsed:
            captions.append((pymupdf.Rect(block[:4]), *parsed))
    if not captions:
        return []

    graphics = _graphic_rects(page)
    if not graphics:
        return []
    lines = _text_lines(page)
    captions.sort(key=lambda c: c[0].y0)
    figures: list[ExtractedFigure] = []
    seen_labels: set[str] = set()
    for i, (cap, label, caption) in enumerate(captions):
        if label in seen_labels:
            continue
        ceiling = captions[i - 1][0].y1 if i > 0 else page.rect.y0
        floor = captions[i + 1][0].y0 if i + 1 < len(captions) else page.rect.y1
        region = _region_above(cap, graphics, ceiling) or _region_below(cap, graphics, floor)
        if region is None or region.width < _MIN_FIGURE_W or region.height < _MIN_FIGURE_H:
            continue
        cap_sizes = [size for rect, _, size in lines if rect.intersects(cap)]
        caption_size = min(cap_sizes) if cap_sizes else 10.0
        clip = _settle_edges((region + (-6, -6, 6, 6)) & page.rect, region, cap, lines, caption_size)
        if clip.is_empty or clip.width < _MIN_FIGURE_W or clip.height < _MIN_FIGURE_H:
            continue
        data, mime, w, h = _render(page, clip)
        seen_labels.add(label)
        figures.append(ExtractedFigure(page.number + 1, label, caption, data, mime, w, h))
    return figures


def extract_figures(pdf_path: str, *, max_pages: int | None = None) -> list[ExtractedFigure]:
    """Every captioned figure in the PDF, in page order. A label seen twice keeps its first crop."""
    out: list[ExtractedFigure] = []
    labels: set[str] = set()
    with pymupdf.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            if max_pages is not None and i >= max_pages:
                break
            for fig in extract_page_figures(page):
                if fig.label not in labels:
                    labels.add(fig.label)
                    out.append(fig)
    return out
