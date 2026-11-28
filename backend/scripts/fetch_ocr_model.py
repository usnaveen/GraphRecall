"""Fetch the OCRia-nano OCR model that document ingestion uses for scanned pages and images.

    python -m backend.scripts.fetch_ocr_model            # download + verify (the Dockerfile runs this)
    python -m backend.scripts.fetch_ocr_model --check    # report what is installed, download nothing

LiteParse downloads the model package and verifies it; set LITEPARSE_MODEL_DIR to choose where it lives
(the Docker image keeps it under /app so the non-root app user can read it). Without the model, text PDFs
still ingest, and scanned pages are reported as skipped rather than read by a different OCR engine.

Model: llamaindex OCRia-nano (8.1M parameters, ONNX). Licence: modified Open RAIL-M, free for personal use
and for organisations under $2M in revenue and funding, not for building a competing parsing product.
"""

from __future__ import annotations

import argparse
import sys

VERSION = "ocria-nano@1.0.0"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    from liteparse import models

    if not args.check:
        path = models.pull(VERSION, quiet=False)
        print(f"installed {VERSION} at {path}")
    installed = [m for m in models.list() if m.name == "ocria-nano"]
    for m in installed:
        print(f"{m.name} {m.version} {m.size_bytes / 1e6:.1f} MB complete={m.complete} at {m.path}")
    ok = any(m.complete for m in installed)
    if not ok:
        print("OCRia-nano is not installed: scanned pages and images can't be read", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
