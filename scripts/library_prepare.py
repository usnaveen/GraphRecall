#!/usr/bin/env python3
"""Prepare the user's essential books for ingestion: download from iCloud, convert, size, cost.

Phase A of book ingestion. It needs no LLM or API key; the ingest itself (scripts/ingest_book.py /
ingest_papers.py) runs afterwards.

Per book listed in data/library/essential.txt (paths relative to iCloud Drive/Library):
  1. ensure it's downloaded from iCloud (`brctl download`; the file is a placeholder until then);
  2. convert: PDF → markdown with PyMuPDF4LLM (fast, keeps headings and lists; formulas become
     text), EPUB → markdown via ebooklib + BeautifulSoup;
  3. measure: pages, characters, estimated tokens (chars / 4), and chunks using the same BookChunker
     settings the ingest uses, giving the embedding calls and extraction batches the ingest will make.

Writes data/library/md/<slug>.md and data/library/manifest.json, and prints a table and totals.
Pass prices to get a cost estimate (no prices are assumed):
    .venv/bin/python scripts/library_prepare.py --price-in 0.10 --price-out 0.40 --price-embed 0.15
(USD per million tokens: model input, model output, embeddings.)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
LIBRARY = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Library"
OUT = REPO / "data" / "library"
EXTRACT_BATCH_CHUNKS = 4          # chunks per concept-extraction call in ingest_book.py (approx.)
OUTPUT_TOKENS_PER_BATCH = 800     # rough JSON size of an extraction response


def slug(p: Path) -> str:
    return re.sub(r"[^a-z0-9]+", "-", p.stem.lower()).strip("-")[:80]


def is_placeholder(p: Path) -> bool:
    out = subprocess.run(["/bin/ls", "-lO", str(p)], capture_output=True, text=True).stdout
    return "dataless" in out


def ensure_local(p: Path, wait_s: int) -> bool:
    if not is_placeholder(p):
        return True
    subprocess.run(["brctl", "download", str(p)], capture_output=True)
    end = time.time() + wait_s
    while time.time() < end:
        if not is_placeholder(p):
            return True
        time.sleep(5)
    return False


def pdf_to_md(p: Path) -> tuple[str, int]:
    import pymupdf
    import pymupdf4llm

    with pymupdf.open(p) as doc:
        pages = doc.page_count
    return pymupdf4llm.to_markdown(str(p), show_progress=False), pages


def epub_to_md(p: Path) -> tuple[str, int]:
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    book = epub.read_epub(str(p))
    parts = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for h in soup.find_all(re.compile(r"^h[1-6]$")):
            h.string = "#" * int(h.name[1]) + " " + h.get_text(" ", strip=True)
        text = soup.get_text("\n", strip=True)
        if text:
            parts.append(text)
    md = "\n\n".join(parts)
    return md, max(1, len(md) // 2000)  # EPUBs have no pages: ~2,000 characters per page


def main() -> None:
    from backend.services.book_chunker import BookChunker

    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default=str(OUT / "essential.txt"))
    ap.add_argument("--wait", type=int, default=900, help="seconds to wait per book for iCloud")
    ap.add_argument("--price-in", type=float)
    ap.add_argument("--price-out", type=float)
    ap.add_argument("--price-embed", type=float)
    a = ap.parse_args()

    (OUT / "md").mkdir(parents=True, exist_ok=True)
    entries = [l.strip() for l in Path(a.list).read_text().splitlines() if l.strip() and not l.startswith("#")]
    chunker = BookChunker()
    manifest = json.loads((OUT / "manifest.json").read_text()) if (OUT / "manifest.json").exists() else {}
    for rel in entries:
        src = LIBRARY / rel
        key = slug(src)
        if key in manifest and manifest[key].get("status") == "converted" and (OUT / "md" / f"{key}.md").exists():
            continue
        rec = {"source": rel, "kind": "paper" if rel.startswith("Papers/") else "book"}
        if not src.exists():
            rec["status"] = "missing"
        elif not ensure_local(src, a.wait):
            rec["status"] = "not downloaded from iCloud yet"
        else:
            t0 = time.time()
            try:
                md, pages = (epub_to_md if src.suffix.lower() == ".epub" else pdf_to_md)(src)
                (OUT / "md" / f"{key}.md").write_text(md, encoding="utf-8")
                chunks = chunker.chunk_text(md)   # same chunker (and 1,400-char limit) as the ingest
                children = len(chunks)             # one embedding per chunk
                rec.update(status="converted", pages=pages, chars=len(md), tokens_est=len(md) // 4,
                           chunks=len(chunks), embed_calls=children,
                           extraction_calls=-(-len(chunks) // EXTRACT_BATCH_CHUNKS),
                           seconds=round(time.time() - t0, 1))
            except Exception as e:  # noqa: BLE001
                rec.update(status="conversion failed", error=f"{type(e).__name__}: {e}"[:200])
        manifest[key] = rec
        (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
        print(f"{rec['status']:28s} {rec.get('pages', ''):>5} pages {rec.get('tokens_est', 0):>9,} tok  {rel[:70]}", flush=True)

    done = [r for r in manifest.values() if r.get("status") == "converted"]
    tok = sum(r["tokens_est"] for r in done)
    calls = sum(r["extraction_calls"] for r in done)
    emb = sum(r["embed_calls"] for r in done)
    print(f"\n{len(done)}/{len(entries)} converted: {sum(r['pages'] for r in done):,} pages, ~{tok:,} tokens, "
          f"{sum(r['chunks'] for r in done):,} chunks, ~{emb:,} embeddings, ~{calls:,} extraction calls")
    if a.price_in is not None and a.price_out is not None and a.price_embed is not None:
        # extraction reads every token once (plus prompt overhead ~15%), embeddings read every token once
        cost = tok * 1.15 / 1e6 * a.price_in + calls * OUTPUT_TOKENS_PER_BATCH / 1e6 * a.price_out + tok / 1e6 * a.price_embed
        print(f"estimated one-off ingest cost ≈ ${cost:,.2f} (excludes flashcard/quiz generation and synthesis)")


if __name__ == "__main__":
    main()
