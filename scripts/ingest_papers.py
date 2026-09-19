#!/usr/bin/env python3
"""Ingest a folder of research papers, end to end, unattended.

Per paper: PDF -> markdown (Marker) -> metadata (title/authors/year/DOI/arXiv)
-> the full ingestion pipeline (scripts/ingest_book.py) -> paper metadata written
onto the note row and its NoteSource node in Neo4j.

A manifest records every paper's status, timing and ids, so a re-run skips what
already landed and retries only what failed.

Usage:
    python scripts/ingest_papers.py --dir ~/papers
    python scripts/ingest_papers.py --dir ~/papers --limit 3
    python scripts/ingest_papers.py --dir ~/papers --retry-failed
    python scripts/ingest_papers.py --dir ~/papers --convert-only

Requires: marker-pdf (see pyproject.toml) and a running backend stack, since the
pipeline writes to Postgres and Neo4j.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"  # the DEBUG test user
MANIFEST_NAME = "papers-manifest.json"
DEFAULT_WORK_DIR = REPO_ROOT / "data" / "papers"
CONTAINER_REPO = "/app"  # ./data and ./scripts are mounted here in docker-compose

# Metadata patterns. Papers are inconsistent, so each is best-effort and the
# pipeline still runs when one misses.
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[-._;()/:a-z0-9]+)\b", re.I)
ARXIV_RE = re.compile(r"arxiv[:\s]*((?:\d{4}\.\d{4,5})(?:v\d+)?|[a-z-]+/\d{7})", re.I)
YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")
# An author line: "A. B. Smith, C. Doe and E. Roe" — commas/ands, few words each.
AUTHOR_HINT_RE = re.compile(r"^[A-Z][\w.'-]+(?:\s+[A-Z][\w.'-]+){0,3}(?:\s*,\s*|\s+and\s+)", re.M)


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #

class Manifest:
    """Per-paper status on disk, so a re-run resumes instead of redoing."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {"version": 1, "papers": {}}
        if path.exists():
            try:
                self.data = json.loads(path.read_text())
            except json.JSONDecodeError:
                print(f"! manifest unreadable, starting fresh: {path}")

    def entry(self, key: str) -> dict[str, Any]:
        return self.data["papers"].get(key, {})

    def record(self, key: str, **fields: Any) -> None:
        current = self.data["papers"].setdefault(key, {})
        current.update(fields)
        self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, default=str))

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.data["papers"].values():
            status = entry.get("status", "unknown")
            counts[status] = counts.get(status, 0) + 1
        return counts


def file_key(pdf: Path) -> str:
    """Identify a paper by content, so renaming a file doesn't re-ingest it."""
    digest = hashlib.sha256()
    with pdf.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()[:16]


# --------------------------------------------------------------------------- #
# PDF -> markdown
# --------------------------------------------------------------------------- #

_MARKER_MODELS = None


def convert_pdf(pdf: Path, out_md: Path, images_dir: Path) -> None:
    """Convert one PDF to markdown with Marker, reusing loaded models."""
    global _MARKER_MODELS
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered

    if _MARKER_MODELS is None:
        print("   loading Marker models (first paper only)…")
        _MARKER_MODELS = create_model_dict()

    converter = PdfConverter(artifact_dict=_MARKER_MODELS)
    rendered = converter(str(pdf))
    text, _, images = text_from_rendered(rendered)

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(text, encoding="utf-8")

    images_dir.mkdir(parents=True, exist_ok=True)
    for name, image in (images or {}).items():
        try:
            image.save(images_dir / name)
        except Exception as exc:  # a bad figure must not lose the paper
            print(f"   ! could not save {name}: {exc}")


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #

def extract_metadata(markdown: str, fallback_title: str) -> dict[str, Any]:
    """Pull title, authors, year, DOI and arXiv id out of a paper's front matter."""
    head = markdown[:4000]
    lines = [line.strip() for line in head.splitlines()]

    title = None
    for line in lines:
        if line.startswith("#"):
            candidate = line.lstrip("#").strip()
            if len(candidate) > 8:
                title = candidate
                break
    if not title:
        for line in lines:
            if len(line) > 15 and not line.startswith(("!", "|", ">")):
                title = line
                break
    title = (title or fallback_title)[:480]

    authors: list[str] = []
    title_seen = False
    for line in lines[:40]:
        if not line:
            continue
        if title and line.lstrip("#").strip() == title:
            title_seen = True
            continue
        if title_seen and AUTHOR_HINT_RE.search(line + " and "):
            parts = re.split(r",| and ", line.replace("*", ""))
            authors = [p.strip() for p in parts if 2 < len(p.strip()) < 60][:12]
            if authors:
                break

    doi = DOI_RE.search(head)
    arxiv = ARXIV_RE.search(head)
    years = YEAR_RE.findall(head)

    return {
        "title": title,
        "authors": authors,
        "year": int(years[0]) if years else None,
        "doi": doi.group(1).rstrip(".") if doi else None,
        "arxiv_id": arxiv.group(1) if arxiv else None,
    }


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #

