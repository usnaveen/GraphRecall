"""Crop the captioned figures out of one source PDF and store them for its note.

Run from the repo root with PYTHONPATH set and DATABASE_URL pointing at the database:

  python scripts/extract_figures.py --user-id <uuid> --note-id <uuid> --pdf "path/to/paper.pdf"
  python scripts/extract_figures.py ... --dry-run          # list what would be stored
  python scripts/extract_figures.py ... --out-dir /tmp/x   # also write the crops for a look

No model calls: figures are found by their captions ("Figure 3.1: ...") and cropped from the page,
so the run costs nothing but time. Re-running replaces a figure with the same page and label.
An iCloud Drive placeholder is downloaded first (`brctl download`), as library_prepare.py does.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from pathlib import Path

from backend.services.figure_extractor import extract_figures


def _is_placeholder(p: Path) -> bool:
    out = subprocess.run(["/bin/ls", "-lO", str(p)], capture_output=True, text=True).stdout
    return "dataless" in out


def _ensure_local(p: Path, wait_s: int = 600) -> bool:
    if sys.platform != "darwin" or not _is_placeholder(p):
        return True
    subprocess.run(["brctl", "download", str(p)], capture_output=True)
    end = time.time() + wait_s
    while time.time() < end:
        if not _is_placeholder(p):
            return True
        time.sleep(3)
    return False


async def _store(user_id: str, note_id: str, figures, replace: bool) -> int:
    from backend.db.postgres_client import get_postgres_client

    pg = await get_postgres_client()
    owned = await pg.execute_query(
        "SELECT 1 FROM notes WHERE id = CAST(:n AS uuid) AND user_id = CAST(:u AS uuid)",
        {"n": note_id, "u": user_id},
    )
    if not owned:
        raise SystemExit(f"note {note_id} does not belong to user {user_id}")
    if replace:
        await pg.execute_update(
            "DELETE FROM source_figures WHERE note_id = CAST(:n AS uuid) AND user_id = CAST(:u AS uuid)",
            {"n": note_id, "u": user_id},
        )
    for f in figures:
        await pg.execute_update(
            """
            INSERT INTO source_figures (user_id, note_id, page, label, caption, mime, image, width, height)
            VALUES (CAST(:u AS uuid), CAST(:n AS uuid), :page, :label, :caption, :mime, :image, :w, :h)
            ON CONFLICT (note_id, page, label) DO UPDATE SET
                caption = EXCLUDED.caption, mime = EXCLUDED.mime, image = EXCLUDED.image,
                width = EXCLUDED.width, height = EXCLUDED.height
            """,
            {
                "u": user_id, "n": note_id, "page": f.page, "label": f.label, "caption": f.caption,
                "mime": f.mime, "image": f.image, "w": f.width, "h": f.height,
            },
        )
    return len(figures)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user-id", required=True)
    ap.add_argument("--note-id", required=True)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--max-pages", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true", help="extract and list, store nothing")
    ap.add_argument("--replace", action="store_true", help="drop the note's stored figures first")
    ap.add_argument("--out-dir", default=None, help="also write each crop here")
    args = ap.parse_args()

    pdf = Path(args.pdf).expanduser()
    if not pdf.exists():
        raise SystemExit(f"no such file: {pdf}")
    if not _ensure_local(pdf):
        raise SystemExit(f"iCloud did not download {pdf.name} in time")

    started = time.time()
    figures = extract_figures(str(pdf), max_pages=args.max_pages)
    total_kb = sum(len(f.image) for f in figures) // 1024
    print(f"{pdf.name}: {len(figures)} figures, {total_kb} KB, {time.time() - started:.1f}s")
    for f in figures:
        print(f"  p{f.page:<4} {f.label:<12} {f.width}x{f.height} {len(f.image) // 1024:>4} KB  {f.caption[:70]}")
        if args.out_dir:
            out = Path(args.out_dir)
            out.mkdir(parents=True, exist_ok=True)
            ext = "png" if f.mime == "image/png" else "jpg"
            (out / f"p{f.page}-{f.label.replace(' ', '_')}.{ext}").write_bytes(f.image)
    if args.dry_run:
        return
    stored = asyncio.run(_store(args.user_id, args.note_id, figures, args.replace))
    print(f"stored {stored} figures for note {args.note_id}")


if __name__ == "__main__":
    main()