def _container_path(path: Path) -> str:
    """Map a repo path to where the API container mounts it."""
    return str(Path(CONTAINER_REPO) / path.resolve().relative_to(REPO_ROOT))


def run_pipeline(
    md_path: Path,
    images_dir: Path,
    note_id: str,
    title: str,
    user_id: str,
    extra_args: list[str],
    log_path: Path,
    runner: str = "docker",
) -> tuple[bool, str]:
    """Run the existing unattended pipeline for one paper.

    The pipeline needs the backend's dependencies and database access, which the
    API container already has — so by default it runs there, with ./data and
    ./scripts mounted. `--runner local` uses the current interpreter instead.
    """
    if runner == "docker":
        cmd = [
            "docker", "compose", "exec", "-T",
            # the scripts dir is not a package, so `backend` needs to be importable
            "-e", "PYTHONPATH=/app",
            "api",
            "python", "/app/scripts/ingest_book.py",
            "--md-path", _container_path(md_path),
            "--images-dir", _container_path(images_dir),
            "--note-title", title,
            "--note-id", note_id,
            "--user-id", user_id,
            *extra_args,
        ]
    else:
        cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "ingest_book.py"),
            "--md-path", str(md_path),
            "--images-dir", str(images_dir),
            "--note-title", title,
            "--note-id", note_id,
            "--user-id", user_id,
            *extra_args,
        ]
    with log_path.open("w") as log:
        log.write(" ".join(cmd) + "\n\n")
        log.flush()
        proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=REPO_ROOT)
    if proc.returncode == 0:
        return True, ""
    tail = log_path.read_text(errors="replace").strip().splitlines()[-12:]
    return False, "\n".join(tail)


def tag_paper_via_container(note_id: str, meta: dict[str, Any], source_path: Path) -> None:
    """Same tagging, executed inside the API container (which holds the DB deps)."""
    payload = json.dumps({"note_id": note_id, "meta": meta, "file": source_path.name})
    code = (
        "import asyncio, json, os, sys\n"
        "sys.path.insert(0, '/app')\n"
        "from scripts.ingest_papers import tag_paper\n"
        "from pathlib import Path\n"
        "data = json.loads(os.environ['GR_PAPER_JSON'])\n"
        "asyncio.run(tag_paper(data['note_id'], data['meta'], Path(data['file'])))\n"
    )
    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "-e", f"GR_PAPER_JSON={payload}", "api", "python", "-"],
        input=code, text=True, capture_output=True, cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[-400:])


async def tag_paper(note_id: str, meta: dict[str, Any], source_path: Path) -> None:
    """Mark the note as a paper and put its metadata where the graph can use it."""
    from backend.db.neo4j_client import get_neo4j_client
    from backend.db.postgres_client import get_postgres_client

    # notes.resource_type is constrained to a fixed list, so 'research' carries the
    # kind and the 'paper' tag marks these as papers specifically.
    tags = ["paper"]
    if meta.get("year"):
        tags.append(f"year:{meta['year']}")
    if meta.get("doi"):
        tags.append(f"doi:{meta['doi']}")
    if meta.get("arxiv_id"):
        tags.append(f"arxiv:{meta['arxiv_id']}")
    for author in (meta.get("authors") or [])[:6]:
        tags.append(f"author:{author}")

    source_url = None
    if meta.get("doi"):
        source_url = f"https://doi.org/{meta['doi']}"
    elif meta.get("arxiv_id"):
        source_url = f"https://arxiv.org/abs/{meta['arxiv_id']}"

    pg = await get_postgres_client()
    await pg.execute_update(
        """
        UPDATE notes
           SET resource_type = 'research',
               tags = :tags,
               source_url = COALESCE(:source_url, source_url)
         WHERE id = CAST(:note_id AS uuid)
        """,
        {"note_id": note_id, "tags": tags, "source_url": source_url},
    )

    # The same metadata on the graph side, so Phase 2 can draw paper-to-paper edges.
    neo4j = await get_neo4j_client()
    await neo4j.execute_query(
        """
        MERGE (n:NoteSource {id: $note_id})
          SET n.title = $title,
              n.resource_type = 'paper',
              n.year = $year,
              n.doi = $doi,
              n.arxiv_id = $arxiv_id,
              n.authors = $authors,
              n.source_file = $source_file
        """,
        {
            "note_id": note_id,
            "title": meta.get("title"),
            "year": meta.get("year"),
            "doi": meta.get("doi"),
            "arxiv_id": meta.get("arxiv_id"),
            "authors": meta.get("authors") or [],
            "source_file": source_path.name,
        },
    )


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", help="Folder of PDFs to ingest")
    parser.add_argument("--file", action="append", default=[], help="Single PDF (repeatable)")
    parser.add_argument("--work-dir", default=None, help="Where converted markdown lands (default: <dir>/.graphrecall)")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--limit", type=int, default=None, help="Stop after N papers")
    parser.add_argument("--retry-failed", action="store_true", help="Retry papers that previously failed")
    parser.add_argument("--reingest", action="store_true", help="Ingest again even if already done")
    parser.add_argument("--convert-only", action="store_true", help="PDF -> markdown + metadata, no pipeline")
    parser.add_argument("--skip-cards", action="store_true", help="Skip flashcard and quiz generation (faster, cheaper)")
    parser.add_argument("--local-embeddings", action="store_true", help="Embed locally instead of via Gemini")
    parser.add_argument("--concept-batch-size", type=int, default=10)
    parser.add_argument(
        "--runner", choices=["docker", "local"], default="docker",
        help="Where the pipeline runs: the API container (default) or this interpreter",
    )
    return parser.parse_args()


def collect_pdfs(args: argparse.Namespace) -> list[Path]:
    pdfs: list[Path] = [Path(os.path.expanduser(f)).resolve() for f in args.file]
    if args.dir:
        root = Path(os.path.expanduser(args.dir)).resolve()
        pdfs.extend(sorted(p for p in root.rglob("*.pdf") if not p.name.startswith(".")))
    seen: set[Path] = set()
    unique = []
    for pdf in pdfs:
        if pdf not in seen and pdf.is_file():
            seen.add(pdf)
            unique.append(pdf)
    return unique


async def main() -> int:
    args = parse_args()
    pdfs = collect_pdfs(args)
    if not pdfs:
        print("No PDFs found. Pass --dir <folder> or --file <paper.pdf>.")
        return 1

    # Default work dir lives in the repo because the API container mounts ./data,
    # and the pipeline runs in that container.
    base = Path(os.path.expanduser(args.work_dir)).resolve() if args.work_dir else DEFAULT_WORK_DIR
    base.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(base / MANIFEST_NAME)

    extra: list[str] = ["--concept-batch-size", str(args.concept_batch_size)]
    if args.skip_cards:
        extra += ["--skip-flashcards", "--skip-quizzes"]
    if args.local_embeddings:
        extra.append("--local-embeddings")

    print(f"{len(pdfs)} PDF(s) found · work dir {base}")
    done = failed = skipped = 0

    for index, pdf in enumerate(pdfs, start=1):
        if args.limit and done + failed >= args.limit:
            break

        key = file_key(pdf)
        entry = manifest.entry(key)
        status = entry.get("status")
        if status == "done" and not args.reingest:
            skipped += 1
            continue
        if status == "failed" and not (args.retry_failed or args.reingest):
            skipped += 1
            continue

        print(f"\n[{index}/{len(pdfs)}] {pdf.name}")
        started = time.time()
        md_path = base / f"{key}.md"
        images_dir = base / f"{key}_images"

        try:
            if md_path.exists() and not args.reingest:
                print("   markdown already converted")
            else:
                print("   converting…")
                convert_pdf(pdf, md_path, images_dir)
            markdown = md_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            print(f"   ! conversion failed: {exc}")
            manifest.record(key, file=str(pdf), status="failed", stage="convert", error=str(exc))
            failed += 1
            continue

        images_dir.mkdir(parents=True, exist_ok=True)
        meta = extract_metadata(markdown, pdf.stem)
        print(f"   title: {meta['title'][:70]}")
        if meta.get("year") or meta.get("doi") or meta.get("arxiv_id"):
            print(f"   meta: year={meta.get('year')} doi={meta.get('doi')} arxiv={meta.get('arxiv_id')}")
        manifest.record(
            key, file=str(pdf), markdown=str(md_path), metadata=meta,
            chars=len(markdown), status="converted",
        )

        if args.convert_only:
            done += 1
            continue

        note_id = entry.get("note_id") or str(uuid.uuid4())
        log_path = base / f"{key}.log"
        print("   ingesting…")
        ok, tail = run_pipeline(
            md_path, images_dir, note_id, meta["title"], args.user_id, extra, log_path, args.runner
        )
        elapsed = round(time.time() - started, 1)

        if not ok:
            print(f"   ! pipeline failed after {elapsed}s — log: {log_path}")
            if tail:
                print("   " + tail.replace("\n", "\n   "))
            manifest.record(key, status="failed", stage="pipeline", note_id=note_id, seconds=elapsed, log=str(log_path))
            failed += 1
            continue

        try:
            if args.runner == "docker":
                tag_paper_via_container(note_id, meta, pdf)
            else:
                await tag_paper(note_id, meta, pdf)
        except Exception as exc:
            print(f"   ! ingested but tagging failed: {exc}")

        print(f"   done in {elapsed}s · note {note_id}")
        manifest.record(key, status="done", note_id=note_id, seconds=elapsed, log=str(log_path))
        done += 1

    print(f"\n{done} ingested · {failed} failed · {skipped} skipped")
    print(f"manifest: {manifest.path}")
    print(f"status counts: {manifest.summary()}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
